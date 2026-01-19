"""
Unit tests for DataSource module with mocked APIs.

This test file mocks all external API calls to Polygon, Alpaca,
Glassnode, and LaborStats for fast, deterministic, offline testing.
"""
import os
import sys
import pytest
import pandas as pd
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.append('hyperdrive')
import Constants as C  # noqa: E402


# ============================================================
# Sample Test Data
# ============================================================

SAMPLE_SYMBOLS = pd.DataFrame({
    C.SYMBOL: ['AAPL', 'AMZN', 'GOOGL', 'META', 'NFLX'],
    C.NAME: ['Apple', 'Amazon', 'Alphabet', 'Meta', 'Netflix']
})

SAMPLE_OHLC = pd.DataFrame({
    C.TIME: ['2024-01-01', '2024-01-02', '2024-01-03'],
    C.OPEN: [100.0, 102.0, 101.0],
    C.HIGH: [105.0, 106.0, 104.0],
    C.LOW: [99.0, 101.0, 100.0],
    C.CLOSE: [103.0, 104.0, 102.0],
    C.VOL: [1000000, 1100000, 900000],
    C.AVG: [102.0, 103.5, 102.0]
})

SAMPLE_DIVIDENDS = pd.DataFrame({
    C.EX: ['2024-01-15', '2024-04-15', '2024-07-15'],
    C.PAY: ['2024-01-30', '2024-04-30', '2024-07-30'],
    C.DEC: ['2024-01-01', '2024-04-01', '2024-07-01'],
    C.DIV: [0.25, 0.25, 0.26]
})

SAMPLE_SPLITS = pd.DataFrame({
    C.EX: ['2022-07-18', '2020-08-31'],
    C.DEC: ['2022-07-01', '2020-08-01'],
    C.RATIO: ['4:1', '5:1']
})

SAMPLE_UNEMPLOYMENT = pd.DataFrame({
    C.TIME: ['2024-01-01', '2024-02-01', '2024-03-01'],
    C.UN_RATE: [3.7, 3.8, 3.6]
})

SAMPLE_NDX = pd.DataFrame({
    C.TIME: ['2024-01-01', '2024-01-01', '2024-01-01'],
    C.SYMBOL: ['AAPL', 'MSFT', 'AMZN'],
    C.DELTA: ['+', '+', '+']
})

SAMPLE_S2F = pd.DataFrame({
    C.TIME: pd.date_range('2020-01-01', periods=100, freq='D'),
    C.HALVING: [False] * 100,
    C.RATIO: [50.0] * 100
})

SAMPLE_DIFF_RIBBON = pd.DataFrame({
    C.TIME: pd.date_range('2020-01-01', periods=100, freq='D'),
    **{ma: [100.0] * 100 for ma in C.MAs}
})

SAMPLE_SOPR = pd.DataFrame({
    C.TIME: pd.date_range('2020-01-01', periods=100, freq='D'),
    C.SOPR: [1.0] * 100
})


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set up mock environment variables."""
    monkeypatch.setenv('POLYGON', 'test_polygon_key')
    monkeypatch.setenv('AWS_ACCESS_KEY_ID', 'test_aws_key')
    monkeypatch.setenv('AWS_SECRET_ACCESS_KEY', 'test_aws_secret')
    monkeypatch.setenv('AWS_DEFAULT_REGION', 'us-east-1')
    monkeypatch.setenv('S3_BUCKET', 'test-bucket')
    monkeypatch.setenv('S3_DEV_BUCKET', 'test-dev-bucket')
    monkeypatch.setenv('ALPACA_PAPER', 'test_alpaca_key')
    monkeypatch.setenv('ALPACA_PAPER_SECRET', 'test_alpaca_secret')
    monkeypatch.setenv('BLS', 'test_bls_key')
    monkeypatch.setenv('GLASSNODE', 'test_glassnode_key')
    monkeypatch.setenv('DEV', 'true')
    monkeypatch.setenv('TEST', 'true')


@pytest.fixture
def mock_file_ops(mock_env_vars):
    """Mock file operations (FileReader, FileWriter, Store)."""
    with patch('hyperdrive.DataSource.FileWriter') as MockWriter, \
         patch('hyperdrive.DataSource.FileReader') as MockReader, \
         patch('hyperdrive.FileOps.Store') as MockStore:

        reader = MagicMock()
        writer = MagicMock()
        store = MagicMock()

        # Configure reader
        reader.load_csv.return_value = SAMPLE_OHLC.copy()
        reader.check_file_exists.return_value = True
        reader.store = store
        reader.data_in_timeframe.side_effect = lambda df, col, tf: df

        # Configure store
        store.modified_delta.return_value = timedelta(seconds=30)
        store.key_exists.return_value = True

        # Configure writer
        writer.save_csv.return_value = True

        MockReader.return_value = reader
        MockWriter.return_value = writer
        MockStore.return_value = store

        yield {'reader': reader, 'writer': writer, 'store': store}


@pytest.fixture
def mock_polygon_client(mock_env_vars):
    """Mock Polygon RESTClient."""
    with patch('hyperdrive.DataSource.RESTClient') as MockClient:
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
            split.split_to = int(row[C.RATIO].split(':')[0])
            split_results.append(split)
        client.list_splits.return_value = split_results

        # Mock get_aggs (OHLC)
        agg_results = []
        for _, row in SAMPLE_OHLC.iterrows():
            agg = MagicMock()
            agg.timestamp = row[C.TIME]
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
def market_data(mock_file_ops, mock_polygon_client):
    """Create MarketData instance with mocked dependencies."""
    from DataSource import MarketData
    md = MarketData()
    # Override reader/writer with mocks
    md.reader = mock_file_ops['reader']
    md.writer = mock_file_ops['writer']
    md.reader.load_csv.return_value = SAMPLE_SYMBOLS.copy()
    return md


@pytest.fixture
def polygon(mock_file_ops, mock_polygon_client):
    """Create Polygon instance with mocked dependencies."""
    from DataSource import Polygon
    poly = Polygon()
    poly.reader = mock_file_ops['reader']
    poly.writer = mock_file_ops['writer']
    return poly


@pytest.fixture
def indices(mock_file_ops):
    """Create Indices instance with mocked dependencies."""
    from DataSource import Indices

    with patch.object(Indices, 'get_ndx', return_value=SAMPLE_NDX.copy()):
        idc = Indices()
        yield idc


@pytest.fixture
def mock_alpaca_api(mock_env_vars):
    """Mock Alpaca data API."""
    import responses

    with responses.RequestsMock() as rsps:
        base = 'https://data.alpaca.markets/v2'

        # Mock bars endpoint
        rsps.add(
            responses.GET,
            f'{base}/stocks/AAPL/bars',
            json={
                'bars': [
                    {'t': '2024-01-01T00:00:00Z', 'o': 100.0, 'h': 105.0,
                     'l': 99.0, 'c': 103.0, 'v': 1000000, 'vw': 102.0}
                ]
            }
        )

        yield rsps


@pytest.fixture
def alpaca_data(mock_file_ops, mock_alpaca_api):
    """Create AlpacaData instance with mocked dependencies."""
    from DataSource import AlpacaData
    alpc = AlpacaData(paper=True)
    alpc.reader = mock_file_ops['reader']
    alpc.writer = mock_file_ops['writer']
    return alpc


@pytest.fixture
def mock_bls_api(mock_env_vars):
    """Mock Bureau of Labor Statistics API."""
    import responses

    with responses.RequestsMock() as rsps:
        rsps.add(
            responses.POST,
            'https://api.bls.gov/publicAPI/v2/timeseries/data/',
            json={
                'Results': {
                    'series': [{
                        'data': [
                            {'year': '2024', 'period': 'M01', 'value': '3.7'},
                            {'year': '2024', 'period': 'M02', 'value': '3.8'},
                            {'year': '2024', 'period': 'M03', 'value': '3.6'}
                        ]
                    }]
                }
            }
        )
        yield rsps


@pytest.fixture
def labor_stats(mock_file_ops, mock_bls_api):
    """Create LaborStats instance with mocked dependencies."""
    from DataSource import LaborStats
    bls = LaborStats()
    bls.reader = mock_file_ops['reader']
    bls.writer = mock_file_ops['writer']
    return bls


@pytest.fixture
def mock_glassnode_api(mock_env_vars):
    """Mock Glassnode API."""
    import responses

    with responses.RequestsMock() as rsps:
        base = 'https://api.glassnode.com/v1'

        # Mock S2F endpoint
        rsps.add(
            responses.GET,
            f'{base}/metrics/indicators/stock_to_flow_ratio',
            json=[{'t': 1609459200, 'v': 50.0}] * 100
        )

        # Mock difficulty ribbon
        rsps.add(
            responses.GET,
            f'{base}/metrics/mining/difficulty_ribbon',
            json=[{'t': 1609459200, 'o': {ma: 100.0 for ma in C.MAs}}] * 100
        )

        # Mock SOPR
        rsps.add(
            responses.GET,
            f'{base}/metrics/indicators/sopr',
            json=[{'t': 1609459200, 'v': 1.0}] * 100
        )

        yield rsps


@pytest.fixture
def glassnode(mock_file_ops, mock_glassnode_api):
    """Create Glassnode instance with mocked dependencies."""
    from DataSource import Glassnode
    glass = Glassnode()
    glass.reader = mock_file_ops['reader']
    glass.writer = mock_file_ops['writer']
    return glass


# ============================================================
# Test Classes
# ============================================================

class TestMarketData:
    """Unit tests for MarketData class."""

    def test_init(self, market_data):
        """Test MarketData initialization."""
        assert type(market_data).__name__ == 'MarketData'
        assert hasattr(market_data, 'writer')
        assert hasattr(market_data, 'reader')
        assert hasattr(market_data, 'finder')
        assert hasattr(market_data, 'provider')

    def test_try_again_success(self, market_data):
        """Test try_again with successful function."""
        result = market_data.try_again(lambda: 42)
        assert result == 42

    def test_try_again_failure(self, market_data):
        """Test try_again with failing function raises exception."""
        with pytest.raises(ZeroDivisionError):
            market_data.try_again(lambda: 1 / 0)

    def test_get_symbols(self, market_data, mock_file_ops):
        """Test getting symbols list."""
        mock_file_ops['reader'].load_csv.return_value = SAMPLE_SYMBOLS.copy()
        symbols = market_data.get_symbols()
        assert 'AAPL' in symbols
        assert 'AMZN' in symbols
        assert 'NFLX' in symbols

    def test_get_dividends(self, market_data, mock_file_ops):
        """Test getting dividend data."""
        mock_file_ops['reader'].load_csv.return_value = SAMPLE_DIVIDENDS.copy()
        df = market_data.get_dividends(symbol='AAPL')
        assert {C.EX, C.PAY, C.DEC, C.DIV}.issubset(df.columns)

    def test_standardize_dividends(self, market_data):
        """Test dividend data standardization."""
        raw = pd.DataFrame({
            'exDate': ['2024-01-15'],
            'paymentDate': ['2024-01-30'],
            'declaredDate': ['2024-01-01'],
            'amount': [0.25]
        })
        result = market_data.standardize_dividends('AAPL', raw)
        assert C.EX in result.columns
        assert C.PAY in result.columns
        assert C.DEC in result.columns
        assert C.DIV in result.columns

    def test_standardize_dividends_partial_columns(self, market_data):
        """Test dividend standardization with partial columns."""
        raw = pd.DataFrame({'exDate': ['2024-01-15'], 'paymentDate': ['2024-01-30']})
        result = market_data.standardize_dividends('AAPL', raw)
        assert C.EX in result.columns
        assert C.PAY in result.columns

    def test_get_splits(self, market_data, mock_file_ops):
        """Test getting splits data."""
        mock_file_ops['reader'].load_csv.return_value = SAMPLE_SPLITS.copy()
        df = market_data.get_splits('AAPL')
        assert {C.EX, C.DEC, C.RATIO}.issubset(df.columns)

    def test_standardize_splits(self, market_data):
        """Test splits data standardization."""
        raw = pd.DataFrame({
            'exDate': ['2022-07-18'],
            'paymentDate': ['2022-07-18'],
            'declaredDate': ['2022-07-01'],
            'ratio': ['4:1']
        })
        result = market_data.standardize_splits('AAPL', raw)
        assert C.EX in result.columns
        assert C.RATIO in result.columns

    def test_standardize_ohlc(self, market_data):
        """Test OHLC data standardization."""
        raw = pd.DataFrame({
            'date': ['2024-01-01'],
            'open': [100.0],
            'high': [105.0],
            'low': [99.0],
            'close': [103.0],
            'volume': [1000000]
        })
        result = market_data.standardize_ohlc('AAPL', raw)
        assert C.TIME in result.columns
        assert C.OPEN in result.columns
        assert C.CLOSE in result.columns
        assert C.VOL in result.columns

    def test_get_ohlc(self, market_data, mock_file_ops):
        """Test getting OHLC data."""
        mock_file_ops['reader'].load_csv.return_value = SAMPLE_OHLC.copy()
        df = market_data.get_ohlc('AAPL', '1y')
        assert {C.TIME, C.OPEN, C.HIGH, C.LOW, C.CLOSE, C.VOL}.issubset(df.columns)

    def test_get_unemployment_rate(self, market_data, mock_file_ops):
        """Test getting unemployment rate data."""
        mock_file_ops['reader'].load_csv.return_value = SAMPLE_UNEMPLOYMENT.copy()
        df = market_data.get_unemployment_rate()
        assert {C.TIME, C.UN_RATE}.issubset(df.columns)

    def test_standardize_unemployment(self, market_data):
        """Test unemployment data standardization."""
        raw = pd.DataFrame({'time': ['2024-01-01'], 'value': [3.7]})
        result = market_data.standardize_unemployment(raw)
        assert C.TIME in result.columns
        assert C.UN_RATE in result.columns

    def test_get_ndx(self, market_data, mock_file_ops):
        """Test getting NDX index data."""
        mock_file_ops['reader'].load_csv.return_value = SAMPLE_NDX.copy()
        df = market_data.get_ndx()
        assert {C.TIME, C.SYMBOL, C.DELTA}.issubset(df.columns)

    def test_standardize_ndx(self, market_data):
        """Test NDX data standardization (removes duplicates, keeps latest)."""
        nonstd = pd.DataFrame({
            C.TIME: ['2020-01-03', '2020-01-01', '2020-01-02'],
            C.SYMBOL: ['AAPL', 'NFLX', 'AAPL'],
            C.DELTA: ['-', '+', '+'],
        })
        std = market_data.standardize_ndx(nonstd)
        # Should keep only symbols that end with '+' delta
        assert (std[C.DELTA] == '+').all()

    def test_log_api_call_time(self, market_data):
        """Test API call time logging."""
        if hasattr(market_data, 'last_api_call_time'):
            delattr(market_data, 'last_api_call_time')
        market_data.log_api_call_time()
        assert hasattr(market_data, 'last_api_call_time')


class TestIndices:
    """Unit tests for Indices class."""

    def test_init(self, mock_file_ops):
        """Test Indices initialization."""
        from DataSource import Indices
        idc = Indices()
        assert isinstance(idc, Indices)

    def test_get_ndx(self, indices):
        """Test getting NDX index constituents."""
        ndx = indices.get_ndx()
        assert {C.TIME, C.SYMBOL, C.DELTA}.issubset(ndx.columns)


class TestPolygon:
    """Unit tests for Polygon class."""

    def test_init(self, polygon):
        """Test Polygon initialization."""
        assert hasattr(polygon, 'client')
        assert hasattr(polygon, 'provider')

    def test_get_dividends(self, polygon, mock_polygon_client):
        """Test getting dividend data from Polygon."""
        df = polygon.get_dividends(symbol='AAPL', timeframe='5y')
        assert {C.EX, C.PAY, C.DEC, C.DIV}.issubset(df.columns)
        mock_polygon_client.list_dividends.assert_called()

    def test_get_splits(self, polygon, mock_polygon_client):
        """Test getting splits data from Polygon."""
        df = polygon.get_splits(symbol='AAPL')
        assert {C.EX, C.DEC, C.RATIO}.issubset(df.columns)
        mock_polygon_client.list_splits.assert_called()

    def test_get_ohlc(self, polygon, mock_polygon_client):
        """Test getting OHLC data from Polygon."""
        df = polygon.get_ohlc(symbol='AAPL', timeframe='1m')
        assert {C.TIME, C.OPEN, C.HIGH, C.LOW, C.CLOSE, C.VOL}.issubset(df.columns)
        mock_polygon_client.get_aggs.assert_called()

    def test_log_api_call_time(self, polygon):
        """Test API call time logging."""
        if hasattr(polygon, 'last_api_call_time'):
            delattr(polygon, 'last_api_call_time')
        polygon.log_api_call_time()
        assert hasattr(polygon, 'last_api_call_time')


class TestAlpacaData:
    """Unit tests for AlpacaData class."""

    def test_init(self, alpaca_data):
        """Test AlpacaData initialization."""
        assert hasattr(alpaca_data, 'base')
        assert hasattr(alpaca_data, 'token')
        assert hasattr(alpaca_data, 'secret')
        assert hasattr(alpaca_data, 'provider')


class TestLaborStats:
    """Unit tests for LaborStats class."""

    def test_init(self, labor_stats):
        """Test LaborStats initialization."""
        assert hasattr(labor_stats, 'base')
        assert hasattr(labor_stats, 'version')
        assert hasattr(labor_stats, 'token')
        assert hasattr(labor_stats, 'provider')

    def test_get_unemployment_rate(self, labor_stats, mock_bls_api):
        """Test getting unemployment rate from BLS API."""
        df = labor_stats.get_unemployment_rate(timeframe='2y')
        assert {C.TIME, C.UN_RATE}.issubset(df.columns)


class TestGlassnode:
    """Unit tests for Glassnode class."""

    def test_init(self, glassnode):
        """Test Glassnode initialization."""
        assert hasattr(glassnode, 'base')
        assert hasattr(glassnode, 'version')
        assert hasattr(glassnode, 'token')
        assert hasattr(glassnode, 'provider')
