"""
Pytest configuration and shared fixtures for hyperdrive tests.

This module provides:
- Sample data fixtures (OHLC, dividends, splits, etc.)
- Mock service fixtures (S3, Polygon, Binance, Kraken, Alpaca, Robinhood)
- Common test utilities
"""

import os
import sys
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Add hyperdrive to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "hyperdrive"))

import Constants as C  # noqa: E402

# ============================================================
# Pytest Configuration
# ============================================================


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (uses real APIs)"
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless explicitly requested."""
    if config.getoption("--run-integration", default=False):
        return
    skip_integration = pytest.mark.skip(reason="need --run-integration option")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


def pytest_addoption(parser):
    """Add custom CLI options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="run integration tests that use real APIs",
    )


# ============================================================
# Sample Data Fixtures
# ============================================================


@pytest.fixture
def sample_ohlc_df():
    """Standard OHLC data for testing."""
    return pd.DataFrame(
        {
            C.TIME: [
                "2024-01-01",
                "2024-01-02",
                "2024-01-03",
                "2024-01-04",
                "2024-01-05",
            ],
            C.OPEN: [100.0, 102.0, 101.0, 103.0, 105.0],
            C.HIGH: [105.0, 106.0, 104.0, 108.0, 110.0],
            C.LOW: [99.0, 101.0, 100.0, 102.0, 104.0],
            C.CLOSE: [103.0, 104.0, 102.0, 107.0, 108.0],
            C.VOL: [1000000, 1100000, 900000, 1200000, 1300000],
        }
    )


@pytest.fixture
def sample_ohlc_with_avg_df(sample_ohlc_df):
    """OHLC data with average column (Polygon/Alpaca format)."""
    df = sample_ohlc_df.copy()
    df[C.AVG] = (df[C.HIGH] + df[C.LOW]) / 2
    return df


@pytest.fixture
def sample_dividends_df():
    """Standard dividend data for testing."""
    return pd.DataFrame(
        {
            C.EX: ["2024-01-15", "2024-04-15", "2024-07-15", "2024-10-15"],
            C.PAY: ["2024-01-30", "2024-04-30", "2024-07-30", "2024-10-30"],
            C.DEC: ["2024-01-01", "2024-04-01", "2024-07-01", "2024-10-01"],
            C.DIV: [0.25, 0.25, 0.26, 0.26],
        }
    )


@pytest.fixture
def sample_splits_df():
    """Standard splits data for testing."""
    return pd.DataFrame(
        {
            C.EX: ["2022-07-18", "2020-08-31"],
            C.DEC: ["2022-07-01", "2020-08-01"],
            C.RATIO: ["4:1", "5:1"],
        }
    )


@pytest.fixture
def sample_symbols_df():
    """Sample symbols list for testing."""
    return pd.DataFrame(
        {
            C.SYMBOL: ["AAPL", "AMZN", "GOOGL", "META", "NFLX"],
            C.NAME: [
                "Apple Inc.",
                "Amazon.com",
                "Alphabet Inc.",
                "Meta Platforms",
                "Netflix",
            ],
        }
    )


@pytest.fixture
def sample_unemployment_df():
    """Sample unemployment rate data."""
    return pd.DataFrame(
        {C.TIME: ["2024-01-01", "2024-02-01", "2024-03-01"], C.UN_RATE: [3.7, 3.8, 3.6]}
    )


@pytest.fixture
def sample_ndx_df():
    """Sample NDX index constituent data."""
    return pd.DataFrame(
        {
            C.TIME: ["2024-01-01", "2024-01-01", "2024-01-01"],
            C.SYMBOL: ["AAPL", "MSFT", "AMZN"],
            C.DELTA: ["+", "+", "+"],
        }
    )


# ============================================================
# Mock S3/Storage Fixtures
# ============================================================


@pytest.fixture
def mock_s3_store():
    """Mock S3 Store that simulates all S3 operations in memory."""
    with patch("hyperdrive.Storage.boto3") as mock_boto:
        # Create mock bucket
        mock_bucket = MagicMock()
        mock_bucket.objects.filter.return_value = []

        # Create mock S3 resource
        mock_s3 = MagicMock()
        mock_s3.Bucket.return_value = mock_bucket
        mock_boto.resource.return_value = mock_s3

        # Mock object operations
        mock_obj = MagicMock()
        mock_obj.last_modified = datetime.now()
        mock_bucket.Object.return_value = mock_obj

        yield {
            "boto": mock_boto,
            "s3": mock_s3,
            "bucket": mock_bucket,
            "object": mock_obj,
        }


@pytest.fixture
def mock_store(mock_s3_store):
    """Higher-level mock for Store class."""
    with patch("hyperdrive.FileOps.Store") as MockStore:
        store = MagicMock()
        store.key_exists.return_value = True
        store.get_keys.return_value = ["data/symbols.csv", "README.md"]
        store.download_file.return_value = None
        store.upload_file.return_value = None
        store.modified_delta.return_value = timedelta(seconds=30)
        store.finder = MagicMock()
        MockStore.return_value = store
        yield store


# ============================================================
# Mock API Client Fixtures
# ============================================================


@pytest.fixture
def mock_polygon_client(sample_ohlc_df, sample_dividends_df, sample_splits_df):
    """Mock Polygon API client."""
    with patch("hyperdrive.DataSource.RESTClient") as MockClient:
        client = MagicMock()

        # Mock dividends response
        div_results = []
        for _, row in sample_dividends_df.iterrows():
            div = MagicMock()
            div.ex_dividend_date = row[C.EX]
            div.pay_date = row[C.PAY]
            div.declaration_date = row[C.DEC]
            div.cash_amount = row[C.DIV]
            div_results.append(div)
        client.list_dividends.return_value = div_results

        # Mock splits response
        split_results = []
        for _, row in sample_splits_df.iterrows():
            split = MagicMock()
            split.execution_date = row[C.EX]
            split.split_from = 1
            split.split_to = int(row[C.RATIO].split(":")[0])
            split_results.append(split)
        client.list_splits.return_value = split_results

        # Mock aggregates (OHLC) response
        agg_results = []
        for _, row in sample_ohlc_df.iterrows():
            agg = MagicMock()
            agg.timestamp = row[C.TIME]
            agg.open = row[C.OPEN]
            agg.high = row[C.HIGH]
            agg.low = row[C.LOW]
            agg.close = row[C.CLOSE]
            agg.volume = row[C.VOL]
            agg.vwap = (row[C.HIGH] + row[C.LOW]) / 2
            agg_results.append(agg)
        client.get_aggs.return_value = agg_results

        MockClient.return_value = client
        yield client


@pytest.fixture
def mock_binance_client():
    """Mock Binance client."""
    with patch("hyperdrive.Exchange.Client") as MockClient:
        client = MagicMock()

        # Mock account info
        client.get_account.return_value = {
            "balances": [
                {"asset": "BTC", "free": "0.5", "locked": "0"},
                {"asset": "USD", "free": "1000", "locked": "0"},
            ]
        }

        # Mock symbol info
        client.get_symbol_info.return_value = {
            "baseAsset": "BTC",
            "quoteAsset": "USD",
            "baseAssetPrecision": 8,
            "quoteAssetPrecision": 2,
            "filters": [
                {"filterType": "LOT_SIZE", "minQty": "0.00001", "stepSize": "0.00001"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "10"},
            ],
        }

        # Mock order response
        client.create_order.return_value = {
            "symbol": "BTCUSD",
            "orderId": 12345,
            "status": "FILLED",
            "executedQty": "0.001",
            "cummulativeQuoteQty": "50.00",
            "fills": [{"price": "50000", "qty": "0.001", "commission": "0.00"}],
        }

        MockClient.return_value = client
        yield client


@pytest.fixture
def mock_kraken_responses():
    """Mock Kraken API responses."""
    import responses

    @responses.activate
    def _mock():
        # Mock balance endpoint
        responses.add(
            responses.POST,
            "https://api.kraken.com/0/private/Balance",
            json={"result": {"XXBT": "0.5", "ZUSD": "1000"}},
            status=200,
        )

        # Mock order endpoint
        responses.add(
            responses.POST,
            "https://api.kraken.com/0/private/AddOrder",
            json={"result": {"txid": ["ORDER123"]}},
            status=200,
        )

        yield

    return _mock


@pytest.fixture
def mock_alpaca_responses():
    """Mock Alpaca API responses using responses library."""
    import responses

    base_url = "https://paper-api.alpaca.markets"

    with responses.RequestsMock() as rsps:
        # Mock account
        rsps.add(
            responses.GET,
            f"{base_url}/v2/account",
            json={"status": "ACTIVE", "buying_power": "10000"},
            status=200,
        )

        # Mock positions
        rsps.add(
            responses.GET,
            f"{base_url}/v2/positions",
            json=[{"symbol": "BTC/USD", "qty": "0.1"}],
            status=200,
        )

        # Mock orders
        rsps.add(
            responses.POST,
            f"{base_url}/v2/orders",
            json={"id": "order123", "status": "filled"},
            status=200,
        )

        yield rsps


@pytest.fixture
def mock_robinhood():
    """Mock Robinhood API via robin_stocks."""
    with patch("hyperdrive.Broker.rh") as mock_rh:
        # Mock login
        mock_rh.login.return_value = {"access_token": "test_token"}

        # Mock historicals
        mock_rh.get_stock_historicals.return_value = [
            {
                "symbol": "AAPL",
                "begins_at": "2024-01-01T00:00:00Z",
                "open_price": "100.00",
                "close_price": "102.00",
                "high_price": "103.00",
                "low_price": "99.00",
                "volume": 1000000,
            }
        ]

        # Mock name lookup
        mock_rh.get_name_by_symbol.side_effect = lambda s: {
            "AAPL": "Apple Inc.",
            "AMZN": "Amazon.com",
            "META": "Meta Platforms",
            "NFLX": "Netflix",
        }.get(s, "Unknown")

        # Mock holdings
        mock_rh.build_holdings.return_value = {
            "AAPL": {"name": "Apple Inc.", "quantity": "10"},
            "AMZN": {"name": "Amazon.com", "quantity": "5"},
        }

        yield mock_rh


# ============================================================
# Utility Fixtures
# ============================================================


@pytest.fixture
def temp_data_dir(tmp_path):
    """Create a temporary data directory structure."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "ohlc" / "polygon").mkdir(parents=True)
    (data_dir / "dividends" / "polygon").mkdir(parents=True)
    (data_dir / "splits" / "polygon").mkdir(parents=True)
    (data_dir / "intraday" / "polygon").mkdir(parents=True)
    return data_dir


@pytest.fixture
def mock_env_vars(monkeypatch):
    """Set up mock environment variables for testing."""
    monkeypatch.setenv("POLYGON", "test_polygon_key")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test_aws_key")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test_aws_secret")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("S3_DEV_BUCKET", "test-dev-bucket")
    monkeypatch.setenv("BINANCE_TESTNET_KEY", "test_binance_key")
    monkeypatch.setenv("BINANCE_TESTNET_SECRET", "test_binance_secret")
    monkeypatch.setenv("ALPACA_PAPER", "test_alpaca_key")
    monkeypatch.setenv("ALPACA_PAPER_SECRET", "test_alpaca_secret")
    monkeypatch.setenv("RH_USERNAME", "test_user")
    monkeypatch.setenv("RH_PASSWORD", "test_pass")
    monkeypatch.setenv("RH_2FA", "JBSWY3DPEHPK3PXP")  # Test TOTP secret
    monkeypatch.setenv("DEV", "true")
