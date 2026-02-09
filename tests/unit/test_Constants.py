"""Tests for the Constants module."""

import pytest

from hyperdrive.Constants import PathFinder, get_env_int

finder = PathFinder()


class TestPathFinder:
    """Tests for the PathFinder path utility class."""

    def test_init(self) -> None:
        """Test PathFinder initialization."""
        assert type(PathFinder()).__name__ == "PathFinder"

    def test_get_symbols_path(self) -> None:
        """Test getting symbols CSV path."""
        assert finder.get_symbols_path() == "data/symbols.csv"

    def test_get_dividends_path(self) -> None:
        """Test getting dividends CSV path for various symbols."""
        assert finder.get_dividends_path("aapl") == "data/dividends/polygon/AAPL.csv"
        assert finder.get_dividends_path("AMD") == "data/dividends/polygon/AMD.csv"
        assert (
            finder.get_dividends_path("TSLA", "polygon")
            == "data/dividends/polygon/TSLA.csv"
        )

    def test_get_splits_path(self) -> None:
        """Test getting splits CSV path for various symbols."""
        assert finder.get_splits_path("aapl") == "data/splits/polygon/AAPL.csv"
        assert finder.get_splits_path("AMD") == "data/splits/polygon/AMD.csv"
        assert (
            finder.get_splits_path("TSLA", "polygon") == "data/splits/polygon/TSLA.csv"
        )

    def test_get_ohlc_path(self) -> None:
        """Test getting OHLC CSV path for various symbols."""
        assert finder.get_ohlc_path("aapl") == "data/ohlc/polygon/AAPL.csv"
        assert finder.get_ohlc_path("AMD") == "data/ohlc/polygon/AMD.csv"
        assert finder.get_ohlc_path("TSLA", "polygon") == "data/ohlc/polygon/TSLA.csv"

    def test_get_intraday_path(self) -> None:
        """Test getting intraday CSV path for various symbols and dates."""
        assert (
            finder.get_intraday_path("aapl", "2020-01-01")
            == "data/intraday/polygon/AAPL/2020-01-01.csv"
        )
        assert (
            finder.get_intraday_path("AMD", "2020-01-01")
            == "data/intraday/polygon/AMD/2020-01-01.csv"
        )
        assert (
            finder.get_intraday_path("TSLA", "2020-01-01", "polygon")
            == "data/intraday/polygon/TSLA/2020-01-01.csv"
        )

    def test_get_all_paths(self) -> None:
        """Test getting all file paths in a directory."""
        paths = set(finder.get_all_paths("hyperdrive", False))
        assert "hyperdrive/DataSource.py" in paths
        paths = set(finder.get_all_paths(".", True))
        # Check that test files are found (path format may vary)
        assert any("test_Constants.py" in p for p in paths)

    def test_get_signals_path(self) -> None:
        """Test getting signals CSV path."""
        assert finder.get_signals_path() == "models/latest/signals.csv"

    def test_get_orders_path(self) -> None:
        """Test getting orders CSV path."""
        assert finder.get_orders_path() == "models/latest/orders.csv"

    def test_get_new_orders_path(self) -> None:
        """Test getting new orders CSV path for a provider."""
        assert finder.get_new_orders_path("binance") == "data/orders/binance.csv"
        assert finder.get_new_orders_path("kraken") == "data/orders/kraken.csv"

    def test_get_api_path(self) -> None:
        """Test getting API JSON path for an endpoint."""
        assert finder.get_api_path("trades") == "data/api/trades.json"
        assert finder.get_api_path("deposits") == "data/api/deposits.json"


class TestEnvHelpers:
    """Tests for environment variable helper functions."""

    def test_get_env_int_numeric(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        """Test get_env_int with a numeric value."""
        monkeypatch.setenv("TEST_INT_VAR", "42")
        assert get_env_int("TEST_INT_VAR") == 42

    def test_get_env_int_non_numeric(self, monkeypatch: "pytest.MonkeyPatch") -> None:
        """Test get_env_int with a non-numeric value returns default."""
        monkeypatch.setenv("TEST_INT_VAR", "not_a_number")
        assert get_env_int("TEST_INT_VAR") is None
        assert get_env_int("TEST_INT_VAR", 10) == 10

    def test_get_env_int_missing(self) -> None:
        """Test get_env_int with missing variable returns default."""
        assert get_env_int("NONEXISTENT_VAR_12345") is None
        assert get_env_int("NONEXISTENT_VAR_12345", 99) == 99
