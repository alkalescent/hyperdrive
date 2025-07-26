import os
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class Cryptographer:
    """
    A class for symmetric encryption using AES-256 in GCM mode.

    The key is derived from a user-provided password and salt using Scrypt.
    This approach is considered post-quantum
    resistant for symmetric encryption.

    Derives a 256-bit (32-byte) key from the password and salt.

    Args:
        password (str):
            The password to use for key derivation.
        salt (str):
            A random salt, which should be stored and reused for decryption.
    """

    def __init__(self, password: str, salt: str):
        kdf = Scrypt(
            salt=salt,
            length=32,
            n=2**16,
            r=8,
            p=2,
        )
        # Store the key for encryption/decryption operations
        self.key = kdf.derive(password)
        # AES-GCM is the recommended AEAD cipher
        self.aesgcm = AESGCM(self._key)

    def encrypt(self, plaintext: bytes) -> bytes:
        return self.f.encrypt(plaintext)

    def decrypt(self, ciphertext) -> bytes:
        return self.f.decrypt(ciphertext)
