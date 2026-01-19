"""
Integration tests for Storage module.

These tests make real API calls to AWS S3.
Run with: pytest tests/integration/ -v
"""
import pytest
import sys

sys.path.append('hyperdrive')


class TestStorageIntegration:
    """Integration tests for S3 Storage."""

    def test_s3_connection(self):
        """Test real S3 connection."""
        from Storage import Store
        store = Store()
        keys = store.get_keys()
        assert len(keys) >= 0

    def test_s3_key_exists(self):
        """Test real S3 key existence check."""
        from Storage import Store
        store = Store()
        # Check for a known file
        symbols_path = store.finder.get_symbols_path()
        assert store.key_exists(symbols_path) is True

    def test_s3_get_keys(self):
        """Test real S3 list keys."""
        from Storage import Store
        store = Store()
        keys = store.get_keys('data/')
        assert isinstance(keys, list)
