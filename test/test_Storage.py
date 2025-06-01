import os
import shutil
import sys
import pytest
from botocore.exceptions import ClientError
from dotenv import load_dotenv, find_dotenv
sys.path.append('hyperdrive')
from Storage import Store  # noqa autopep8
import Constants as C  # noqa autopep8
from Utils import SwissArmyKnife  # noqa autopep8

load_dotenv(find_dotenv('config.env'))
knife = SwissArmyKnife()
store = Store()
store = knife.use_dev(store)

run_id = ''
if C.CI:
    run_id = os.environ['RUN_ID']

symbols_path = store.finder.get_symbols_path()

test_file1 = f'{C.DEV_DIR}/{run_id}_x'
test_file2 = f'{C.DEV_DIR}/{run_id}_y'


class TestStore:
    def test_init(self):
        assert type(store).__name__ == 'Store'
        assert hasattr(store, 'bucket_name')
        assert hasattr(store, 'finder')

    def test_upload_file(self):
        store.finder.make_path(test_file1)
        with open(test_file1, 'w') as file:
            file.write('123')
        store.upload_file(test_file1)
        assert store.key_exists(test_file1)

    def test_upload_dir(self):
        with open(test_file2, 'w') as file:
            file.write('b')
        store.upload_dir(path=C.DEV_DIR)
        assert store.key_exists(test_file2)

    def test_delete_objects(self):
        shutil.rmtree(C.DEV_DIR)
        store.delete_objects([test_file1, test_file2])
        assert not store.key_exists(test_file2)

    def test_get_keys(self):
        keys = set(store.get_keys())

        assert symbols_path in keys
        assert 'README.md' in keys

    def test_key_exists(self):
        assert store.key_exists(symbols_path)
        assert not store.key_exists(test_file1)

    def test_download_file(self):
        assert not os.path.exists(test_file1)
        with pytest.raises(ClientError):
            store.download_file(test_file1)
        assert not os.path.exists(test_file1)

        if os.path.exists(symbols_path):
            os.remove(symbols_path)
        assert not os.path.exists(symbols_path)
        store.download_file(symbols_path)
        assert os.path.exists(symbols_path)

    def test_rename_key(self):
        src_path = f'{symbols_path}_{run_id}_SRC2'
        dst_path = f'{symbols_path}_{run_id}_DST2'

        assert not store.key_exists(src_path)
        store.copy_object(symbols_path, src_path)
        assert store.key_exists(src_path)

        assert not store.key_exists(dst_path)
        store.rename_key(src_path, dst_path)
        assert store.key_exists(dst_path)

        store.delete_objects([dst_path])
