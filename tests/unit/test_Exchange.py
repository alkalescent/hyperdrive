"""Unit tests for Exchange module with mocked API clients.

This test file mocks all external API calls to Binance, Kraken, and Alpaca
for fast, deterministic, offline testing.
"""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import responses

# ============================================================
# Sample Response Data
# ============================================================

SAMPLE_BINANCE_ORDER = {
    "symbol": "BTCUSD",
    "orderId": 12345,
    "orderListId": -1,
    "clientOrderId": "test123",
    "transactTime": 1634612257816,
    "price": "0.0000",
    "origQty": "0.00080000",
    "executedQty": "0.00080000",
    "cummulativeQuoteQty": "49.4641",
    "status": "FILLED",
    "timeInForce": "GTC",
    "type": "MARKET",
    "side": "BUY",
    "fills": [
        {
            "price": "61830.1400",
            "qty": "0.00080000",
            "commission": "0.0500",
            "commissionAsset": "USD",
            "tradeId": 24328534,
        }
    ],
}

SAMPLE_KRAKEN_ORDER = {
    "closetm": 1671356188.5147808,
    "opentm": 1671356188.5141125,
    "cost": "5.41340502",
    "descr": {
        "order": "sell 5.41394641 USDCUSD @ market",
        "ordertype": "market",
        "pair": "USDCUSD",
        "type": "sell",
    },
    "fee": "0.01082681",
    "price": "0.9999",
    "status": "closed",
    "vol": "5.41394641",
    "vol_exec": "5.41394641",
    "trades": ["TZX2YO-WCZN5-6GIH3E"],
    "order_id": "OD74VW-UPIQ7-A47XCN",
}

SAMPLE_KRAKEN_TRADE = {
    "cost": "5.41340502",
    "fee": "0.01082681",
    "pair": "USDCUSD",
    "price": "0.99990000",
    "time": 1671356188.5147705,
    "type": "sell",
    "vol": "5.41394641",
    "trade_id": "TZX2YO-WCZN5-6GIH3E",
}


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up mock environment variables."""
    monkeypatch.setenv("BINANCE_KEY", "test_key")
    monkeypatch.setenv("BINANCE_SECRET", "test_secret")
    monkeypatch.setenv("BINANCE_TESTNET_KEY", "test_key")
    monkeypatch.setenv("BINANCE_TESTNET_SECRET", "test_secret")
    monkeypatch.setenv("KRAKEN_KEY", "test_kraken_key")
    monkeypatch.setenv("KRAKEN_SECRET", "dGVzdF9rcmFrZW5fc2VjcmV0")  # base64
    monkeypatch.setenv("ALPACA_PAPER", "test_alpaca_key")
    monkeypatch.setenv("ALPACA_PAPER_SECRET", "test_alpaca_secret")
    monkeypatch.setenv("TEST", "true")


@pytest.fixture
def mock_binance_client(mock_env_vars: None) -> Generator[MagicMock, None, None]:
    """Mock Binance Client."""
    with patch("hyperdrive.Exchange.Client") as MockClient:
        client = MagicMock()

        # Mock constants
        client.ORDER_TYPE_MARKET = "MARKET"
        client.SIDE_BUY = "BUY"
        client.SIDE_SELL = "SELL"

        # Mock get_symbol_info
        client.get_symbol_info.return_value = {
            "baseAsset": "BTC",
            "quoteAsset": "USD",
            "baseAssetPrecision": 8,
            "quoteAssetPrecision": 4,
            "filters": [
                {"filterType": "LOT_SIZE", "stepSize": "0.00000100"},
                {"filterType": "MIN_NOTIONAL", "minNotional": "10.0000"},
            ],
        }

        # Mock get_asset_balance
        client.get_asset_balance.return_value = {"free": "1000.00", "locked": "0"}

        # Mock create_order / create_test_order
        client.create_order.return_value = SAMPLE_BINANCE_ORDER.copy()
        client.create_test_order.return_value = {}

        MockClient.return_value = client
        yield client


@pytest.fixture
def binance(mock_binance_client: MagicMock) -> Any:
    """Create Binance instance with mocked client."""
    from hyperdrive.Exchange import Binance

    return Binance(testnet=True)


@pytest.fixture
def mock_kraken_api(
    mock_env_vars: None,
) -> Generator[responses.RequestsMock, None, None]:
    """Mock Kraken API responses."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        base = "https://api.kraken.com"

        # Mock Balance
        rsps.add(
            responses.POST,
            f"{base}/0/private/Balance",
            json={"result": {"XXBT": "0.5", "ZUSD": "1000"}, "error": []},
        )

        # Mock AssetPairs
        rsps.add(
            responses.GET,
            f"{base}/0/public/AssetPairs",
            json={
                "result": {
                    "XXBTZUSD": {
                        "lot_decimals": 8,
                        "cost_decimals": 5,
                        "ordermin": "0.0001",
                    }
                },
                "error": [],
            },
        )

        # Mock TradeVolume (for fees)
        rsps.add(
            responses.POST,
            f"{base}/0/private/TradeVolume",
            json={"result": {"fees": {"XXBTZUSD": {"fee": "0.26"}}}, "error": []},
        )

        # Mock AddOrder
        rsps.add(
            responses.POST,
            f"{base}/0/private/AddOrder",
            json={"result": {"txid": ["ORDER123"]}, "error": []},
        )

        # Mock QueryOrders
        rsps.add(
            responses.POST,
            f"{base}/0/private/QueryOrders",
            json={"result": {"OD74VW-UPIQ7-A47XCN": SAMPLE_KRAKEN_ORDER}, "error": []},
        )

        # Mock QueryTrades
        rsps.add(
            responses.POST,
            f"{base}/0/private/QueryTrades",
            json={"result": {"TZX2YO-WCZN5-6GIH3E": SAMPLE_KRAKEN_TRADE}, "error": []},
        )

        # Mock Ticker
        rsps.add(
            responses.POST,
            f"{base}/0/public/Ticker",
            json={"result": {"XXBTZUSD": {"c": ["50000.00"]}}, "error": []},
        )

        yield rsps


@pytest.fixture
def kraken(mock_env_vars: None, mock_kraken_api: responses.RequestsMock) -> Any:
    """Create Kraken instance with mocked API."""
    from hyperdrive.Exchange import Kraken

    return Kraken(test=True)


@pytest.fixture
def mock_alpaca_api(
    mock_env_vars: None,
) -> Generator[responses.RequestsMock, None, None]:
    """Mock Alpaca API responses."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        base = "https://paper-api.alpaca.markets/v2"

        # Mock account
        rsps.add(
            responses.GET,
            f"{base}/account",
            json={"status": "ACTIVE", "buying_power": "10000"},
        )

        # Mock positions
        rsps.add(
            responses.GET,
            f"{base}/positions",
            json=[{"symbol": "LTC/USD", "qty": "0.1", "market_value": "10.00"}],
        )

        # Mock create order
        rsps.add(
            responses.POST,
            f"{base}/orders",
            json={"id": "order123", "status": "filled", "symbol": "LTC/USD"},
        )

        # Mock get order
        rsps.add(
            responses.GET,
            f"{base}/orders/order123",
            json={"id": "order123", "status": "filled"},
        )

        # Mock delete position
        rsps.add(
            responses.DELETE,
            f"{base}/positions/LTC/USD",
            json={"id": "close123", "status": "filled"},
        )

        # Mock 404 for invalid routes/orders
        rsps.add(responses.GET, f"{base}/not_a_real_route", status=404)
        rsps.add(responses.GET, f"{base}/orders/not_a_real_id", status=404)

        yield rsps


@pytest.fixture
def alpaca(mock_env_vars: None, mock_alpaca_api: responses.RequestsMock) -> Any:
    """Create AlpacaEx instance with mocked API."""
    from hyperdrive.Exchange import AlpacaEx

    return AlpacaEx(paper=True)


# ============================================================
# Test Classes
# ============================================================


class TestAlpacaEx:
    """Unit tests for AlpacaEx class."""

    def test_init(self, alpaca: Any) -> None:
        """Test AlpacaEx initialization."""
        assert hasattr(alpaca, "base")
        assert alpaca.base == "https://paper-api.alpaca.markets"
        assert hasattr(alpaca, "version")
        assert hasattr(alpaca, "token")
        assert hasattr(alpaca, "secret")

    def test_make_request_success(self, alpaca: Any) -> None:
        """Test successful API request."""
        result = alpaca.make_request("GET", "account")
        assert result["status"] == "ACTIVE"

    def test_make_request_failure(self, alpaca: Any) -> None:
        """Test failed API request raises exception."""
        with pytest.raises(RuntimeError):
            alpaca.make_request("GET", "not_a_real_route")

    def test_get_positions(self, alpaca: Any) -> None:
        """Test getting positions."""
        positions = alpaca.get_positions()
        assert len(positions) == 1
        assert positions[0]["symbol"] == "LTC/USD"

    def test_get_account(self, alpaca: Any) -> None:
        """Test getting account info."""
        account = alpaca.get_account()
        assert account["status"] == "ACTIVE"
        assert account["buying_power"] == "10000"

    def test_create_order(self, alpaca: Any) -> None:
        """Test creating an order."""
        order = alpaca.create_order("LTC/USD", "buy", 10)
        assert order["id"] == "order123"
        assert order["status"] == "filled"

    def test_get_order(
        self, alpaca: Any, mock_alpaca_api: responses.RequestsMock
    ) -> None:
        """Test getting order by ID."""
        # Add specific order response
        mock_alpaca_api.add(
            responses.GET,
            "https://paper-api.alpaca.markets/v2/orders/order123",
            json={"id": "order123", "status": "filled"},
        )
        order = alpaca.get_order("order123")
        assert order["status"] == "filled"

    def test_get_order_not_found(self, alpaca: Any) -> None:
        """Test getting non-existent order raises exception."""
        with pytest.raises(RuntimeError):
            alpaca.get_order("not_a_real_id")

    def test_close_position(self, alpaca: Any) -> None:
        """Test closing a position."""
        result = alpaca.close_position("LTC/USD")
        assert result["status"] == "filled"

    def test_fill_orders(
        self, alpaca: Any, mock_alpaca_api: responses.RequestsMock
    ) -> None:
        """Test filling multiple orders."""
        # Add response for the order
        mock_alpaca_api.add(
            responses.POST,
            "https://paper-api.alpaca.markets/v2/orders",
            json={"id": "order456", "status": "filled", "symbol": "ETH/USD"},
        )
        orders = alpaca.fill_orders(
            ["ETH/USD"], alpaca.create_order, side="buy", notional=10
        )
        assert len(orders) == 1
        assert orders[0]["status"] == "filled"


class TestBinance:
    """Unit tests for Binance class."""

    def test_init(self, binance: Any) -> None:
        """Test Binance initialization."""
        assert hasattr(binance, "key")
        assert hasattr(binance, "secret")
        assert hasattr(binance, "client")

    def test_init_mainnet(
        self, mock_env_vars: None, mock_binance_client: MagicMock
    ) -> None:
        """Test Binance initialization with testnet=False."""
        from hyperdrive.Exchange import Binance

        b = Binance(testnet=False)
        assert b.key == "test_key"
        assert b.secret == "test_secret"

    def test_create_pair(self, binance: Any) -> None:
        """Test pair creation."""
        assert binance.create_pair("BTC", "USD") == "BTCUSD"
        assert binance.create_pair("ETH", "USDT") == "ETHUSDT"

    def test_order_buy(self, binance: Any, mock_binance_client: MagicMock) -> None:
        """Test buy order."""
        mock_binance_client.create_test_order.return_value = {}

        binance.order("BTC", "USD", "buy", 0.01, test=True)

        # Verify the client was called correctly
        mock_binance_client.get_symbol_info.assert_called_with("BTCUSD")
        mock_binance_client.get_asset_balance.assert_called_with("USD")
        mock_binance_client.create_test_order.assert_called_once()

    def test_order_sell(self, binance: Any, mock_binance_client: MagicMock) -> None:
        """Test sell order."""
        mock_binance_client.create_test_order.return_value = {}

        binance.order("BTC", "USD", "sell", 1, test=True)

        mock_binance_client.get_asset_balance.assert_called_with("BTC")
        mock_binance_client.create_test_order.assert_called()

    def test_order_invalid_side(self, binance: Any) -> None:
        """Test order with invalid side raises exception."""
        with pytest.raises(Exception, match="Need to specify BUY or SELL"):
            binance.order("BTC", "USD", "invalid", 0.01)


class TestKraken:
    """Unit tests for Kraken class."""

    def test_init(self, kraken: Any) -> None:
        """Test Kraken initialization."""
        assert hasattr(kraken, "key")
        assert hasattr(kraken, "secret")
        assert hasattr(kraken, "version")
        assert hasattr(kraken, "api_url")
        assert kraken.api_url == "https://api.kraken.com"

    def test_gen_nonce(self, kraken: Any) -> None:
        """Test nonce generation."""
        nonce = kraken.gen_nonce()
        assert isinstance(nonce, str)
        assert len(nonce) > 10

    def test_get_signature(self, kraken: Any) -> None:
        """Test signature generation."""
        data = {"nonce": "1234567890"}
        sig = kraken.get_signature("/0/private/Balance", data)
        assert isinstance(sig, str)
        assert len(sig) > 0

    def test_get_balance(self, kraken: Any) -> None:
        """Test getting account balance."""
        balance = kraken.get_balance()
        assert "XXBT" in balance
        assert "ZUSD" in balance
        assert balance["XXBT"] == 0.5
        assert balance["ZUSD"] == 1000.0

    def test_get_asset_pair(self, kraken: Any) -> None:
        """Test getting asset pair info."""
        pair_info = kraken.get_asset_pair("XXBTZUSD")
        assert "lot_decimals" in pair_info
        assert pair_info["lot_decimals"] == 8

    def test_order_invalid_side(self, kraken: Any) -> None:
        """Test order with invalid side raises exception."""
        with pytest.raises(Exception, match="Need to specify BUY or SELL"):
            kraken.order("XXBT", "ZUSD", "invalid", 0.01)

    def test_standardize_order_buy(self, kraken: Any) -> None:
        """Test standardize_order with BUY side adjusts origQty."""
        buy_order = SAMPLE_KRAKEN_ORDER.copy()
        descr = dict(SAMPLE_KRAKEN_ORDER["descr"])  # type: ignore[arg-type]
        descr["type"] = "buy"
        buy_order["descr"] = descr
        trades = [SAMPLE_KRAKEN_TRADE.copy()]
        std = kraken.standardize_order(buy_order, trades)
        assert std["side"] == "BUY"
        # BUY adjusts origQty by dividing by price
        vol = str(buy_order["vol"])
        assert std["origQty"] != float(vol)

    def test_order_with_test_flag(self, kraken: Any) -> None:
        """Test order with validation (test) flag."""
        result = kraken.order("XXBT", "ZUSD", "sell", 0.005, test=True)
        assert "txid" in result

    def test_standardize_order(self, kraken: Any) -> None:
        """Test order standardization."""
        order = SAMPLE_KRAKEN_ORDER.copy()
        trades = [SAMPLE_KRAKEN_TRADE.copy()]

        std_order = kraken.standardize_order(order, trades)

        assert std_order["symbol"] == "USDCUSD"
        assert std_order["orderId"] == "OD74VW-UPIQ7-A47XCN"
        assert std_order["status"] == "CLOSED"
        assert std_order["type"] == "MARKET"
        assert std_order["side"] == "SELL"
        assert len(std_order["fills"]) == 1

    def test_get_order(self, kraken: Any) -> None:
        """Test getting order by ID (returns order with order_id added)."""
        # Use the existing fixture mock that already has the right response
        order = kraken.get_order("OD74VW-UPIQ7-A47XCN")
        assert order["order_id"] == "OD74VW-UPIQ7-A47XCN"
        assert "status" in order

    def test_get_trades(self, kraken: Any) -> None:
        """Test getting trades by IDs."""
        trades = kraken.get_trades(["TZX2YO-WCZN5-6GIH3E"])
        assert len(trades) == 1
        assert trades[0]["trade_id"] == "TZX2YO-WCZN5-6GIH3E"

    def test_get_fee(
        self, kraken: Any, mock_kraken_api: responses.RequestsMock
    ) -> None:
        """Test getting trading fees."""
        mock_kraken_api.add(
            responses.POST,
            "https://api.kraken.com/0/private/TradeVolume",
            json={"result": {"fees": {"XXBTZUSD": {"fee": "0.26"}}}, "error": []},
        )
        fee = kraken.get_fee("XXBTZUSD")
        assert fee == 0.26

    def test_get_ticker(
        self, kraken: Any, mock_kraken_api: responses.RequestsMock
    ) -> None:
        """Test getting ticker data."""
        mock_kraken_api.add(
            responses.POST,
            "https://api.kraken.com/0/public/Ticker",
            json={"result": {"XXBTZUSD": {"c": ["50000.00"]}}, "error": []},
        )
        ticker = kraken.get_ticker("XXBTZUSD")
        assert "XXBTZUSD" in ticker

    def test_get_price(
        self, kraken: Any, mock_kraken_api: responses.RequestsMock
    ) -> None:
        """Test getting asset price."""
        mock_kraken_api.add(
            responses.POST,
            "https://api.kraken.com/0/public/Ticker",
            json={"result": {"XXBTZUSD": {"c": ["50000.00"]}}, "error": []},
        )
        price = kraken.get_price("XXBTZUSD")
        assert price == 50000.0

    def test_order_buy(
        self, kraken: Any, mock_kraken_api: responses.RequestsMock
    ) -> None:
        """Test buy order."""
        mock_kraken_api.add(
            responses.POST,
            "https://api.kraken.com/0/private/AddOrder",
            json={"result": {"txid": ["BUY123"]}, "error": []},
        )
        result = kraken.order("XXBT", "ZUSD", "buy", 0.01, test=True)
        assert "txid" in result

    def test_get_test_side(self, kraken: Any) -> None:
        """Test getting test order side (opposite for testing)."""
        side = kraken.get_test_side("XXBT", "ZUSD")
        assert side in ["buy", "sell"]

    def test_handle_response_with_error(self, kraken: Any) -> None:
        """Test handling response with API error."""
        mock_response = MagicMock()
        mock_response.json.return_value = {"result": {}, "error": ["Test error"]}

        with pytest.raises(Exception, match="Test error"):
            kraken.handle_response(mock_response)

    def test_make_auth_req(
        self, kraken: Any, mock_kraken_api: responses.RequestsMock
    ) -> None:
        """Test making authenticated request."""
        mock_kraken_api.add(
            responses.POST,
            "https://api.kraken.com/0/private/Balance",
            json={"result": {"XXBT": "1.0"}, "error": []},
        )
        result = kraken.make_auth_req("/0/private/Balance")
        assert isinstance(result, dict)


class TestAlpacaExEdgeCases:
    """Edge case tests for AlpacaEx class."""

    def test_fill_orders_empty(self, alpaca: Any) -> None:
        """Test fill_orders with empty symbols list."""
        orders = alpaca.fill_orders([], alpaca.create_order, side="buy", notional=10)
        assert orders == []

    def test_create_pair(self, alpaca: Any) -> None:
        """Test pair creation - CEX base class uses no separator."""
        # CEX.create_pair returns base+quote without separator
        assert alpaca.create_pair("BTC", "USD") == "BTCUSD"
        assert alpaca.create_pair("ETH", "USDT") == "ETHUSDT"


class TestBinanceEdgeCases:
    """Edge case tests for Binance class."""

    def test_order_real_mode(
        self, binance: Any, mock_binance_client: MagicMock
    ) -> None:
        """Test order in real mode (not test)."""
        mock_binance_client.create_order.return_value = SAMPLE_BINANCE_ORDER.copy()

        result = binance.order("BTC", "USD", "buy", 0.01, test=False)

        mock_binance_client.create_order.assert_called_once()
        assert "orderId" in result

    def test_order_symbol_info_none(
        self, binance: Any, mock_binance_client: MagicMock
    ) -> None:
        """Test order raises when symbol_info is None."""
        mock_binance_client.get_symbol_info.return_value = None
        with pytest.raises(Exception, match="Symbol info not found"):
            binance.order("INVALID", "USD", "buy", 0.01)


class TestAlpacaFillOrders:
    """Tests for AlpacaEx fill_orders with pending orders."""

    def test_fill_orders_with_pending(
        self, alpaca: Any, mock_alpaca_api: responses.RequestsMock
    ) -> None:
        """Test fill_orders adds pending orders to queue (line 52)."""

        def mock_order_func(symbol: str, **kwargs: Any) -> dict[str, Any]:
            return {"id": f"order_{symbol}", "status": "filled", "symbol": symbol}

        orders = alpaca.fill_orders(["AAPL", "GOOG"], mock_order_func, side="buy")
        assert len(orders) == 2

    def test_fill_orders_waits_for_pending(
        self, alpaca: Any, mock_alpaca_api: responses.RequestsMock
    ) -> None:
        """Test fill_orders handles pending orders that later fill (lines 52-59)."""
        call_count = {"AAPL": 0}

        def mock_order_func(symbol: str, **kwargs: Any) -> dict[str, Any]:
            # First order is pending, second is filled
            if symbol == "AAPL":
                return {"id": "order_AAPL", "status": "pending", "symbol": symbol}
            return {"id": f"order_{symbol}", "status": "filled", "symbol": symbol}

        # Mock get_order to return filled status after first call
        def mock_get_order(order_id: str) -> dict[str, str]:
            call_count["AAPL"] += 1
            return {"id": order_id, "status": "filled"}

        alpaca.get_order = mock_get_order

        orders = alpaca.fill_orders(["AAPL", "GOOG"], mock_order_func, side="buy")
        assert len(orders) == 2
        assert call_count["AAPL"] >= 1  # get_order was called to check pending


class TestAlpacaMissingCredentials:
    """Test for missing credentials exception."""

    def test_init_missing_credentials(
        self, mock_env_vars: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Test AlpacaEx raises exception with missing credentials (line 40)."""
        # Remove Alpaca credentials
        monkeypatch.delenv("ALPACA", raising=False)
        monkeypatch.delenv("ALPACA_SECRET", raising=False)
        monkeypatch.delenv("ALPACA_PAPER", raising=False)
        monkeypatch.delenv("ALPACA_PAPER_SECRET", raising=False)

        from hyperdrive.Exchange import AlpacaEx

        with pytest.raises(Exception, match="missing Alpaca credentials"):
            AlpacaEx(token=None, secret=None, paper=False)
