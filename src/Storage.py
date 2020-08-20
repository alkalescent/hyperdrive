import os
import boto3
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from multiprocessing import Pool
from Constants import PathFinder
import Constants as C


class Store:
    def __init__(self):
        load_dotenv()
        self.bucket_name = self.get_bucket_name()
        self.finder = PathFinder()

    def get_bucket_name(self):
        return os.environ.get(
            'S3_BUCKET') if not C.DEV else os.environ.get('S3_DEV_BUCKET')

    def upload_file(self, path):
        s3 = boto3.resource('s3')
        bucket = s3.Bucket(self.bucket_name)
        bucket.upload_file(path, path)

    def upload_dir(self, path, truncate=False):
        paths = self.finder.get_all_paths(path, truncate=truncate)
        with Pool() as p:
            p.map(self.upload_file, paths)

    def delete_objects(self, keys):
        if keys:
            objects = [{'Key': key} for key in keys]
            s3 = boto3.resource('s3')
            bucket = s3.Bucket(self.bucket_name)
            bucket.delete_objects(Delete={'Objects': objects})

    def get_all_keys(self):
        s3 = boto3.resource('s3')
        bucket = s3.Bucket(self.bucket_name)
        keys = [obj.key for obj in bucket.objects.filter()]
        return keys

    def key_exists(self, key, download=False):
        try:
            s3 = boto3.resource('s3')
            bucket = s3.Bucket(self.bucket_name)
            bucket.Object(key).load()
        except ClientError:
            return False
        else:
            return True

    def download_file(self, key):
        try:
            self.finder.make_path(key)
            s3 = boto3.resource('s3')
            with open(key, 'wb') as file:
                bucket = s3.Bucket(self.bucket_name)
                bucket.download_fileobj(key, file)
        except ClientError as e:
            print(f'{key} does not exist in S3.')
            os.remove(key)
            raise e

    def rename_key(self, old_key, new_key):
        s3 = boto3.resource('s3')
        s3.Object(self.bucket_name, new_key).copy_from(
            CopySource=f'{self.bucket_name}/{old_key}')
        s3.Object(self.bucket_name, old_key).delete()
