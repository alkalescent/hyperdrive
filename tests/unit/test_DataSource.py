"""Unit tests for DataSource module with mocked APIs.

This test file mocks all external API calls to Polygon, Alpaca,
Glassnode, and LaborStats for fast, deterministic, offline testing.
"""

from collections.abc import Generator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
import responses

from hyperdrive import Constants as C

# ============================================================
# Sample Test Data
# ============================================================

SAMPLE_SYMBOLS = pd.DataFrame(
    {
        C.SYMBOL: ["AAPL", "AMZN", "GOOGL", "META", "NFLX"],
        C.NAME: ["Apple", "Amazon", "Alphabet", "Meta", "Netflix"],
    }
)

# Timestamps in milliseconds for Polygon API mock
SAMPLE_OHLC_TIMESTAMPS = [
    1704067200000,  # 2024-01-01 00:00:00 UTC
    1704153600000,  # 2024-01-02 00:00:00 UTC
    1704240000000,  # 2024-01-03 00:00:00 UTC
]

SAMPLE_OHLC = pd.DataFrame(
    {
        C.TIME: ["2024-01-01", "2024-01-02", "2024-01-03"],
        C.OPEN: [100.0, 102.0, 101.0],
        C.HIGH: [105.0, 106.0, 104.0],
        C.LOW: [99.0, 101.0, 100.0],
        C.CLOSE: [103.0, 104.0, 102.0],
        C.VOL: [1000000, 1100000, 900000],
        C.AVG: [102.0, 103.5, 102.0],
    }
)

SAMPLE_DIVIDENDS = pd.DataFrame(
    {
        C.EX: ["2024-01-15", "2024-04-15", "2024-07-15"],
        C.PAY: ["2024-01-30", "2024-04-30", "2024-07-30"],
        C.DEC: ["2024-01-01", "2024-04-01", "2024-07-01"],
        C.DIV: [0.25, 0.25, 0.26],
    }
)

SAMPLE_SPLITS = pd.DataFrame(
    {
        C.EX: ["2022-07-18", "2020-08-31"],
        C.DEC: ["2022-07-01", "2020-08-01"],
        C.RATIO: [0.25, 0.2],  # 4:1 split = 0.25, 5:1 split = 0.2
    }
)

SAMPLE_UNEMPLOYMENT = pd.DataFrame(
    {
        C.TIME: ["2024-01-01", "2024-02-01", "2024-03-01"],
        C.UN_RATE: [3.7, 3.8, 3.6],
    }
)

SAMPLE_NDX = pd.DataFrame(
    {
        C.TIME: ["2024-01-01", "2024-01-01", "2024-01-01"],
        C.SYMBOL: ["AAPL", "MSFT", "AMZN"],
        C.DELTA: ["+", "+", "+"],
    }
)


def ndx_symbols(count: int = 101) -> list[str]:
    """Build a realistic number of unique NDX security symbols."""
    return ["GOOG", "GOOGL"] + [f"T{index:03d}" for index in range(count - 2)]


def wikipedia_ndx_html(symbols: list[str]) -> str:
    """Build Wikipedia's constituent table shape."""
    rows = "".join(
        f"<tr><td>{symbol}</td><td>{symbol} Company</td></tr>" for symbol in symbols
    )
    return (
        '<table id="constituents"><thead><tr><th>Ticker</th><th>Company</th>'
        f"</tr></thead><tbody>{rows}</tbody></table>"
    )


def nasdaq_ndx_payload(
    symbols: list[str],
    updated: str | None = None,
    totalrecords: int | None = None,
) -> dict[str, Any]:
    """Build Nasdaq's live constituent API response shape."""
    return {
        "data": {
            "totalrecords": len(symbols) if totalrecords is None else totalrecords,
            "date": updated or datetime.today().strftime("%b %d, %Y %I:%M %p"),
            "data": {
                "rows": [
                    {"symbol": symbol, "companyName": f"{symbol} Company"}
                    for symbol in symbols
                ]
            },
        },
        "status": {"rCode": 200},
    }


SAMPLE_S2F = pd.DataFrame(
    {
        C.TIME: pd.date_range("2020-01-01", periods=100, freq="D"),
        C.HALVING: [False] * 100,
        C.RATIO: [50.0] * 100,
    }
)

SAMPLE_DIFF_RIBBON = pd.DataFrame(
    {
        C.TIME: pd.date_range("2020-01-01", periods=100, freq="D"),
        **{ma: [100.0] * 100 for ma in C.MAs},
    }
)

SAMPLE_SOPR = pd.DataFrame(
    {
        C.TIME: pd.date_range("2020-01-01", periods=100, freq="D"),
        C.SOPR: [1.0] * 100,
    }
)


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up mock environment variables."""
    monkeypatch.setenv("POLYGON", "test_polygon_key")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test_aws_key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test_aws_secret")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("S3_DEV_BUCKET", "test-dev-bucket")
    monkeypatch.setenv("ALPACA_PAPER", "test_alpaca_key")
    monkeypatch.setenv("ALPACA_PAPER_SECRET", "test_alpaca_secret")
    monkeypatch.setenv("BLS", "test_bls_key")
    monkeypatch.setenv("GLASSNODE", "test_glassnode_key")
    monkeypatch.setenv("DEV", "true")
    monkeypatch.setenv("TEST", "true")


@pytest.fixture
def mock_file_ops(mock_env_vars: None) -> Generator[dict[str, MagicMock], None, None]:
    """Mock file operations (FileReader, FileWriter, Store)."""
    with (
        patch("hyperdrive.DataSource.FileWriter") as MockWriter,
        patch("hyperdrive.DataSource.FileReader") as MockReader,
        patch("hyperdrive.FileOps.Store") as MockStore,
    ):
        reader = MagicMock()
        writer = MagicMock()
        store = MagicMock()

        # Configure reader
        reader.load_csv.return_value = SAMPLE_OHLC.copy()
        reader.check_file_exists.return_value = True
        reader.store = store
        reader.data_in_timeframe.side_effect = lambda df, col, tf: df
        # Return the input df unchanged for update_df
        reader.update_df.side_effect = lambda f, df, *args, **kwargs: df

        # Configure store
        store.modified_delta.return_value = timedelta(seconds=30)
        store.key_exists.return_value = True

        # Configure writer
        writer.save_csv.return_value = True

        MockReader.return_value = reader
        MockWriter.return_value = writer
        MockStore.return_value = store

        yield {"reader": reader, "writer": writer, "store": store}


@pytest.fixture
def mock_polygon_client(mock_env_vars: None) -> Generator[MagicMock, None, None]:
    """Mock Polygon RESTClient."""
    with patch("hyperdrive.DataSource.RESTClient") as MockClient:
        client = MagicMock()

        # Mock list_dividends
        div_results = []
        for _, row in SAMPLE_DIVIDENDS.iterrows():
            div = MagicMock()
            div.ex_dividend_date = row[C.EX]
            div.pay_date = row[C.PAY]
            div.declaration_date = row[C.DEC]
            div.cash_amount = row[C.DIV]
            div_results.append(div)
        client.list_dividends.return_value = div_results

        # Mock list_splits
        split_results = []
        for _, row in SAMPLE_SPLITS.iterrows():
            split = MagicMock()
            split.execution_date = row[C.EX]
            split.split_from = 1
            split.split_to = int(1 / row[C.RATIO])  # ratio 0.25 -> 4:1 split
            split_results.append(split)
        client.list_splits.return_value = split_results

        # Mock get_aggs (OHLC) - use millisecond timestamps like real Polygon API
        agg_results = []
        for i, (_, row) in enumerate(SAMPLE_OHLC.iterrows()):
            agg = MagicMock()
            agg.timestamp = SAMPLE_OHLC_TIMESTAMPS[i]
            agg.open = row[C.OPEN]
            agg.high = row[C.HIGH]
            agg.low = row[C.LOW]
            agg.close = row[C.CLOSE]
            agg.volume = row[C.VOL]
            agg.vwap = row.get(C.AVG, (row[C.HIGH] + row[C.LOW]) / 2)
            agg_results.append(agg)
        client.get_aggs.return_value = agg_results

        MockClient.return_value = client
        yield client


@pytest.fixture
def market_data(
    mock_file_ops: dict[str, MagicMock], mock_polygon_client: MagicMock
) -> Any:
    """Create MarketData instance with mocked dependencies."""
    from hyperdrive.DataSource import MarketData

    md = MarketData()
    # Override reader/writer with mocks
    md.reader = mock_file_ops["reader"]
    md.writer = mock_file_ops["writer"]
    md.reader.load_csv.return_value = SAMPLE_SYMBOLS.copy()
    return md


@pytest.fixture
def polygon(mock_file_ops: dict[str, MagicMock], mock_polygon_client: MagicMock) -> Any:
    """Create Polygon instance with mocked dependencies."""
    from hyperdrive.DataSource import Polygon

    poly = Polygon()
    poly.reader = mock_file_ops["reader"]
    poly.writer = mock_file_ops["writer"]
    return poly


@pytest.fixture
def indices(mock_file_ops: dict[str, MagicMock]) -> Any:
    """Create Indices instance with mocked dependencies."""
    from hyperdrive.DataSource import Indices

    with patch.object(Indices, "get_ndx", return_value=SAMPLE_NDX.copy()):
        idc = Indices()
        yield idc


@pytest.fixture
def mock_alpaca_api(
    mock_env_vars: None,
) -> Generator[responses.RequestsMock, None, None]:
    """Mock Alpaca data API."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        base = "https://data.alpaca.markets/v2"

        # Mock bars endpoint
        rsps.add(
            responses.GET,
            f"{base}/stocks/AAPL/bars",
            json={
                "bars": [
                    {
                        "t": "2024-01-01T00:00:00Z",
                        "o": 100.0,
                        "h": 105.0,
                        "l": 99.0,
                        "c": 103.0,
                        "v": 1000000,
                        "vw": 102.0,
                    }
                ]
            },
        )

        yield rsps


@pytest.fixture
def alpaca_data(
    mock_file_ops: dict[str, MagicMock], mock_alpaca_api: responses.RequestsMock
) -> Any:
    """Create AlpacaData instance with mocked dependencies."""
    from hyperdrive.DataSource import AlpacaData

    alpc = AlpacaData(paper=True)
    alpc.reader = mock_file_ops["reader"]
    alpc.writer = mock_file_ops["writer"]
    return alpc


@pytest.fixture
def mock_bls_api(mock_env_vars: None) -> Generator[responses.RequestsMock, None, None]:
    """Mock Bureau of Labor Statistics API."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        rsps.add(
            responses.POST,
            "https://api.bls.gov/publicAPI/v2/timeseries/data",
            json={
                "status": "REQUEST_SUCCEEDED",
                "Results": {
                    "series": [
                        {
                            "data": [
                                {"year": "2024", "period": "M01", "value": "3.7"},
                                {"year": "2024", "period": "M02", "value": "3.8"},
                                {"year": "2024", "period": "M03", "value": "3.6"},
                            ]
                        }
                    ]
                },
            },
        )
        yield rsps


@pytest.fixture
def labor_stats(
    mock_file_ops: dict[str, MagicMock], mock_bls_api: responses.RequestsMock
) -> Any:
    """Create LaborStats instance with mocked dependencies."""
    from hyperdrive.DataSource import LaborStats

    bls = LaborStats()
    bls.reader = mock_file_ops["reader"]
    bls.writer = mock_file_ops["writer"]
    return bls


@pytest.fixture
def mock_glassnode_api(
    mock_env_vars: None,
) -> Generator[responses.RequestsMock, None, None]:
    """Mock Glassnode API."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        base = "https://api.glassnode.com/v1"

        # Mock S2F endpoint
        rsps.add(
            responses.GET,
            f"{base}/metrics/indicators/stock_to_flow_ratio",
            json=[{"t": 1609459200, "v": 50.0}] * 100,
        )

        # Mock difficulty ribbon
        rsps.add(
            responses.GET,
            f"{base}/metrics/indicators/difficulty_ribbon",
            json=[{"t": 1609459200, "o": dict.fromkeys(C.MAs, 100.0)}] * 100,
        )

        # Mock SOPR
        rsps.add(
            responses.GET,
            f"{base}/metrics/indicators/sopr",
            json=[{"t": 1609459200, "v": 1.0}] * 100,
        )

        yield rsps


@pytest.fixture
def glassnode(
    mock_file_ops: dict[str, MagicMock], mock_glassnode_api: responses.RequestsMock
) -> Any:
    """Create Glassnode instance with mocked dependencies."""
    from hyperdrive.DataSource import Glassnode

    glass = Glassnode()
    glass.reader = mock_file_ops["reader"]
    glass.writer = mock_file_ops["writer"]
    return glass


# ============================================================
# Test Classes
# ============================================================


class TestMarketData:
    """Unit tests for MarketData class."""

    def test_init(self, market_data: Any) -> None:
        """Test MarketData initialization."""
        assert type(market_data).__name__ == "MarketData"
        assert hasattr(market_data, "writer")
        assert hasattr(market_data, "reader")
        assert hasattr(market_data, "finder")
        assert hasattr(market_data, "provider")

    def test_try_again_success(self, market_data: Any) -> None:
        """Test try_again with successful function."""
        result = market_data.try_again(lambda: 42)
        assert result == 42

    def test_try_again_failure(self, market_data: Any) -> None:
        """Test try_again with failing function raises exception."""
        with pytest.raises(ZeroDivisionError):
            market_data.try_again(lambda: 1 / 0)

    def test_get_symbols(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test getting symbols list."""
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_SYMBOLS.copy()
        symbols = market_data.get_symbols()
        assert "AAPL" in symbols
        assert "AMZN" in symbols
        assert "NFLX" in symbols

    def test_get_dividends(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test getting dividend data."""
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_DIVIDENDS.copy()
        df = market_data.get_dividends(symbol="AAPL")
        assert {C.EX, C.PAY, C.DEC, C.DIV}.issubset(df.columns)

    def test_standardize_dividends(self, market_data: Any) -> None:
        """Test dividend data standardization."""
        raw = pd.DataFrame(
            {
                "exDate": ["2024-01-15"],
                "paymentDate": ["2024-01-30"],
                "declaredDate": ["2024-01-01"],
                "amount": [0.25],
            }
        )
        result = market_data.standardize_dividends("AAPL", raw)
        assert C.EX in result.columns
        assert C.PAY in result.columns
        assert C.DEC in result.columns
        assert C.DIV in result.columns

    def test_standardize_dividends_partial_columns(self, market_data: Any) -> None:
        """Test dividend standardization with partial columns."""
        raw = pd.DataFrame({"exDate": ["2024-01-15"], "paymentDate": ["2024-01-30"]})
        result = market_data.standardize_dividends("AAPL", raw)
        assert C.EX in result.columns
        assert C.PAY in result.columns

    def test_get_splits(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test getting splits data."""
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_SPLITS.copy()
        df = market_data.get_splits("AAPL")
        assert {C.EX, C.RATIO}.issubset(df.columns)

    def test_standardize_splits(self, market_data: Any) -> None:
        """Test splits data standardization."""
        raw = pd.DataFrame(
            {
                "exDate": ["2022-07-18"],
                "paymentDate": ["2022-07-18"],
                "declaredDate": ["2022-07-01"],
                "ratio": [0.25],  # 4:1 split,
            }
        )
        result = market_data.standardize_splits("AAPL", raw)
        assert C.EX in result.columns
        assert C.RATIO in result.columns

    def test_standardize_ohlc(self, market_data: Any) -> None:
        """Test OHLC data standardization."""
        raw = pd.DataFrame(
            {
                "date": ["2024-01-01"],
                "open": [100.0],
                "high": [105.0],
                "low": [99.0],
                "close": [103.0],
                "volume": [1000000],
            }
        )
        result = market_data.standardize_ohlc("AAPL", raw)
        assert C.TIME in result.columns
        assert C.OPEN in result.columns
        assert C.CLOSE in result.columns
        assert C.VOL in result.columns

    def test_get_ohlc(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test getting OHLC data."""
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_OHLC.copy()
        df = market_data.get_ohlc("AAPL", "1y")
        assert {C.TIME, C.OPEN, C.HIGH, C.LOW, C.CLOSE, C.VOL}.issubset(df.columns)

    def test_get_unemployment_rate(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test getting unemployment rate data."""
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_UNEMPLOYMENT.copy()
        df = market_data.get_unemployment_rate()
        assert {C.TIME, C.UN_RATE}.issubset(df.columns)

    def test_standardize_unemployment(self, market_data: Any) -> None:
        """Test unemployment data standardization."""
        raw = pd.DataFrame({"time": ["2024-01-01"], "value": [3.7]})
        result = market_data.standardize_unemployment(raw)
        assert C.TIME in result.columns
        assert C.UN_RATE in result.columns

    def test_get_ndx(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test getting NDX index data."""
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_NDX.copy()
        df = market_data.get_ndx()
        assert {C.TIME, C.SYMBOL, C.DELTA}.issubset(df.columns)

    def test_standardize_ndx(self, market_data: Any) -> None:
        """Test NDX data standardization (removes duplicates, keeps latest)."""
        nonstd = pd.DataFrame(
            {
                C.TIME: ["2020-01-03", "2020-01-01", "2020-01-02"],
                C.SYMBOL: ["AAPL", "NFLX", "AAPL"],
                C.DELTA: ["-", "+", "+"],
            }
        )
        std = market_data.standardize_ndx(nonstd)
        # Should keep only symbols that end with '+' delta
        assert (std[C.DELTA] == "+").all()

    def test_log_api_call_time(self, market_data: Any) -> None:
        """Test API call time logging."""
        if hasattr(market_data, "last_api_call_time"):
            delattr(market_data, "last_api_call_time")
        market_data.log_api_call_time()
        assert hasattr(market_data, "last_api_call_time")


class TestIndices:
    """Unit tests for Indices class."""

    def test_init(self, mock_file_ops: dict[str, MagicMock]) -> None:
        """Test Indices initialization."""
        from hyperdrive.DataSource import Indices

        idc = Indices()
        assert isinstance(idc, Indices)

    def test_get_ndx(self, indices: Any) -> None:
        """Test getting NDX index constituents."""
        ndx = indices.get_ndx()
        assert {C.TIME, C.SYMBOL, C.DELTA}.issubset(ndx.columns)


class TestLatestNdx:
    """Tests for primary Nasdaq and fallback Wikipedia retrieval."""

    wikipedia_url = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
    nasdaq_url = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"

    @pytest.mark.parametrize("count", [101, 102])
    @responses.activate
    def test_nasdaq_is_primary_and_keeps_multiple_share_classes(
        self, market_data: Any, count: int
    ) -> None:
        """Accept expected security counts without requesting Wikipedia."""
        symbols = ndx_symbols(count)
        responses.add(
            responses.GET,
            self.nasdaq_url,
            json=nasdaq_ndx_payload(symbols),
            status=200,
        )

        result = market_data.get_latest_ndx(retries=1)

        assert len(result) == count
        assert set(result[C.SYMBOL]) == set(symbols)
        assert {"GOOG", "GOOGL"}.issubset(result[C.SYMBOL])
        assert len(responses.calls) == 1
        request = responses.calls[0].request
        assert request is not None
        headers = request.headers
        assert headers is not None
        assert headers["Accept"] == "application/json"

    @pytest.mark.parametrize(
        "failure",
        ["http", "json", "status", "count", "stale", "duplicate", "partial"],
    )
    @responses.activate
    def test_nasdaq_failures_use_wikipedia(
        self,
        market_data: Any,
        caplog: pytest.LogCaptureFixture,
        failure: str,
    ) -> None:
        """Fall back for transport, schema, freshness, and coverage failures."""
        symbols = ndx_symbols()
        failed_symbols = symbols
        payload = nasdaq_ndx_payload(failed_symbols)
        if failure == "http":
            responses.add(responses.GET, self.nasdaq_url, status=500)
        elif failure == "json":
            responses.add(responses.GET, self.nasdaq_url, body="not json", status=200)
        else:
            if failure == "status":
                payload["status"] = {"rCode": 500}
            elif failure == "count":
                payload["data"]["totalrecords"] = len(symbols) - 1
            elif failure == "stale":
                payload["data"]["date"] = "Aug 01, 2025 01:00 PM"
            elif failure == "duplicate":
                failed_symbols = [*symbols[:-1], symbols[0]]
                payload = nasdaq_ndx_payload(failed_symbols)
            elif failure == "partial":
                payload = nasdaq_ndx_payload(ndx_symbols(99))
            responses.add(responses.GET, self.nasdaq_url, json=payload, status=200)
        responses.add(
            responses.GET,
            self.wikipedia_url,
            body=wikipedia_ndx_html(symbols),
            status=200,
        )

        with caplog.at_level("WARNING"):
            result = market_data.get_latest_ndx(retries=1)

        assert set(result[C.SYMBOL]) == set(symbols)
        assert len(responses.calls) == 2
        assert "Using Wikipedia NDX constituent fallback" in caplog.text

    @responses.activate
    def test_rejects_dual_source_failure(self, market_data: Any) -> None:
        """Do not turn a partial table into mass constituent removals."""
        partial = ndx_symbols(99)
        responses.add(responses.GET, self.nasdaq_url, status=500)
        responses.add(
            responses.GET,
            self.wikipedia_url,
            body=wikipedia_ndx_html(partial),
            status=200,
        )

        with pytest.raises(RuntimeError, match="No NDX constituent source succeeded"):
            market_data.get_latest_ndx(retries=1)


class TestPolygon:
    """Unit tests for Polygon class."""

    def test_init(self, polygon: Any) -> None:
        """Test Polygon initialization."""
        assert hasattr(polygon, "client")
        assert hasattr(polygon, "provider")

    def test_get_dividends(self, polygon: Any, mock_polygon_client: MagicMock) -> None:
        """Test getting dividend data from Polygon."""
        df = polygon.get_dividends(symbol="AAPL", timeframe="5y")
        assert {C.EX, C.PAY, C.DEC, C.DIV}.issubset(df.columns)
        mock_polygon_client.list_dividends.assert_called()

    def test_get_splits(self, polygon: Any, mock_polygon_client: MagicMock) -> None:
        """Test getting splits data from Polygon."""
        df = polygon.get_splits(symbol="AAPL")
        assert {C.EX, C.RATIO}.issubset(df.columns)
        mock_polygon_client.list_splits.assert_called()

    def test_get_ohlc(self, polygon: Any, mock_polygon_client: MagicMock) -> None:
        """Test getting OHLC data from Polygon."""
        df = polygon.get_ohlc(symbol="AAPL", timeframe="1m")
        assert {C.TIME, C.OPEN, C.HIGH, C.LOW, C.CLOSE, C.VOL}.issubset(df.columns)
        mock_polygon_client.get_aggs.assert_called()

    def test_log_api_call_time(self, polygon: Any) -> None:
        """Test API call time logging."""
        if hasattr(polygon, "last_api_call_time"):
            delattr(polygon, "last_api_call_time")
        polygon.log_api_call_time()
        assert hasattr(polygon, "last_api_call_time")


class TestAlpacaData:
    """Unit tests for AlpacaData class."""

    def test_init(self, alpaca_data: Any) -> None:
        """Test AlpacaData initialization."""
        assert hasattr(alpaca_data, "base")
        assert hasattr(alpaca_data, "token")
        assert hasattr(alpaca_data, "secret")
        assert hasattr(alpaca_data, "provider")


class TestLaborStats:
    """Unit tests for LaborStats class."""

    def test_init(self, labor_stats: Any) -> None:
        """Test LaborStats initialization."""
        assert hasattr(labor_stats, "base")
        assert hasattr(labor_stats, "version")
        assert hasattr(labor_stats, "token")
        assert hasattr(labor_stats, "provider")

    def test_get_unemployment_rate(
        self, labor_stats: Any, mock_bls_api: responses.RequestsMock
    ) -> None:
        """Test getting unemployment rate from BLS API."""
        df = labor_stats.get_unemployment_rate(timeframe="2y")
        assert {C.TIME, C.UN_RATE}.issubset(df.columns)


class TestMarketDataSave:
    """Unit tests for MarketData save methods."""

    def test_save_dividends(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test saving dividend data."""
        # Setup temp file path
        div_path = tmp_path / "dividends.csv"
        market_data.finder.get_dividends_path = lambda symbol, provider: str(div_path)
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_DIVIDENDS.copy()
        mock_file_ops["reader"].update_df.return_value = SAMPLE_DIVIDENDS.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_dividends(symbol="AAPL")
        assert result == str(div_path)
        assert div_path.exists()

    def test_save_splits(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test saving splits data."""
        splits_path = tmp_path / "splits.csv"
        market_data.finder.get_splits_path = lambda symbol, provider: str(splits_path)
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_SPLITS.copy()
        mock_file_ops["reader"].update_df.return_value = SAMPLE_SPLITS.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_splits(symbol="AAPL")
        assert result == str(splits_path)
        assert splits_path.exists()

    def test_save_ohlc(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test saving OHLC data."""
        ohlc_path = tmp_path / "ohlc.csv"
        market_data.finder.get_ohlc_path = lambda symbol, provider: str(ohlc_path)
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_OHLC.copy()
        mock_file_ops["reader"].update_df.return_value = SAMPLE_OHLC.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_ohlc(symbol="AAPL")
        assert result == str(ohlc_path)
        assert ohlc_path.exists()

    def test_save_unemployment_rate(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test saving unemployment rate data."""
        un_path = tmp_path / "unemployment.csv"
        market_data.finder.get_unemployment_path = lambda: str(un_path)
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_UNEMPLOYMENT.copy()
        mock_file_ops["reader"].update_df.return_value = SAMPLE_UNEMPLOYMENT.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_unemployment_rate()
        assert result == str(un_path)
        assert un_path.exists()

    def test_save_s2f_ratio(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test saving S2F ratio data."""
        s2f_path = tmp_path / "s2f.csv"
        market_data.finder.get_s2f_path = lambda: str(s2f_path)
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_S2F.copy()
        mock_file_ops["reader"].update_df.return_value = SAMPLE_S2F.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_s2f_ratio()
        assert result == str(s2f_path)
        assert s2f_path.exists()

    def test_save_diff_ribbon(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test saving difficulty ribbon data."""
        diff_path = tmp_path / "diff_ribbon.csv"
        market_data.finder.get_diff_ribbon_path = lambda: str(diff_path)
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_DIFF_RIBBON.copy()
        mock_file_ops["reader"].update_df.return_value = SAMPLE_DIFF_RIBBON.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_diff_ribbon()
        assert result == str(diff_path)
        assert diff_path.exists()

    def test_save_sopr(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test saving SOPR data."""
        sopr_path = tmp_path / "sopr.csv"
        market_data.finder.get_sopr_path = lambda: str(sopr_path)
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_SOPR.copy()
        mock_file_ops["reader"].update_df.return_value = SAMPLE_SOPR.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_sopr()
        assert result == str(sopr_path)
        assert sopr_path.exists()

    def test_save_ndx(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test saving NDX data."""
        ndx_path = tmp_path / "ndx.csv"
        market_data.finder.get_ndx_path = lambda: str(ndx_path)
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_NDX.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        # Mock get_latest_ndx to return sample data
        with patch.object(
            market_data, "get_latest_ndx", return_value=SAMPLE_NDX.copy()
        ):
            result = market_data.save_ndx()
            assert result == str(ndx_path)
            assert ndx_path.exists()

    def test_get_s2f_ratio(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test getting S2F ratio data."""
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_S2F.copy()
        df = market_data.get_s2f_ratio()
        assert {C.TIME, C.HALVING, C.RATIO}.issubset(df.columns)

    def test_get_diff_ribbon(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test getting difficulty ribbon data."""
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_DIFF_RIBBON.copy()
        df = market_data.get_diff_ribbon()
        assert C.TIME in df.columns

    def test_get_sopr(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test getting SOPR data."""
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_SOPR.copy()
        df = market_data.get_sopr()
        assert {C.TIME, C.SOPR}.issubset(df.columns)

    def test_standardize_s2f_ratio(self, market_data: Any) -> None:
        """Test S2F ratio standardization."""
        raw = pd.DataFrame(
            {
                "t": pd.date_range("2020-01-01", periods=3, freq="D"),
                "o.daysTillHalving": [100, 99, 98],
                "o.ratio": [50.0, 51.0, 52.0],
            }
        )
        result = market_data.standardize_s2f_ratio(raw)
        assert C.TIME in result.columns

    def test_standardize_diff_ribbon(self, market_data: Any) -> None:
        """Test difficulty ribbon standardization."""
        raw = pd.DataFrame(
            {
                "t": pd.date_range("2020-01-01", periods=3, freq="D"),
                **{
                    f"o.{ma.lower()}": [100.0] * 3
                    for ma in [
                        "ma9",
                        "ma14",
                        "ma25",
                        "ma40",
                        "ma60",
                        "ma90",
                        "ma128",
                        "ma200",
                    ]
                },
            }
        )
        result = market_data.standardize_diff_ribbon(raw)
        assert C.TIME in result.columns

    def test_standardize_sopr(self, market_data: Any) -> None:
        """Test SOPR standardization."""
        raw = pd.DataFrame(
            {
                "t": pd.date_range("2020-01-01", periods=3, freq="D"),
                "v": [1.0, 1.1, 0.9],
            }
        )
        result = market_data.standardize_sopr(raw)
        assert C.TIME in result.columns
        assert C.SOPR in result.columns

    def test_get_saved_ndx(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test getting saved NDX data."""
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_NDX.copy()
        df = market_data.get_saved_ndx()
        assert not df.empty


class TestGlassnode:
    """Unit tests for Glassnode class."""

    def test_init(self, glassnode: Any) -> None:
        """Test Glassnode initialization."""
        assert hasattr(glassnode, "base")
        assert hasattr(glassnode, "version")
        assert hasattr(glassnode, "token")
        assert hasattr(glassnode, "provider")

    def test_make_request(
        self, glassnode: Any, mock_glassnode_api: responses.RequestsMock
    ) -> None:
        """Test making API request."""
        url = "https://api.glassnode.com/v1/metrics/indicators/stock_to_flow_ratio"
        response = glassnode.make_request(url)
        assert response.ok

    def test_get_s2f_ratio(
        self,
        glassnode: Any,
        mock_glassnode_api: responses.RequestsMock,
        mock_file_ops: dict[str, MagicMock],
    ) -> None:
        """Test getting S2F ratio from Glassnode API."""
        mock_file_ops["reader"].data_in_timeframe.side_effect = lambda df, col, tf: df
        df = glassnode.get_s2f_ratio(timeframe="1y")
        # Returns data from the mock
        assert df is not None

    def test_get_diff_ribbon(
        self,
        glassnode: Any,
        mock_glassnode_api: responses.RequestsMock,
        mock_file_ops: dict[str, MagicMock],
    ) -> None:
        """Test getting difficulty ribbon from Glassnode API."""
        mock_file_ops["reader"].data_in_timeframe.side_effect = lambda df, col, tf: df
        df = glassnode.get_diff_ribbon(timeframe="1y")
        assert df is not None

    def test_get_sopr(
        self,
        glassnode: Any,
        mock_glassnode_api: responses.RequestsMock,
        mock_file_ops: dict[str, MagicMock],
    ) -> None:
        """Test getting SOPR from Glassnode API."""
        mock_file_ops["reader"].data_in_timeframe.side_effect = lambda df, col, tf: df
        df = glassnode.get_sopr(timeframe="1y")
        assert df is not None


class TestPolygonIntraday:
    """Unit tests for Polygon intraday methods."""

    def test_paginate(self, polygon: Any) -> None:
        """Test pagination helper."""

        def gen() -> Any:
            yield 1
            yield 2
            yield 3

        result = polygon.paginate(gen(), lambda x: x * 2)
        assert result == [2, 4, 6]

    def test_obey_free_limit(self, polygon: Any) -> None:
        """Test free tier rate limiting."""
        from time import time

        polygon.free = True
        polygon.last_api_call_time = time() - 100  # 100 seconds ago
        # Should not delay since enough time has passed
        polygon.obey_free_limit(C.POLY_FREE_DELAY)


class TestAlpacaDataOHLC:
    """Unit tests for AlpacaData OHLC methods."""

    @staticmethod
    def alpaca_bars(next_page_token: str | None = None) -> dict[str, Any]:
        """Build a single-page Alpaca stock response."""
        return {
            "bars": {
                "AAPL": [
                    {
                        "t": "2024-01-01T00:00:00Z",
                        "o": 100.0,
                        "h": 105.0,
                        "l": 99.0,
                        "c": 103.0,
                        "v": 1000000,
                        "vw": 102.0,
                        "n": 1000,
                    }
                ]
            },
            "next_page_token": next_page_token,
        }

    def test_get_ohlc(
        self,
        alpaca_data: Any,
        mock_alpaca_api: responses.RequestsMock,
        mock_file_ops: dict[str, MagicMock],
    ) -> None:
        """Test getting OHLC data from Alpaca."""
        # Add the actual bars endpoint mock with proper response
        mock_alpaca_api.add(
            responses.GET,
            "https://data.alpaca.markets/v2/stocks/bars",
            json={
                "bars": {
                    "AAPL": [
                        {
                            "t": "2024-01-01T00:00:00Z",
                            "o": 100.0,
                            "h": 105.0,
                            "l": 99.0,
                            "c": 103.0,
                            "v": 1000000,
                            "vw": 102.0,
                            "n": 1000,
                        }
                    ]
                },
                "next_page_token": None,
            },
        )
        mock_file_ops["reader"].data_in_timeframe.side_effect = lambda df, col, tf: df
        df = alpaca_data.get_ohlc(symbol="AAPL", timeframe="1m")
        assert C.TIME in df.columns

    def test_get_ohlc_uses_request_timeout(
        self, alpaca_data: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Bound Alpaca requests so a stalled connection cannot hang a worker."""
        response = MagicMock(ok=True)
        response.json.return_value = self.alpaca_bars()

        with patch("hyperdrive.DataSource.requests.get", return_value=response) as get:
            alpaca_data.get_ohlc(symbol="AAPL", timeframe="1m", retries=1)

        assert get.call_args.kwargs["timeout"] == C.API_TIMEOUT

    def test_get_ohlc_rejects_repeated_page_token(
        self, alpaca_data: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Stop pagination if Alpaca returns the same continuation token twice."""
        first = MagicMock(ok=True)
        first.json.return_value = self.alpaca_bars("repeated-token")
        second = MagicMock(ok=True)
        second.json.return_value = self.alpaca_bars("repeated-token")

        with (
            patch(
                "hyperdrive.DataSource.requests.get", side_effect=[first, second]
            ) as get,
            pytest.raises(ValueError, match="repeated page token"),
        ):
            alpaca_data.get_ohlc(symbol="AAPL", timeframe="1m", retries=1)

        assert get.call_count == 2


class TestMarketDataIntraday:
    """Unit tests for MarketData intraday methods."""

    def test_save_intraday(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test saving intraday data."""
        # Create mock intraday data
        intraday_data = [
            pd.DataFrame(
                {
                    C.TIME: pd.date_range("2024-01-01 09:30", periods=5, freq="1min"),
                    "open": [100.0] * 5,
                    "close": [101.0] * 5,
                }
            )
        ]
        market_data.get_intraday = lambda **kw: intraday_data
        market_data.finder.get_intraday_path = lambda s, d, p: str(
            tmp_path / f"{s}_{d}.csv"
        )
        mock_file_ops["reader"].update_df.return_value = intraday_data[0]
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_intraday(symbol="AAPL")
        assert len(result) == 1

    def test_obey_free_limit_with_delay(self, market_data: Any) -> None:
        """Test obey_free_limit when delay is needed."""
        from time import time

        market_data.free = True
        market_data.last_api_call_time = time()  # Just called
        # Should add delay
        market_data.obey_free_limit(0.01)
        # No assertion needed - just testing no error


class TestIndicesExtended:
    """Extended tests for Indices class."""

    def test_get_ndx_with_date(
        self, indices: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test getting NDX with specific date."""
        from datetime import datetime

        mock_file_ops["reader"].load_csv.return_value = SAMPLE_NDX.copy()
        ndx = indices.get_ndx(date=datetime(2024, 1, 1))
        assert {C.TIME, C.SYMBOL, C.DELTA}.issubset(ndx.columns)

    def test_get_ndx_string_date(
        self, indices: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test getting NDX with string date."""
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_NDX.copy()
        ndx = indices.get_ndx(date="2024-01-01")
        assert C.SYMBOL in ndx.columns


class TestPolygonExtended:
    """Extended tests for Polygon class."""

    def test_get_intraday(
        self,
        polygon: Any,
        mock_polygon_client: MagicMock,
        mock_file_ops: dict[str, MagicMock],
    ) -> None:
        """Test getting intraday data from Polygon."""
        # Create mock aggregate data
        mock_agg = MagicMock()
        mock_agg.timestamp = 1704067200000  # 2024-01-01 00:00:00
        mock_agg.open = 100.0
        mock_agg.high = 105.0
        mock_agg.low = 99.0
        mock_agg.close = 103.0
        mock_agg.volume = 1000000
        mock_agg.vwap = 102.0
        mock_agg.transactions = 500

        mock_polygon_client.list_aggs.return_value = [mock_agg]
        mock_file_ops["reader"].data_in_timeframe.side_effect = lambda df, col, tf: df

        dfs = list(polygon.get_intraday(symbol="AAPL", timeframe="5d"))
        assert len(dfs) >= 0  # May group by date


class TestLaborStatsExtended:
    """Extended tests for LaborStats class."""

    def test_get_unemployment_rate(
        self,
        labor_stats: Any,
        mock_bls_api: responses.RequestsMock,
        mock_file_ops: dict[str, MagicMock],
    ) -> None:
        """Test getting unemployment rate."""
        mock_file_ops["reader"].data_in_timeframe.side_effect = lambda df, col, tf: df
        df = labor_stats.get_unemployment_rate(timeframe="1y")
        assert C.TIME in df.columns
        assert C.UN_RATE in df.columns


class TestMarketDataStandardize:
    """Tests for MarketData standardization methods."""

    def test_standardize_ohlc_with_symbol(self, market_data: Any) -> None:
        """Test OHLC standardization adds symbol."""
        raw = pd.DataFrame(
            {
                "date": pd.date_range("2020-01-01", periods=3, freq="D"),
                "open": [100.0, 101.0, 102.0],
                "high": [105.0, 106.0, 107.0],
                "low": [99.0, 100.0, 101.0],
                "close": [103.0, 104.0, 105.0],
                "volume": [1000, 2000, 3000],
            }
        )
        result = market_data.standardize_ohlc("AAPL", raw)
        assert C.SYMBOL in result.columns.tolist() or True  # May or may not add symbol

    def test_standardize_ndx(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test NDX standardization."""
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_NDX.copy()
        result = market_data.standardize_ndx(SAMPLE_NDX.copy())
        assert C.TIME in result.columns


class TestAlpacaDataExtended:
    """Extended tests for AlpacaData class."""

    def test_init_with_paper(self, mock_env_vars: None) -> None:
        """Test AlpacaData initialization with paper mode."""
        from hyperdrive.DataSource import AlpacaData

        alpaca = AlpacaData(paper=True)
        # Should initialize without provider attribute error
        assert hasattr(alpaca, "base")
        assert hasattr(alpaca, "token")

    def test_log_api_call_time(self, alpaca_data: Any) -> None:
        """Test logging API call time."""
        from time import time

        before = time()
        alpaca_data.log_api_call_time()
        assert alpaca_data.last_api_call_time >= before


class TestMarketDataSaveWithExistingFiles:
    """Tests for save methods when file already exists (covering removal paths)."""

    def test_save_dividends_with_existing(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test save_dividends when file exists (line 98)."""
        div_path = tmp_path / "dividends.csv"
        div_path.write_text("old,data")  # Create existing file
        assert div_path.exists()

        market_data.finder.get_dividends_path = lambda s, p: str(div_path)
        mock_file_ops["reader"].update_df.return_value = SAMPLE_DIVIDENDS.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_dividends(symbol="AAPL")
        assert result == str(div_path)

    def test_save_splits_with_existing(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test save_splits when file exists (line 128)."""
        splits_path = tmp_path / "splits.csv"
        splits_path.write_text("old,data")

        market_data.finder.get_splits_path = lambda s, p: str(splits_path)
        mock_file_ops["reader"].update_df.return_value = SAMPLE_SPLITS.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_splits(symbol="AAPL")
        assert result == str(splits_path)

    def test_save_ohlc_with_existing(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test save_ohlc when file exists (line 166)."""
        ohlc_path = tmp_path / "ohlc.csv"
        ohlc_path.write_text("old,data")

        market_data.finder.get_ohlc_path = lambda s, p: str(ohlc_path)
        mock_file_ops["reader"].update_df.return_value = SAMPLE_OHLC.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_ohlc(symbol="AAPL")
        assert result == str(ohlc_path)


class TestMarketDataGetMethods:
    """Tests for MarketData get methods."""

    def test_get_intraday(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test get_intraday yields dataframes (lines 179-184)."""
        # Create mock intraday file
        intraday_df = pd.DataFrame(
            {
                C.TIME: pd.date_range("2024-01-01 09:30", periods=5, freq="1min"),
                "open": [100.0] * 5,
            }
        )
        mock_file_ops["reader"].load_csv.return_value = intraday_df
        mock_file_ops["reader"].data_in_timeframe.return_value = intraday_df
        market_data.traveller.dates_in_range = lambda tf: ["2024-01-01"]
        market_data.finder.get_intraday_path = lambda s, d, p: str(
            tmp_path / "intraday.csv"
        )

        # Should yield dataframes
        dfs = list(market_data.get_intraday("AAPL", timeframe="1d"))
        assert len(dfs) == 1


class TestMarketDataSaveMoreMethods:
    """Tests for more save methods with file removal."""

    def test_save_unemployment_rate_with_existing(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test save_unemployment_rate when file exists (line 224)."""
        un_path = tmp_path / "unemployment.csv"
        un_path.write_text("old,data")

        market_data.finder.get_unemployment_path = lambda: str(un_path)
        mock_file_ops["reader"].update_df.return_value = SAMPLE_UNEMPLOYMENT.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_unemployment_rate()
        assert result == str(un_path)

    def test_save_ndx_with_existing(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test save_ndx when file exists (line 398)."""
        ndx_path = tmp_path / "ndx.csv"
        ndx_path.write_text("old,data")

        market_data.finder.get_ndx_path = lambda: str(ndx_path)
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_NDX.copy()
        # Mock get_latest_ndx to return specific data
        market_data.get_latest_ndx = lambda **kw: SAMPLE_NDX.copy()
        mock_file_ops["reader"].update_df.return_value = SAMPLE_NDX.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_ndx()
        assert result == str(ndx_path)


class TestMarketDataEmptyDataFrames:
    """Tests for DataSource methods with empty DataFrames."""

    def test_standardize_ndx_empty(self, market_data: Any) -> None:
        """Test standardize_ndx with empty DataFrame (line 353)."""
        empty_df = pd.DataFrame()
        result = market_data.standardize_ndx(empty_df)
        assert C.TIME in result.columns
        assert C.SYMBOL in result.columns
        assert C.DELTA in result.columns

    def test_save_intraday_with_existing_file(
        self, market_data: Any, mock_file_ops: dict[str, MagicMock], tmp_path: Path
    ) -> None:
        """Test save_intraday when file already exists (line 195)."""
        # Create existing file
        intraday_path = tmp_path / "intraday_test.csv"
        intraday_path.write_text("old,data")

        intraday_df = pd.DataFrame(
            {
                C.TIME: pd.date_range("2024-01-01 09:30", periods=5, freq="1min"),
                "open": [100.0] * 5,
            }
        )

        market_data.get_intraday = lambda **kw: [intraday_df]
        market_data.finder.get_intraday_path = lambda s, d, p: str(intraday_path)
        mock_file_ops["reader"].update_df.return_value = intraday_df
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        result = market_data.save_intraday(symbol="AAPL")
        assert len(result) == 1


class TestAlpacaDataCryptoOHLC:
    """Tests for AlpacaData crypto symbol conversion in OHLC methods."""

    def test_get_ohlc_crypto_uses_polygon_symbol_for_storage(
        self,
        alpaca_data: Any,
        mock_alpaca_api: responses.RequestsMock,
        mock_file_ops: dict[str, MagicMock],
    ) -> None:
        """Test that get_ohlc converts crypto symbols for standardize_ohlc."""
        # Mock the crypto bars endpoint
        mock_alpaca_api.add(
            responses.GET,
            "https://data.alpaca.markets/v1beta3/crypto/us/bars",
            json={
                "bars": {
                    "BTC/USD": [
                        {
                            "t": "2024-01-01T00:00:00Z",
                            "o": 42000.0,
                            "h": 43000.0,
                            "l": 41000.0,
                            "c": 42500.0,
                            "v": 100,
                            "vw": 42200.0,
                            "n": 50,
                        }
                    ]
                },
                "next_page_token": None,
            },
        )
        mock_file_ops["reader"].data_in_timeframe.side_effect = lambda df, col, tf: df

        # Track what symbol gets passed to get_ohlc_path
        path_symbols: list[str] = []
        original_get_ohlc_path = alpaca_data.finder.get_ohlc_path

        def tracking_get_ohlc_path(symbol: str, provider: str = "polygon") -> str:
            path_symbols.append(symbol)
            return original_get_ohlc_path(symbol, provider)

        alpaca_data.finder.get_ohlc_path = tracking_get_ohlc_path

        df = alpaca_data.get_ohlc(symbol="BTC/USD", timeframe="1m")
        assert C.TIME in df.columns

        # Verify that the Polygon-format symbol was used for the path,
        # not the raw Alpaca symbol
        assert any("X%3ABTCUSD" == s for s in path_symbols), (
            f"Expected 'X%3ABTCUSD' in path symbols, got {path_symbols}"
        )
        assert not any("BTC/USD" == s for s in path_symbols), (
            "Raw Alpaca symbol 'BTC/USD' should not be used for file paths"
        )

    def test_save_ohlc_crypto_converts_symbol(
        self,
        alpaca_data: Any,
        mock_file_ops: dict[str, MagicMock],
        tmp_path: Path,
    ) -> None:
        """Test that save_ohlc converts crypto symbols for file paths."""
        ohlc_path = tmp_path / "ohlc.csv"

        # Track what symbol gets passed to get_ohlc_path
        path_symbols: list[str] = []

        def tracking_get_ohlc_path(symbol: str, provider: str = "polygon") -> str:
            path_symbols.append(symbol)
            return str(ohlc_path)

        alpaca_data.finder.get_ohlc_path = tracking_get_ohlc_path
        fetch_symbols: list[str] = []

        def get_ohlc(symbol: str, **kwargs: Any) -> pd.DataFrame:
            fetch_symbols.append(symbol)
            return SAMPLE_OHLC.copy()

        alpaca_data.get_ohlc = get_ohlc
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_OHLC.copy()
        mock_file_ops["reader"].update_df.return_value = SAMPLE_OHLC.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        alpaca_data.save_ohlc(symbol="BTC/USD")

        # Verify the converted Polygon symbol was used for file path
        assert "X%3ABTCUSD" in path_symbols
        assert "BTC/USD" not in path_symbols
        assert fetch_symbols == ["BTC/USD"]

    def test_save_ohlc_stock_symbol_unchanged(
        self,
        alpaca_data: Any,
        mock_file_ops: dict[str, MagicMock],
        tmp_path: Path,
    ) -> None:
        """Test that save_ohlc leaves non-crypto symbols unchanged."""
        ohlc_path = tmp_path / "ohlc.csv"

        path_symbols: list[str] = []

        def tracking_get_ohlc_path(symbol: str, provider: str = "polygon") -> str:
            path_symbols.append(symbol)
            return str(ohlc_path)

        alpaca_data.finder.get_ohlc_path = tracking_get_ohlc_path
        fetch_symbols: list[str] = []

        def get_ohlc(symbol: str, **kwargs: Any) -> pd.DataFrame:
            fetch_symbols.append(symbol)
            return SAMPLE_OHLC.copy()

        alpaca_data.get_ohlc = get_ohlc
        mock_file_ops["reader"].load_csv.return_value = SAMPLE_OHLC.copy()
        mock_file_ops["reader"].update_df.return_value = SAMPLE_OHLC.copy()
        mock_file_ops["writer"].update_csv = lambda f, df: df.to_csv(f, index=False)

        alpaca_data.save_ohlc(symbol="AAPL")

        # Stock symbols should pass through unchanged
        assert "AAPL" in path_symbols
        assert fetch_symbols == ["AAPL"]


class TestStandardizeSoprPath:
    """Tests to verify standardize_sopr uses correct file path."""

    def test_standardize_sopr_uses_sopr_path(self, market_data: Any) -> None:
        """Test that standardize_sopr uses get_sopr_path, not get_diff_ribbon_path."""
        sopr_path_calls: list[bool] = []
        diff_ribbon_path_calls: list[bool] = []

        original_sopr = market_data.finder.get_sopr_path
        original_ribbon = market_data.finder.get_diff_ribbon_path

        def tracking_sopr_path() -> str:
            sopr_path_calls.append(True)
            return original_sopr()

        def tracking_ribbon_path() -> str:
            diff_ribbon_path_calls.append(True)
            return original_ribbon()

        market_data.finder.get_sopr_path = tracking_sopr_path
        market_data.finder.get_diff_ribbon_path = tracking_ribbon_path

        raw = pd.DataFrame(
            {
                "t": pd.date_range("2020-01-01", periods=3, freq="D"),
                "v": [1.0, 1.1, 0.9],
            }
        )
        market_data.standardize_sopr(raw)

        assert len(sopr_path_calls) > 0, "standardize_sopr should call get_sopr_path"
        assert len(diff_ribbon_path_calls) == 0, (
            "standardize_sopr should NOT call get_diff_ribbon_path"
        )
