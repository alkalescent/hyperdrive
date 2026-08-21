"""AWS S3 storage utilities for file operations."""

import os
from datetime import UTC, datetime, timedelta
from multiprocessing import Pool
from typing import Any

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import find_dotenv, load_dotenv

from . import Constants as C
from .Constants import PathFinder


class Store:
    """AWS S3 storage client for file operations.

    Provides methods for uploading, downloading, copying, and deleting
    files and directories in S3 buckets.

    Attributes:
        bucket_name: Name of the S3 bucket to use.
        finder: PathFinder instance for path operations.
    """

    def __init__(self) -> None:
        """Initialize the Store with bucket configuration from environment."""
        load_dotenv(find_dotenv("config.env"))
        self.bucket_name = self.get_bucket_name()
        self.finder = PathFinder()

    def get_bucket_name(self) -> str:
        """Get the S3 bucket name based on environment.

        Returns:
            The production or dev bucket name depending on C.DEV setting.
        """
        bucket = (
            os.environ.get("S3_BUCKET")
            if not C.DEV
            else os.environ.get("S3_DEV_BUCKET")
        )
        return bucket or ""

    def get_bucket(self) -> Any:
        """Get the S3 bucket resource.

        Returns:
            A boto3 S3 Bucket resource object.
        """
        s3 = boto3.resource(
            "s3",
            config=Config(
                connect_timeout=C.API_TIMEOUT,
                read_timeout=C.API_TIMEOUT,
                retries={"max_attempts": C.DEFAULT_RETRIES, "mode": "standard"},
                tcp_keepalive=True,
            ),
        )
        bucket = s3.Bucket(self.bucket_name)
        return bucket

    def upload_file(self, path: str) -> None:
        """Upload a local file to S3.

        Args:
            path: Local file path to upload.
        """
        bucket = self.get_bucket()
        key = path.replace("\\", "/")
        bucket.upload_file(path, key)

    def upload_dir(self, **kwargs: Any) -> None:
        """Upload all files in a directory to S3.

        Args:
            **kwargs: Arguments passed to PathFinder.get_all_paths().
        """
        paths = self.finder.get_all_paths(**kwargs)
        with Pool() as p:
            p.map(self.upload_file, paths)

    def delete_objects(self, keys: list[str]) -> None:
        """Delete multiple objects from S3.

        Args:
            keys: List of S3 keys to delete.
        """
        if keys:
            objects = [{"Key": key.replace("\\", "/")} for key in keys]
            bucket = self.get_bucket()
            bucket.delete_objects(Delete={"Objects": objects})

    def get_keys(self, filter: str = "") -> list[str]:
        """List all keys in the bucket matching a prefix.

        Args:
            filter: Prefix to filter keys by.

        Returns:
            List of matching S3 keys.
        """
        bucket = self.get_bucket()
        keys = [obj.key for obj in bucket.objects.filter(Prefix=filter)]
        return keys

    def key_exists(self, key: str, download: bool = False) -> bool:
        """Check if a key exists in S3.

        Args:
            key: S3 key to check.
            download: If True, download the file to verify existence.

        Returns:
            True if the key exists, False otherwise.
        """
        key = key.replace("\\", "/")
        try:
            if download:
                self.download_file(key)
            else:
                bucket = self.get_bucket()
                bucket.Object(key).load()
        except ClientError:
            return False
        else:
            return True

    def download_file(self, key: str) -> None:
        """Download a file from S3.

        Args:
            key: S3 key to download.

        Raises:
            ClientError: If the key does not exist in S3.
        """
        try:
            self.finder.make_path(key)
            with open(key, "wb") as file:
                bucket = self.get_bucket()
                s3_key = key.replace("\\", "/")
                bucket.download_fileobj(s3_key, file)
        except ClientError as e:
            print(f"{key} does not exist in S3.")
            os.remove(key)
            raise e

    def download_dir(self, path: str) -> None:
        """Download all files in an S3 directory.

        Args:
            path: S3 prefix path to download.
        """
        keys = self.get_keys(path)
        with Pool() as p:
            p.starmap(self.key_exists, zip(keys, [True] * len(keys), strict=True))

    def copy_object(self, src: str, dst: str) -> None:
        """Copy an object within S3.

        Args:
            src: Source S3 key.
            dst: Destination S3 key.
        """
        src = src.replace("\\", "/")
        dst = dst.replace("\\", "/")
        bucket = self.get_bucket()
        copy_source = {"Bucket": self.bucket_name, "Key": src}
        bucket.copy(copy_source, dst)

    def rename_key(self, old_key: str, new_key: str) -> None:
        """Rename an S3 object by copying and deleting.

        Args:
            old_key: Current S3 key.
            new_key: New S3 key.
        """
        old_key = old_key.replace("\\", "/")
        new_key = new_key.replace("\\", "/")
        self.copy_object(old_key, new_key)
        self.delete_objects([old_key])

    def last_modified(self, key: str) -> datetime:
        """Get the last modified time of an S3 object.

        Args:
            key: S3 key to check.

        Returns:
            The last modified datetime (timezone-aware UTC).
        """
        key = key.replace("\\", "/")
        bucket = self.get_bucket()
        obj = bucket.Object(key)
        return obj.last_modified  # S3 returns timezone-aware UTC datetime

    def modified_delta(self, key: str) -> timedelta:
        """Get time since an S3 object was last modified.

        Args:
            key: S3 key to check.

        Returns:
            Time elapsed since last modification.
        """
        key = key.replace("\\", "/")
        then = self.last_modified(key)
        now = datetime.now(UTC)
        return now - then
