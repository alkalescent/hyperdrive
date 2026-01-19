"""Integration tests for DataSource module.

These tests make real API calls to external services.
Run with: pytest tests/integration/ -v
"""

from hyperdrive import Constants as C


class TestPolygonIntegration:
    """Integration tests for Polygon API."""

    def test_polygon_live_dividends(self):
        """Test real Polygon dividend data."""
        from hyperdrive.DataSource import Polygon

        poly = Polygon()
        df = poly.get_dividends(symbol="AAPL", timeframe="5y")
        assert {C.EX, C.PAY, C.DEC, C.DIV}.issubset(df.columns)
        assert len(df) > 0

    def test_polygon_live_splits(self):
        """Test real Polygon splits data."""
        from hyperdrive.DataSource import Polygon

        poly = Polygon()
        df = poly.get_splits(symbol="AAPL")
        assert {C.EX, C.DEC, C.RATIO}.issubset(df.columns)

    def test_polygon_live_ohlc(self):
        """Test real Polygon OHLC data."""
        from hyperdrive.DataSource import Polygon

        poly = Polygon()
        df = poly.get_ohlc(symbol="AAPL", timeframe="1m")
        assert {C.TIME, C.OPEN, C.HIGH, C.LOW, C.CLOSE, C.VOL}.issubset(df.columns)
        assert len(df) > 10


class TestAlpacaIntegration:
    """Integration tests for Alpaca API."""

    def test_alpaca_live_ohlc(self):
        """Test real Alpaca OHLC data."""
        from hyperdrive.DataSource import AlpacaData

        alpc = AlpacaData(paper=True)
        df = alpc.get_ohlc(symbol="AAPL", timeframe="1m")
        assert {C.TIME, C.OPEN, C.HIGH, C.LOW, C.CLOSE, C.VOL}.issubset(df.columns)
        assert len(df) > 0


class TestLaborStatsIntegration:
    """Integration tests for Bureau of Labor Statistics API."""

    def test_bls_live_unemployment(self):
        """Test real BLS unemployment data."""
        from hyperdrive.DataSource import LaborStats

        bls = LaborStats()
        df = bls.get_unemployment_rate(timeframe="1y")
        assert {C.TIME, C.UN_RATE}.issubset(df.columns)
        assert len(df) > 0


class TestGlassnodeIntegration:
    """Integration tests for Glassnode API."""

    def test_glassnode_live_s2f(self):
        """Test real Glassnode S2F data."""
        from hyperdrive.DataSource import Glassnode

        glass = Glassnode()
        df = glass.get_s2f_ratio(timeframe="1y")
        assert {C.TIME, C.HALVING, C.RATIO}.issubset(df.columns)
        assert len(df) > 0
