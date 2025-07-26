import os
from typing import Union
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


FlexibleBytes = Union[str, bytes]


class Cryptographer:
    """
    A class for symmetric encryption using AES-256 in GCM mode.

    The key is derived from a user-provided password and salt using Scrypt.
    This approach is considered post-quantum
    resistant for symmetric encryption.

    Derives a 256-bit (32-byte) key from the password and salt.

    Args:
        password (FlexibleBytes):
            The password to use for key derivation.
        salt (FlexibleBytes):
            A random salt, which should be stored and reused for decryption.
    """

    def __init__(self, password: FlexibleBytes, salt: FlexibleBytes):
        password = self.convert_to_bytes(password)
        salt = self.convert_to_bytes(salt)
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
        self.aesgcm = AESGCM(self.key)
        # Define nonce size for AES-GCM
        self.nonce_size = 12

    def convert_to_bytes(self, value: FlexibleBytes) -> bytes:
        """
        Convert a string to bytes, if necessary.

        Args:
            value (FlexibleBytes): The value to convert.

        Returns:
            bytes: The converted value.
        """
        if isinstance(value, str):
            return value.encode('UTF-8')
        return value

    def encrypt(self, plaintext: FlexibleBytes) -> bytes:
        """
        Encrypts and authenticates plaintext using AES-256-GCM.

        Args:
            plaintext (FlexibleBytes): The data to encrypt.

        Returns:
            bytes: A self-contained ciphertext blob in the format:
            nonce + encrypted_data_and_tag.
        """
        plaintext = self.convert_to_bytes(plaintext)
        # Generate a random nonce. It must be unique for each encryption.
        nonce = os.urandom(self.nonce_size)
        # Encrypt the data. The result includes the authentication tag.
        ciphertext = self.aesgcm.encrypt(nonce, plaintext, None)
        # Prepend the nonce to the ciphertext for use during decryption
        return nonce + ciphertext

    def decrypt(self, ciphertext: bytes) -> FlexibleBytes:
        """
        Decrypts and verifies a ciphertext blob.

        Args:
            ciphertext (bytes): The combined nonce and ciphertext.

        Returns:
            FlexibleBytes: The original plaintext
                if decryption and authentication are successful.
        """
        # Extract the nonce
        nonce = ciphertext[:self.nonce_size]
        # Extract the actual ciphertext (without the nonce)
        ciphertext = ciphertext[self.nonce_size:]
        # Decrypt the data. The tag is verified automatically.
        plaintext = self.aesgcm.decrypt(nonce, ciphertext, None)
        try:
            plaintext = plaintext.decode('UTF-8')
        except UnicodeDecodeError:
            pass
        return plaintext
