"""Tests for the Crypt module."""

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from hyperdrive.Crypt import Cryptographer

crypt = Cryptographer("password", "salt")


class TestCryptographer:
    """Tests for the Cryptographer encryption utility class."""

    def test_init(self) -> None:
        """Test Cryptographer initialization."""
        assert hasattr(crypt, "key")
        assert isinstance(crypt.key, bytes)
        assert hasattr(crypt, "aesgcm")
        assert isinstance(crypt.aesgcm, AESGCM)
        assert hasattr(crypt, "nonce_size")
        assert isinstance(crypt.nonce_size, int)

    def test_encrypt_and_decrypt(self) -> None:
        """Test encrypting and decrypting a secret."""
        secret = "secret"
        ciphertext = crypt.encrypt(secret)
        assert ciphertext != secret
        plaintext = crypt.decrypt(ciphertext)
        assert plaintext == secret

    def test_convert_to_bytes_string(self) -> None:
        """Test convert_to_bytes with string input."""
        result = crypt.convert_to_bytes("hello")
        assert isinstance(result, bytes)
        assert result == b"hello"

    def test_convert_to_bytes_bytes(self) -> None:
        """Test convert_to_bytes with bytes input (line 55)."""
        input_bytes = b"already bytes"
        result = crypt.convert_to_bytes(input_bytes)
        assert result == input_bytes

    def test_encrypt_bytes(self) -> None:
        """Test encrypting bytes directly."""
        secret = b"secret bytes"
        ciphertext = crypt.encrypt(secret)
        assert ciphertext != secret
        plaintext = crypt.decrypt(ciphertext)
        # decrypt returns string if UTF-8 decodable
        assert plaintext == "secret bytes"

    def test_decrypt_binary_data(self) -> None:
        """Test decrypting binary data that can't be decoded as UTF-8 (lines 95-96)."""
        # Create binary data that isn't valid UTF-8
        binary_data = bytes([0x80, 0x81, 0x82, 0xFF, 0xFE])
        ciphertext = crypt.encrypt(binary_data)
        plaintext = crypt.decrypt(ciphertext)
        # Should return bytes when UTF-8 decode fails
        assert plaintext == binary_data
        assert isinstance(plaintext, bytes)

    def test_init_with_bytes(self) -> None:
        """Test initializing with bytes password and salt."""
        crypt2 = Cryptographer(b"password bytes", b"salt bytes")
        assert hasattr(crypt2, "key")
        assert isinstance(crypt2.key, bytes)
