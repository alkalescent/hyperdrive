"""
Integration tests for Exchange module.

These tests make real API calls to exchange testnet/paper APIs.
Run with: pytest tests/integration/ -v
"""
import pytest
import sys

sys.path.append('hyperdrive')
import Constants as C  # noqa: E402


class TestAlpacaExIntegration:
    """Integration tests for Alpaca Exchange API."""

    def test_alpaca_paper_account(self):
        """Test real Alpaca paper account."""
        from Exchange import AlpacaEx
        alpc = AlpacaEx(paper=True)
        account = alpc.get_account()
        assert account['status'] == 'ACTIVE'

    def test_alpaca_paper_positions(self):
        """Test real Alpaca paper positions."""
        from Exchange import AlpacaEx
        alpc = AlpacaEx(paper=True)
        positions = alpc.get_positions()
        assert isinstance(positions, list)


class TestBinanceIntegration:
    """Integration tests for Binance Testnet."""

    def test_binance_testnet_connection(self):
        """Test real Binance testnet connection."""
        from Exchange import Binance
        bn = Binance(testnet=True)
        info = bn.client.get_symbol_info('BTCUSDT')
        assert info is not None


class TestKrakenIntegration:
    """Integration tests for Kraken API."""

    def test_kraken_balance(self):
        """Test real Kraken balance check."""
        from Exchange import Kraken
        kr = Kraken(test=True)
        balance = kr.get_balance()
        assert isinstance(balance, dict)
