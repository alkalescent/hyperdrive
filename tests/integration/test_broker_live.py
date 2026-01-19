"""Integration tests for Broker module.

These tests make real API calls to Robinhood.
Run with: pytest tests/integration/ -v
"""


class TestRobinhoodIntegration:
    """Integration tests for Robinhood API."""

    def test_robinhood_login(self):
        """Test real Robinhood login."""
        from hyperdrive.Broker import Robinhood

        rh = Robinhood()
        holdings = rh.get_holdings()
        assert isinstance(holdings, dict)

    def test_robinhood_symbols(self):
        """Test real Robinhood symbols."""
        from hyperdrive.Broker import Robinhood

        rh = Robinhood()
        symbols = rh.get_symbols()
        assert isinstance(symbols, list)
