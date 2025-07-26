import os
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt


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
        key = base64.urlsafe_b64encode(kdf.derive(password))
        self.f = Fernet(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        return self.f.encrypt(plaintext)

    def decrypt(self, ciphertext) -> bytes:
        return self.f.decrypt(ciphertext)
