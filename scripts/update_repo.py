import shutil

from hyperdrive.Constants import DATA_DIR, MODELS_DIR
from hyperdrive.Storage import Store

store = Store()
# delete everything in s3 bucket unless it is in data/ or models/
repo_keys = [
    key
    for key in store.get_keys()
    if key.find(f"{DATA_DIR}/") and key.find(f"{MODELS_DIR}/")
]
store.delete_objects(repo_keys)
shutil.rmtree(DATA_DIR)
shutil.rmtree(MODELS_DIR)
store.upload_dir(path=".", truncate=True)
