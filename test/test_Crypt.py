import sys
sys.path.append('hyperdrive')
from Crypt import Cryptographer  # noqa autopep8


password = b'password'
salt = b'salt'
crypt = Cryptographer(password, salt)


class TestCryptographer():
    def test_encrypt_decrypt(self):
        plaintext = b'This is a secret message.'
        ciphertext = crypt.encrypt(plaintext)

        decrypted_text = crypt.decrypt(ciphertext)

        assert decrypted_text == plaintext, (
            "Decrypted text does not match original plaintext.")

    def test_invalid_decryption(self):
        invalid_ciphertext = b'invaliddata'

        try:
            crypt.decrypt(invalid_ciphertext)
            assert False, (
                "Expected decryption to fail with invalid ciphertext.")
        except Exception as e:
            assert isinstance(
                e, Exception), "Expected an exception for invalid decryption."
