import sys
sys.path.append('hyperdrive')
from Crypt import Cryptographer  # noqa autopep8


password = b'securepassword'
salt = b'salt'


class TestCryptographer():
    def test_encrypt_decrypt(self):
        cryptographer = Cryptographer(password, salt)

        plaintext = b'This is a secret message.'
        ciphertext = cryptographer.encrypt(plaintext)

        decrypted_text = cryptographer.decrypt(ciphertext)

        assert decrypted_text == plaintext, "Decrypted text does not match original plaintext."

    def test_invalid_decryption(self):
        cryptographer = Cryptographer(password, salt)

        invalid_ciphertext = b'invaliddata'

        try:
            cryptographer.decrypt(invalid_ciphertext)
            assert False, "Expected decryption to fail with invalid ciphertext."
        except Exception as e:
            assert isinstance(
                e, Exception), "Expected an exception for invalid decryption."
