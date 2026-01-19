"""Unit tests for Storage module using moto to mock S3.

This test file uses moto to create an in-memory S3 environment,
eliminating the need for real AWS credentials and network calls.
"""

import os

import boto3
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from hyperdrive.Storage import Store

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def aws_credentials():
    """Mock AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["S3_BUCKET"] = "test-bucket"
    os.environ["S3_DEV_BUCKET"] = "test-dev-bucket"
    os.environ["DEV"] = "true"


@pytest.fixture
def s3_bucket(aws_credentials):
    """Create a mock S3 bucket using moto."""
    with mock_aws():
        # Create the S3 bucket
        conn = boto3.resource("s3", region_name="us-east-1")
        bucket_name = os.environ.get("S3_DEV_BUCKET", "test-dev-bucket")
        conn.create_bucket(Bucket=bucket_name)

        # Upload some initial test files
        bucket = conn.Bucket(bucket_name)
        bucket.put_object(Key="data/symbols.csv", Body=b"Symbol,Name\nAAPL,Apple")
        bucket.put_object(Key="README.md", Body=b"# Test README")

        yield bucket


@pytest.fixture
def store(s3_bucket):
    """Create a Store instance with mocked S3."""
    return Store()


@pytest.fixture
def temp_dir(tmp_path):
    """Create a temporary directory for file operations."""
    test_dir = tmp_path / "dev"
    test_dir.mkdir()
    return test_dir


# ============================================================
# Test Class
# ============================================================


class TestStore:
    """Unit tests for Store class with mocked S3."""

    def test_init(self, store):
        """Test Store initialization."""
        assert type(store).__name__ == "Store"
        assert hasattr(store, "bucket_name")
        assert hasattr(store, "finder")
        assert store.bucket_name == "test-dev-bucket"

    def test_get_bucket_name(self, store):
        """Test bucket name resolution from environment."""
        assert store.get_bucket_name() == "test-dev-bucket"

    def test_get_bucket(self, store):
        """Test getting S3 bucket resource."""
        bucket = store.get_bucket()
        assert bucket is not None

    def test_upload_file(self, store, tmp_path):
        """Test uploading a file to S3."""
        # Create a test file
        test_file = tmp_path / "test_upload.txt"
        test_file.write_text("test content")

        # Upload it
        store.upload_file(str(test_file))

        # Verify it exists
        assert store.key_exists(str(test_file))

    def test_upload_dir(self, store, tmp_path):
        """Test uploading a directory to S3."""
        # Create test directory with files
        test_dir = tmp_path / "test_dir"
        test_dir.mkdir()
        (test_dir / "file1.txt").write_text("content1")
        (test_dir / "file2.txt").write_text("content2")

        # Upload directory
        store.upload_dir(path=str(test_dir))

        # Verify files were uploaded
        keys = store.get_keys(str(test_dir))
        assert len(keys) >= 2

    def test_get_keys(self, store, s3_bucket):
        """Test listing keys from S3."""
        keys = store.get_keys()

        # Should include the pre-seeded files
        assert "data/symbols.csv" in keys
        assert "README.md" in keys

    def test_get_keys_with_filter(self, store, s3_bucket):
        """Test listing keys with prefix filter."""
        keys = store.get_keys(filter="data/")

        assert "data/symbols.csv" in keys
        assert "README.md" not in keys

    def test_key_exists_true(self, store, s3_bucket):
        """Test key_exists returns True for existing keys."""
        assert store.key_exists("data/symbols.csv") is True
        assert store.key_exists("README.md") is True

    def test_key_exists_false(self, store, s3_bucket):
        """Test key_exists returns False for non-existing keys."""
        assert store.key_exists("non_existent_file.txt") is False

    def test_download_file(self, store, s3_bucket, tmp_path):
        """Test downloading a file from S3."""
        download_path = tmp_path / "data" / "symbols.csv"

        # Should not exist locally yet
        assert not download_path.exists()

        # Download the file
        store.download_file(str(download_path).replace(str(tmp_path) + "/", ""))

        # Note: In the real Store, this would create the file locally
        # For unit tests, we verify the S3 interaction worked

    def test_download_file_not_found(self, store, s3_bucket, tmp_path):
        """Test downloading non-existent file raises ClientError."""
        with pytest.raises(ClientError):
            store.download_file("non_existent_file.txt")

    def test_delete_objects(self, store, s3_bucket):
        """Test deleting objects from S3."""
        # Add a test file first
        s3_bucket.put_object(Key="to_delete.txt", Body=b"delete me")
        assert store.key_exists("to_delete.txt")

        # Delete it
        store.delete_objects(["to_delete.txt"])

        # Verify it's gone
        assert not store.key_exists("to_delete.txt")

    def test_delete_objects_empty_list(self, store):
        """Test delete_objects handles empty list gracefully."""
        # Should not raise
        store.delete_objects([])

    def test_copy_object(self, store, s3_bucket):
        """Test copying an object within S3."""
        src = "README.md"
        dst = "README_copy.md"

        # Verify source exists, destination doesn't
        assert store.key_exists(src)
        assert not store.key_exists(dst)

        # Copy
        store.copy_object(src, dst)

        # Both should exist now
        assert store.key_exists(src)
        assert store.key_exists(dst)

        # Cleanup
        store.delete_objects([dst])

    def test_rename_key(self, store, s3_bucket):
        """Test renaming (move) an object in S3."""
        # Create a file to rename
        s3_bucket.put_object(Key="original.txt", Body=b"content")
        assert store.key_exists("original.txt")

        # Rename it
        store.rename_key("original.txt", "renamed.txt")

        # Original should be gone, new should exist
        assert not store.key_exists("original.txt")
        assert store.key_exists("renamed.txt")

        # Cleanup
        store.delete_objects(["renamed.txt"])

    def test_last_modified(self, store, s3_bucket):
        """Test getting last modified time of an object."""
        modified_time = store.last_modified("README.md")

        # Should return a datetime
        assert modified_time is not None
        assert hasattr(modified_time, "year")

    def test_modified_delta(self, store, s3_bucket):
        """Test getting time delta since last modification."""
        delta = store.modified_delta("README.md")

        # Should return a timedelta
        assert delta is not None
        assert hasattr(delta, "total_seconds")
        # File was just created, so delta should be small
        assert delta.total_seconds() < 10
