import os
from datetime import datetime, timedelta
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv, find_dotenv
from multiprocessing import Pool
from Constants import PathFinder
import Constants as C
# from typing import Optional


class Store:
    def __init__(self):
        load_dotenv(find_dotenv('config.env'))
        self.bucket_name = self.get_bucket_name()
        self.finder = PathFinder()

    def get_bucket_name(self):
        return os.environ.get(
            'S3_BUCKET') if not C.DEV else os.environ.get('S3_DEV_BUCKET')

    def get_bucket(self):
        s3 = boto3.resource('s3')
        bucket = s3.Bucket(self.bucket_name)
        return bucket

    def upload_file(self, path):
        bucket = self.get_bucket()
        key = path.replace('\\', '/')
        bucket.upload_file(path, key)

    def upload_dir(self, **kwargs):
        paths = self.finder.get_all_paths(**kwargs)
        with Pool() as p:
            p.map(self.upload_file, paths)

    def delete_objects(self, keys: list[str]) -> None:
        if keys:
            objects = [{'Key': key.replace('\\', '/')} for key in keys]
            bucket = self.get_bucket()
            bucket.delete_objects(Delete={'Objects': objects})

    def get_keys(self, filter: str = '') -> list[str]:
        bucket = self.get_bucket()
        keys = [obj.key for obj in bucket.objects.filter(Prefix=filter)]
        return keys

    def key_exists(self, key: str, download=False) -> bool:
        key = key.replace('\\', '/')
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
        try:
            self.finder.make_path(key)
            with open(key, 'wb') as file:
                bucket = self.get_bucket()
                s3_key = key.replace('\\', '/')
                bucket.download_fileobj(s3_key, file)
        except ClientError as e:
            print(f'{key} does not exist in S3.')
            os.remove(key)
            raise e

    def download_dir(self, path: str) -> None:
        keys = self.get_keys(path)
        with Pool() as p:
            p.starmap(self.key_exists, zip(keys, [True] * len(keys)))

    def copy_object(self, src: str, dst: str) -> None:
        src = src.replace('\\', '/')
        dst = dst.replace('\\', '/')
        bucket = self.get_bucket()
        copy_source = {
            'Bucket': self.bucket_name,
            'Key': src
        }
        bucket.copy(copy_source, dst)

    def rename_key(self, old_key: str, new_key: str) -> None:
        old_key = old_key.replace('\\', '/')
        new_key = new_key.replace('\\', '/')
        self.copy_object(old_key, new_key)
        self.delete_objects([old_key])

    def last_modified(self, key: str) -> datetime:
        key = key.replace('\\', '/')
        bucket = self.get_bucket()
        obj = bucket.Object(key)
        then = obj.last_modified.replace(tzinfo=None)
        return then

    def modified_delta(self, key: str) -> timedelta:
        key = key.replace('\\', '/')
        then = self.last_modified(key)
        now = datetime.utcnow()
        return now - then
