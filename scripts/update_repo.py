import sys
import shutil
sys.path.append('hyperdrive')
from Storage import Store  # noqa autopep8
from Constants import DATA_DIR, MODELS_DIR  # noqa autopep8

store = Store()
# delete everything in s3 bucket unless it is in data/ or models/
repo_keys = [key for key in store.get_keys()
             if key.find(f'{DATA_DIR}/') and key.find(f'{MODELS_DIR}/')]
store.delete_objects(repo_keys)
shutil.rmtree(DATA_DIR)
shutil.rmtree(MODELS_DIR)
store.upload_dir(path='.', truncate=True)
