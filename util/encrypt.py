import os
import sys

from dotenv import find_dotenv, load_dotenv

from hyperdrive.Crypt import Cryptographer

load_dotenv(find_dotenv("config.env"))

password = os.environ["RH_PASSWORD"]
salt = os.environ["SALT"]
filename = os.environ.get("FILE") or sys.argv[1]

cryptographer = Cryptographer(password, salt)
with open(filename) as file:
    ciphertext = cryptographer.encrypt(file.read())

with open(f"{filename}.encrypted", "wb") as file:
    file.write(ciphertext)
