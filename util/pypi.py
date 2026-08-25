import os

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv("config.env"))
home = os.path.expanduser("~")
path = os.path.join(home, ".pypirc")
token = os.environ.get("PYPI")
test_token = os.environ.get("PYPI_TEST")

with open(path, "w") as file:
    if token:
        file.write("[pypi]\n")
        file.write("  username = __token__\n")
        file.write(f"  password = {token}\n")
    if test_token:
        file.write("[testpypi]\n")
        file.write("  username = __token__\n")
        file.write(f"  password = {test_token}\n")
