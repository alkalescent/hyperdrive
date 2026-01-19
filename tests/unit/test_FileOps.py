"""Unit tests for FileOps module with mocked S3 Store.

This test file uses moto to mock S3 operations, allowing tests
to run without real AWS credentials or network access.
"""

import json
import os
from datetime import datetime
from unittest.mock import MagicMock

import boto3
import pandas as pd
import pytest
from moto import mock_aws

from hyperdrive.FileOps import FileReader, FileWriter

# ============================================================
# Test Data
# ============================================================

SAMPLE_DATA = [
    {"symbol": "AMZN", "open": 2400.85, "volume": 402265, "date": "2020-12-25"},
    {"symbol": "AAPL", "open": 300.90, "volume": 502265, "date": "2015-01-15"},
]

SAMPLE_SNIPPET = {
    "symbol": "NVDA",
    "open": 445.00,
    "volume": 102265,
    "date": "2015-01-15",
}


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
    """Create mock S3 bucket with test data."""
    with mock_aws():
        conn = boto3.resource("s3", region_name="us-east-1")
        bucket_name = "test-dev-bucket"
        conn.create_bucket(Bucket=bucket_name)

        bucket = conn.Bucket(bucket_name)
        # Add symbols file
        bucket.put_object(Key="data/symbols.csv", Body=b"Symbol,Name\nAAPL,Apple")

        yield bucket


@pytest.fixture
def reader(s3_bucket):
    """Create FileReader with mocked S3."""
    return FileReader()


@pytest.fixture
def writer(s3_bucket):
    """Create FileWriter with mocked S3."""
    return FileWriter()


@pytest.fixture
def temp_files(tmp_path):
    """Create temporary file paths."""
    return {
        "json1": str(tmp_path / "test1.json"),
        "json2": str(tmp_path / "test2.json"),
        "csv1": str(tmp_path / "test1.csv"),
        "csv2": str(tmp_path / "test2.csv"),
    }


@pytest.fixture
def test_dataframes():
    """Create test DataFrames."""
    data_with_snippet = SAMPLE_DATA.copy()
    data_with_snippet.append(SAMPLE_SNIPPET)

    return {
        "test_df": pd.DataFrame(SAMPLE_DATA),
        "big_df": pd.DataFrame(data_with_snippet),
        "small_df": pd.DataFrame([SAMPLE_SNIPPET]),
        "empty_df": pd.DataFrame(),
    }


# ============================================================
# Test Classes
# ============================================================


class TestFileWriter:
    """Unit tests for FileWriter class."""

    def test_init(self, writer):
        """Test FileWriter initialization."""
        assert type(writer).__name__ == "FileWriter"
        assert hasattr(writer, "store")

    def test_save_json_empty(self, writer, temp_files):
        """Test saving empty JSON object."""
        writer.store.upload_file = MagicMock()  # Mock S3 upload

        result = writer.save_json(temp_files["json1"], {})

        assert result is True
        assert os.path.exists(temp_files["json1"])

        with open(temp_files["json1"]) as f:
            content = json.load(f)
        assert content == {}

    def test_save_json_with_data(self, writer, temp_files):
        """Test saving JSON with data."""
        writer.store.upload_file = MagicMock()

        result = writer.save_json(temp_files["json2"], SAMPLE_DATA)

        assert result is True
        assert os.path.exists(temp_files["json2"])

        with open(temp_files["json2"]) as f:
            content = json.load(f)
        assert content == SAMPLE_DATA

    def test_save_csv_empty(self, writer, temp_files, test_dataframes):
        """Test saving empty DataFrame returns False."""
        result = writer.save_csv(temp_files["csv1"], test_dataframes["empty_df"])
        assert result is False
        assert not os.path.exists(temp_files["csv1"])

    def test_save_csv_with_data(self, writer, temp_files, test_dataframes):
        """Test saving DataFrame to CSV."""
        writer.store.upload_file = MagicMock()

        result = writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        assert result is True
        assert os.path.exists(temp_files["csv2"])

    def test_update_csv_no_change(self, writer, reader, temp_files, test_dataframes):
        """Test update_csv doesn't overwrite with smaller data."""
        writer.store.upload_file = MagicMock()

        # First save
        writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        # Try to update with smaller df - should not change
        writer.update_csv(temp_files["csv2"], test_dataframes["small_df"])

        # Verify original data preserved
        df = pd.read_csv(temp_files["csv2"])
        assert len(df) == len(test_dataframes["test_df"])

    def test_update_csv_larger_data(self, writer, temp_files, test_dataframes):
        """Test update_csv overwrites with larger data."""
        writer.store.upload_file = MagicMock()

        # First save
        writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        # Update with larger df
        writer.update_csv(temp_files["csv2"], test_dataframes["big_df"])

        # Verify new data
        df = pd.read_csv(temp_files["csv2"])
        assert len(df) == len(test_dataframes["big_df"])

    def test_remove_files(self, writer, tmp_path):
        """Test removing files."""
        writer.store.delete_objects = MagicMock()

        # Create test file
        test_file = tmp_path / "to_remove.txt"
        test_file.write_text("test")
        assert test_file.exists()

        # Remove it
        writer.remove_files([str(test_file)])

        assert not test_file.exists()
        writer.store.delete_objects.assert_called_once()

    def test_rename_file(self, writer, tmp_path):
        """Test renaming files."""
        writer.store.rename_key = MagicMock()

        # Create test file
        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"
        src.write_text("test")

        # Rename it
        writer.rename_file(str(src), str(dst))

        assert not src.exists()
        assert dst.exists()
        writer.store.rename_key.assert_called_once()


class TestFileReader:
    """Unit tests for FileReader class."""

    def test_init(self, reader):
        """Test FileReader initialization."""
        assert type(reader).__name__ == "FileReader"
        assert hasattr(reader, "store")
        assert hasattr(reader, "traveller")

    def test_load_json(self, reader, writer, temp_files):
        """Test loading JSON file."""
        reader.store.download_file = MagicMock()
        writer.store.upload_file = MagicMock()

        # Save first
        writer.save_json(temp_files["json1"], SAMPLE_DATA)

        # Load it
        result = reader.load_json(temp_files["json1"])

        assert result == SAMPLE_DATA

    def test_load_csv(self, reader, writer, temp_files, test_dataframes):
        """Test loading CSV file."""
        reader.store.download_file = MagicMock()
        writer.store.upload_file = MagicMock()

        # Save first
        writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        # Load it
        result = reader.load_csv(temp_files["csv2"])

        assert len(result) == len(test_dataframes["test_df"])
        assert "symbol" in result.columns

    def test_check_update_same_size(self, reader, writer, temp_files, test_dataframes):
        """Test check_update with same size DataFrame."""
        writer.store.upload_file = MagicMock()
        reader.store.download_file = MagicMock()

        writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        result = reader.check_update(temp_files["csv2"], test_dataframes["test_df"])
        assert result is True

    def test_check_update_smaller(self, reader, writer, temp_files, test_dataframes):
        """Test check_update with smaller DataFrame returns False."""
        writer.store.upload_file = MagicMock()
        reader.store.download_file = MagicMock()

        writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        result = reader.check_update(temp_files["csv2"], test_dataframes["small_df"])
        assert result is False

    def test_check_update_larger(self, reader, writer, temp_files, test_dataframes):
        """Test check_update with larger DataFrame returns True."""
        writer.store.upload_file = MagicMock()
        reader.store.download_file = MagicMock()

        writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        result = reader.check_update(temp_files["csv2"], test_dataframes["big_df"])
        assert result is True

    def test_check_file_exists_false(self, reader):
        """Test check_file_exists returns False for non-existent file."""
        reader.store.key_exists = MagicMock(return_value=False)

        result = reader.check_file_exists("nonexistent.txt")
        assert result is False

    def test_check_file_exists_true(self, reader, tmp_path):
        """Test check_file_exists returns True for existing file."""
        reader.store.key_exists = MagicMock(return_value=True)

        test_file = tmp_path / "exists.txt"
        test_file.write_text("test")

        result = reader.check_file_exists(str(test_file))
        assert result is True

    def test_should_be_updated_new_file(self, reader):
        """Test should_be_updated returns True for non-existent file."""
        result = reader.should_be_updated("nonexistent.txt")
        assert result is True

    def test_should_be_updated_old_file(self, reader, tmp_path):
        """Test should_be_updated returns True for old file."""
        test_file = tmp_path / "old.txt"
        test_file.write_text("test")

        # Set modification time to 2 days ago
        old_time = datetime.now().timestamp() - (2 * 24 * 60 * 60)
        os.utime(str(test_file), (old_time, old_time))

        result = reader.should_be_updated(str(test_file))
        assert result is True

    def test_should_be_updated_recent_file(self, reader, tmp_path):
        """Test should_be_updated returns False for recent file."""
        test_file = tmp_path / "recent.txt"
        test_file.write_text("test")

        result = reader.should_be_updated(str(test_file))
        assert result is False
