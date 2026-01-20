"""Unit tests for Broker module with mocked Robinhood API.

This test file mocks all robin_stocks API calls for fast,
deterministic, offline testing.
"""

from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from hyperdrive import Constants as C

# ============================================================
# Sample Response Data
# ============================================================

SAMPLE_HOLDINGS = {
    "AAPL": {
        "name": "Apple Inc.",
        "quantity": "10",
        "average_buy_price": "150.00",
    },
    "AMZN": {
        "name": "Amazon.com",
        "quantity": "5",
        "average_buy_price": "3000.00",
    },
    "META": {
        "name": "Meta Platforms",
        "quantity": "20",
        "average_buy_price": "200.00",
    },
    "NFLX": {"name": "Netflix", "quantity": "8", "average_buy_price": "400.00"},
}

SAMPLE_HISTORICALS = [
    {
        "symbol": "AAPL",
        "begins_at": "2020-01-06T00:00:00Z",
        "open_price": "148.00",
        "close_price": "150.00",
        "high_price": "152.00",
        "low_price": "147.00",
        "volume": 1000000,
    },
    {
        "symbol": "AAPL",
        "begins_at": "2020-01-13T00:00:00Z",
        "open_price": "150.00",
        "close_price": "155.00",
        "high_price": "157.00",
        "low_price": "149.00",
        "volume": 1200000,
    },
]

NAME_MAPPING = {
    "AAPL": "Apple Inc.",
    "AMZN": "Amazon.com",
    "META": "Meta Platforms",
    "NFLX": "Netflix",
    "GOOGL": "Alphabet Inc.",
}


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up mock environment variables."""
    monkeypatch.setenv("RH_USERNAME", "test_user")
    monkeypatch.setenv("RH_PASSWORD", "test_password")
    monkeypatch.setenv("RH_2FA", "JBSWY3DPEHPK3PXP")  # Test TOTP secret
    monkeypatch.setenv("DEV", "true")
    monkeypatch.setenv("S3_DEV_BUCKET", "test-bucket")


@pytest.fixture
def mock_robinhood(mock_env_vars: None) -> MagicMock:
    """Mock robin_stocks.robinhood module."""
    with patch("hyperdrive.Broker.rh") as mock_rh:
        # Mock login
        mock_rh.login.return_value = {"access_token": "test_token"}

        # Mock get_stock_historicals
        def mock_historicals(
            symbol: str, interval: str, span: str
        ) -> list[dict[str, Any]]:
            return [h for h in SAMPLE_HISTORICALS if h["symbol"] == symbol]

        mock_rh.get_stock_historicals.side_effect = mock_historicals

        # Mock get_name_by_symbol
        mock_rh.get_name_by_symbol.side_effect = lambda s: NAME_MAPPING.get(
            s, "Unknown"
        )

        # Mock build_holdings
        mock_rh.build_holdings.return_value = SAMPLE_HOLDINGS.copy()

        yield mock_rh


@pytest.fixture
def mock_store() -> dict[str, MagicMock]:
    """Mock Store for file operations."""
    with (
        patch("hyperdrive.Broker.FileReader") as MockReader,
        patch("hyperdrive.Broker.FileWriter") as MockWriter,
    ):
        reader = MagicMock()
        writer = MagicMock()

        # Mock file existence checks
        reader.check_file_exists.return_value = True

        MockReader.return_value = reader
        MockWriter.return_value = writer

        yield {"reader": reader, "writer": writer}


@pytest.fixture
def rh(mock_robinhood: MagicMock, mock_store: dict[str, MagicMock]) -> Any:
    """Create Robinhood instance with mocked dependencies."""
    from hyperdrive.Broker import Robinhood

    return Robinhood()


# ============================================================
# Test Class
# ============================================================


class TestRobinhood:
    """Unit tests for Robinhood class."""

    def test_init(self, rh: Any) -> None:
        """Test Robinhood initialization."""
        assert type(rh).__name__ == "Robinhood"
        assert hasattr(rh, "api")
        assert hasattr(rh, "writer")
        assert hasattr(rh, "reader")
        assert hasattr(rh, "finder")

    def test_flatten(self, rh: Any) -> None:
        """Test list flattening utility."""
        # Empty case
        assert rh.flatten([[]]) == []

        # Single inner list
        assert rh.flatten([[1, 2]]) == [1, 2]

        # Multiple inner lists
        assert rh.flatten([[1, 2], [3, 4]]) == [1, 2, 3, 4]

        # Mixed lengths
        assert rh.flatten([[1], [2, 3], [4, 5, 6]]) == [1, 2, 3, 4, 5, 6]

    def test_get_hists(self, rh: Any, mock_robinhood: MagicMock) -> None:
        """Test getting historical data."""
        symbols = ["AAPL"]
        df = rh.get_hists(symbols, span="year", interval="week")

        # Verify API was called
        mock_robinhood.get_stock_historicals.assert_called()

        # Verify DataFrame structure
        assert isinstance(df, pd.DataFrame)
        assert "symbol" in df.columns
        assert "begins_at" in df.columns

    def test_get_hists_multiple_symbols(
        self, rh: Any, mock_robinhood: MagicMock
    ) -> None:
        """Test getting historical data for multiple symbols."""
        # Add more sample data for other symbols
        mock_robinhood.get_stock_historicals.side_effect = lambda s, i, sp: [
            {
                "symbol": s,
                "begins_at": "2020-01-06T00:00:00Z",
                "open_price": "100.00",
                "close_price": "105.00",
                "high_price": "110.00",
                "low_price": "99.00",
                "volume": 1000000,
            }
        ]

        symbols = ["AAPL", "AMZN", "META"]
        df = rh.get_hists(symbols, span="year", interval="week")

        assert len(df) == 3
        symbols_in_df = set(df["symbol"])
        assert symbols_in_df == {"AAPL", "AMZN", "META"}

    def test_get_names(self, rh: Any, mock_robinhood: MagicMock) -> None:
        """Test getting company names from symbols."""
        assert rh.get_names([]) == []

        names = rh.get_names(["AAPL", "AMZN", "META"])
        assert names == ["Apple Inc.", "Amazon.com", "Meta Platforms"]

    def test_get_names_uses_cache(self, rh: Any, mock_robinhood: MagicMock) -> None:
        """Test that get_names uses holdings cache when available."""
        # First call get_holdings to populate cache
        rh.get_holdings()

        # Now get_names should use cached data
        names = rh.get_names(["AAPL"])
        assert names == ["Apple Inc."]

    def test_get_holdings(self, rh: Any, mock_robinhood: MagicMock) -> None:
        """Test getting holdings."""
        holdings = rh.get_holdings()

        mock_robinhood.build_holdings.assert_called_once()
        assert "AAPL" in holdings
        assert "AMZN" in holdings
        assert holdings["AAPL"]["name"] == "Apple Inc."

    def test_get_holdings_cached(self, rh: Any, mock_robinhood: MagicMock) -> None:
        """Test that holdings are cached after first call."""
        # First call
        rh.get_holdings()
        # Second call
        rh.get_holdings()

        # Should only call API once
        assert mock_robinhood.build_holdings.call_count == 1

    def test_get_symbols(self, rh: Any, mock_robinhood: MagicMock) -> None:
        """Test getting symbols from holdings."""
        symbols = rh.get_symbols()

        assert set(symbols) == {"AAPL", "AMZN", "META", "NFLX"}

    def test_save_symbols(self, rh: Any, mock_store: dict[str, MagicMock]) -> None:
        """Test saving symbols to file."""
        rh.save_symbols()

        # Verify writer.save_csv was called
        mock_store["writer"].save_csv.assert_called_once()

        # Check the call arguments
        call_args = mock_store["writer"].save_csv.call_args
        filename = call_args[0][0]
        df = call_args[0][1]

        assert "symbols.csv" in filename
        assert C.SYMBOL in df.columns
        assert C.NAME in df.columns
        assert "AAPL" in list(df[C.SYMBOL])

    def test_get_hists_with_save(
        self, rh: Any, mock_robinhood: MagicMock, mock_store: dict[str, MagicMock]
    ) -> None:
        """Test getting historical data with save=True (line 47)."""
        symbols = ["AAPL"]
        df = rh.get_hists(symbols, span="year", interval="week", save=True)

        # Verify DataFrame returned
        assert isinstance(df, pd.DataFrame)

        # Verify save was called
        mock_store["writer"].save_csv.assert_called()
