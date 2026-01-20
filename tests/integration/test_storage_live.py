"""Integration tests for Storage module.

These tests make real API calls to AWS S3.
Run with: pytest tests/integration/ -v
"""


class TestStorageIntegration:
    """Integration tests for S3 Storage."""

    def test_s3_connection(self) -> None:
        """Test real S3 connection."""
        from hyperdrive.Storage import Store

        store = Store()
        keys = store.get_keys()
        assert len(keys) >= 0

    def test_s3_key_exists(self) -> None:
        """Test real S3 key existence check."""
        from hyperdrive.Storage import Store

        store = Store()
        # Check for a known file
        symbols_path = store.finder.get_symbols_path()
        assert store.key_exists(symbols_path) is True

    def test_s3_get_keys(self) -> None:
        """Test real S3 list keys."""
        from hyperdrive.Storage import Store

        store = Store()
        keys = store.get_keys("data/")
        assert isinstance(keys, list)
