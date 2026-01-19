import sys
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
sys.path.append('hyperdrive')
from Crypt import Cryptographer  # noqa autopep8


crypt = Cryptographer('password', 'salt')


class TestCryptographer:
    def test_init(self):
        assert hasattr(crypt, 'key')
        assert isinstance(crypt.key, bytes)
        assert hasattr(crypt, 'aesgcm')
        assert isinstance(crypt.aesgcm, AESGCM)
        assert hasattr(crypt, 'nonce_size')
        assert isinstance(crypt.nonce_size, int)

    def test_encrypt_and_decrypt(self):
        secret = 'secret'
        ciphertext = crypt.encrypt(secret)
        assert ciphertext != secret
        plaintext = crypt.decrypt(ciphertext)
        assert plaintext == secret
