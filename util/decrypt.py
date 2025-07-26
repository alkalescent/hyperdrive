import os
import sys
from dotenv import load_dotenv, find_dotenv
sys.path.append('hyperdrive')
from Crypt import Cryptographer  # noqa autopep8


load_dotenv(find_dotenv('config.env'))

password = os.environ['RH_PASSWORD']
salt = os.environ['SALT']
filename = os.environ.get('FILE') or sys.argv[1]

cryptographer = Cryptographer(password, salt)
with open(f'{filename}.encrypted', 'rb') as file:
    plaintext = cryptographer.decrypt(file.read())

with open(filename, 'w') as file:
    file.write(plaintext)
