"""Cryptocurrency exchange integrations for trading operations."""

import base64
import hashlib
import hmac
import os
import time
import urllib.parse
from collections.abc import Callable, Iterable
from time import sleep
from typing import Any

import requests
from binance import Client
from binance.helpers import round_step_size
from dotenv import find_dotenv, load_dotenv

from . import Constants as C

load_dotenv(find_dotenv("config.env"))


class CEX:
    """Base class for centralized exchange clients.

    Provides common functionality shared by exchange implementations.
    """

    def create_pair(self, base: str, quote: str) -> str:
        """Create a trading pair symbol from base and quote currencies.

        Args:
            base: Base currency symbol (e.g., 'BTC').
            quote: Quote currency symbol (e.g., 'USD').

        Returns:
            Combined trading pair (e.g., 'BTCUSD').
        """
        return f"{base}{quote}"


class AlpacaEx(CEX):
    """Alpaca exchange client for stock and crypto trading.

    Attributes:
        base: Base API URL.
        version: API version string.
        token: API key.
        secret: API secret.
    """

    def __init__(
        self,
        token: str | None = os.environ.get("ALPACA"),
        secret: str | None = os.environ.get("ALPACA_SECRET"),
        paper: bool = False,
    ) -> None:
        """Initialize the Alpaca client.

        Args:
            token: API key. Defaults to ALPACA env var.
            secret: API secret. Defaults to ALPACA_SECRET env var.
            paper: Use paper trading account if True.

        Raises:
            Exception: If credentials are missing.
        """
        super().__init__()
        self.base = f"https://{'paper-' if paper or C.TEST else ''}api.alpaca.markets"
        self.version = "v2"
        self.token = os.environ.get("ALPACA_PAPER") if paper or C.TEST else token
        self.secret = (
            os.environ.get("ALPACA_PAPER_SECRET") if paper or C.TEST else secret
        )
        if not (self.token and self.secret):
            raise Exception("missing Alpaca credentials")

    def fill_orders(
        self,
        symbols: Iterable[str],
        func: Callable[..., dict[str, Any]],
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """Execute orders for multiple symbols and wait for fills.

        Args:
            symbols: Symbols to trade.
            func: Order function to call for each symbol.
            **kwargs: Additional arguments for the order function.

        Returns:
            List of completed order responses.
        """
        pending_orders: set[str] = set()
        completed_orders: list[dict[str, Any]] = []
        for symbol in symbols:
            order = func(symbol, **kwargs)
            if order["status"] == "filled":
                completed_orders.append(order)
            else:
                pending_orders.add(order["id"])
        while pending_orders:
            for id in list(pending_orders):
                order = self.get_order(id)
                if order["status"] == "filled":
                    completed_orders.append(order)
                    pending_orders.discard(id)
            sleep(1)
        return completed_orders

    def make_request(
        self,
        method: str,
        route: str,
        payload: dict[str, Any] | None = None,
    ) -> Any:
        """Make an authenticated API request.

        Args:
            method: HTTP method (GET, POST, DELETE, etc.).
            route: API endpoint route.
            payload: Request body for POST requests.

        Returns:
            JSON response data.

        Raises:
            RuntimeError: If the request fails.
        """
        payload = payload or {}
        parts = [self.base, self.version, route]
        url = "/".join(parts)
        headers = {
            "accept": "application/json",
            "APCA-API-KEY-ID": self.token,
            "APCA-API-SECRET-KEY": self.secret,
        }
        response = requests.request(method, url, json=payload, headers=headers)
        if response.ok:
            return response.json()
        else:
            raise RuntimeError(response.text)

    def get_positions(self) -> Any:
        """Get all open positions.

        Returns:
            List of position data.
        """
        return self.make_request("GET", "positions")

    def close_position(self, symbol: str) -> Any:
        """Close a position for a symbol.

        Args:
            symbol: Trading symbol to close.

        Returns:
            Close order response.
        """
        return self.make_request("DELETE", f"positions/{symbol}")

    def get_order(self, id: str) -> Any:
        """Get order details by ID.

        Args:
            id: Order ID.

        Returns:
            Order data.
        """
        return self.make_request("GET", f"orders/{id}")

    def get_account(self) -> Any:
        """Get account information.

        Returns:
            Account data including balances.
        """
        return self.make_request("GET", "account")

    def create_order(self, symbol: str, side: str, notional: int | float | str) -> Any:
        """Create a market order by notional value.

        Args:
            symbol: Trading symbol.
            side: 'buy' or 'sell'.
            notional: Dollar amount to trade.

        Returns:
            Order response.
        """
        payload = {
            "symbol": symbol,
            "side": side.lower(),
            "type": "market",
            "notional": str(notional),
            "time_in_force": ("gtc" if symbol in C.ALPC_CRYPTO_SYMBOLS else "day"),
        }
        return self.make_request("POST", "orders", payload)


class Kraken(CEX):
    """Kraken exchange client for cryptocurrency trading.

    Attributes:
        key: API key.
        secret: API secret.
        test: Enable test mode.
        api_url: Base API URL.
        version: API version.
    """

    def __init__(
        self,
        key: str | None = None,
        secret: str | None = None,
        test: bool = False,
    ) -> None:
        """Initialize the Kraken client.

        Args:
            key: API key. Defaults to KRAKEN_KEY env var.
            secret: API secret. Defaults to KRAKEN_SECRET env var.
            test: Enable test/validation mode.
        """
        super().__init__()
        self.key = key
        self.secret = secret
        self.test = test
        if not key:
            self.key = os.environ["KRAKEN_KEY"]
        if not secret:
            self.secret = os.environ["KRAKEN_SECRET"]
        self.api_url = "https://api.kraken.com"
        self.version = "0"

    def get_signature(self, urlpath: str, data: dict[str, Any]) -> str:
        """Generate API signature for authenticated requests.

        Args:
            urlpath: API endpoint path.
            data: Request data including nonce.

        Returns:
            Base64-encoded signature string.
        """
        postdata = urllib.parse.urlencode(data)
        encoded = (str(data["nonce"]) + postdata).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()

        mac = hmac.new(base64.b64decode(self.secret or ""), message, hashlib.sha512)
        sigdigest = base64.b64encode(mac.digest())
        return sigdigest.decode()

    def make_auth_req(self, uri_path: str, data: dict[str, Any] | None = None) -> Any:
        """Make an authenticated API request.

        Args:
            uri_path: API endpoint path.
            data: Request data.

        Returns:
            API response result.
        """
        data = data or {}
        data["nonce"] = self.gen_nonce()
        headers: dict[str, str] = {}
        headers["API-Key"] = self.key or ""
        # Equivalent to get_kraken_signature() in the Authentication section of
        # Kraken's REST API docs.
        headers["API-Sign"] = self.get_signature(uri_path, data)
        response = requests.post((self.api_url + uri_path), headers=headers, data=data)
        return self.handle_response(response)

    def gen_nonce(self) -> str:
        """Generate a unique nonce for API requests.

        Returns:
            Millisecond timestamp as string.
        """
        return str(int(1000 * time.time()))

    def get_balance(self) -> dict[str, float]:
        """Get account balances for all assets.

        Returns:
            Dictionary mapping asset symbols to balances.
        """
        access = "private"
        endpoint = "Balance"
        parts = [
            "",
            self.version,
            access,
            endpoint,
        ]
        url = "/".join(parts)
        response = self.make_auth_req(url)
        for asset in response:
            response[asset] = float(response[asset])
        return response

    def get_asset_pair(self, pair: str) -> dict[str, Any]:
        """Get trading pair information.

        Args:
            pair: Trading pair symbol.

        Returns:
            Pair configuration and limits.
        """
        access = "public"
        endpoint = "AssetPairs"
        parts = [
            self.api_url,
            self.version,
            access,
            endpoint,
        ]
        url = "/".join(parts)
        params = {"pair": pair}
        response = requests.get(url, params=params)
        result = self.handle_response(response)[pair]
        return result

    def order(
        self,
        base: str,
        quote: str,
        side: str,
        spend_ratio: float = 1,
        test: bool = False,
    ) -> Any:
        """Place a market order.

        Args:
            base: Base currency.
            quote: Quote currency.
            side: 'buy' or 'sell'.
            spend_ratio: Fraction of balance to use.
            test: Validate order without executing.

        Returns:
            Order response.

        Raises:
            Exception: If side is not BUY or SELL.
        """
        pair = self.create_pair(base, quote)
        pair_info = self.get_asset_pair(pair)
        fee = self.get_fee(pair) / 100
        spend_ratio = spend_ratio - fee
        side = side.lower()
        access = "private"
        endpoint = "AddOrder"
        parts = [
            "",
            self.version,
            access,
            endpoint,
        ]
        url = "/".join(parts)

        oflags = ["nompp"]
        balance_label = base
        precision_label = "lot_decimals"

        if side.upper() == C.BUY:
            oflags.append("viqc")
            balance_label = quote
            precision_label = "cost_decimals"
        elif side.upper() != C.SELL:
            raise Exception("Need to specify BUY or SELL side for order")

        balance = self.get_balance()[balance_label]
        amount = spend_ratio * balance
        precision = pair_info[precision_label]
        volume = "{:0.0{}f}".format(amount, precision)

        data = {
            "ordertype": "market",
            "type": side.lower(),
            "pair": pair,
            "oflags": ",".join(oflags),
            "volume": volume,
            "validate": test or self.test,
        }
        response = self.make_auth_req(url, data)
        return response

    def handle_response(self, response: requests.Response) -> Any:
        """Handle API response and check for errors.

        Args:
            response: HTTP response object.

        Returns:
            Result data from response.

        Raises:
            Exception: If response contains errors.
        """
        response = response.json()
        error = response["error"]
        if error:
            raise Exception(error)
        return response["result"]

    def get_order(self, order_id: str) -> dict[str, Any]:
        """Get order details by ID.

        Args:
            order_id: Transaction ID of the order.

        Returns:
            Order data with order_id field added.
        """
        access = "private"
        endpoint = "QueryOrders"
        parts = [
            "",
            self.version,
            access,
            endpoint,
        ]
        url = "/".join(parts)
        data = {"txid": order_id, "trades": True}
        response = self.make_auth_req(url, data)
        order = response[order_id]
        order["order_id"] = order_id
        return order

    def get_trades(self, trade_ids: list[str]) -> list[dict[str, Any]]:
        """Get trade details for multiple trade IDs.

        Args:
            trade_ids: List of trade transaction IDs.

        Returns:
            List of trade data with trade_id field added.
        """
        access = "private"
        endpoint = "QueryTrades"
        parts = [
            "",
            self.version,
            access,
            endpoint,
        ]
        url = "/".join(parts)
        data = {"txid": ",".join(trade_ids), "trades": True}
        response = self.make_auth_req(url, data)
        trades = [
            {**response[trade_id], **{"trade_id": trade_id}} for trade_id in trade_ids
        ]
        return trades

    def standardize_order(
        self, order: dict[str, Any], trades: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Convert Kraken order format to standardized format.

        Args:
            order: Kraken order data.
            trades: List of associated trades.

        Returns:
            Standardized order data compatible with other exchanges.
        """
        std: dict[str, Any] = {}
        std["symbol"] = order["descr"]["pair"]
        std["orderId"] = order["order_id"]
        std["transactTime"] = int((order["closetm"] + order["opentm"]) / 2 * 1000)
        std["price"] = round(float(order["price"]), 10)
        side = order["descr"]["type"].upper()
        origQty = float(order["vol"])
        if side == C.BUY:
            # Buys are submitted with the viqc flag, so Kraken reports vol in the
            # quote currency. Divide by price to recover base quantity. A stricter
            # test is `"viqc" in order["oflags"].split(",")`.
            origQty = round(origQty / std["price"], 10)
        std["origQty"] = origQty
        std["executedQty"] = float(order["vol_exec"])
        std["cummulativeQuoteQty"] = round(std["price"] * std["executedQty"], 10)
        std["status"] = order["status"].upper()
        std["type"] = order["descr"]["ordertype"].upper()
        std["side"] = side

        def standardize_trade(trade: dict[str, Any]) -> dict[str, Any]:
            std_trade: dict[str, Any] = {}
            std_trade["price"] = str(round(float(trade["price"]), 10))
            std_trade["qty"] = trade["vol"]
            std_trade["commission"] = trade["fee"]
            std_trade["tradeId"] = trade["trade_id"]
            return std_trade

        fills = [standardize_trade(trade) for trade in trades]
        std["fills"] = fills
        return std

    def get_test_side(self, base: str, quote: str) -> str:
        """Determine optimal trade side for testing.

        Args:
            base: Base currency.
            quote: Quote currency.

        Returns:
            'buy' or 'sell' based on current balances.
        """
        pair = f"{base}{quote}"
        balances = self.get_balance()
        base_bal = balances[base]
        quote_bal = balances[quote]
        price = self.get_price(pair)
        base_val = base_bal * price
        side = "buy" if quote_bal > base_val else "sell"
        return side

    def get_fee(self, pair: str) -> float:
        """Get trading fee for a pair.

        Args:
            pair: Trading pair symbol.

        Returns:
            Fee as a percentage (e.g., 0.26 for 0.26%).
        """
        access = "private"
        endpoint = "TradeVolume"
        parts = [
            "",
            self.version,
            access,
            endpoint,
        ]
        url = "/".join(parts)
        data = {"pair": pair}
        response = self.make_auth_req(url, data)
        fee = float(response["fees"][pair]["fee"])
        return fee

    def get_ticker(self, pair: str | None = None) -> dict[str, Any]:
        """Get ticker data for a trading pair.

        Args:
            pair: Trading pair symbol. None for all pairs.

        Returns:
            Ticker data including price and volume.
        """
        access = "public"
        endpoint = "Ticker"
        parts = [
            "",
            self.version,
            access,
            endpoint,
        ]
        url = "/".join(parts)
        data = {"pair": pair} if pair else {}
        response = self.make_auth_req(url, data)
        return response

    def get_price(self, pair: str) -> float:
        """Get current price for a trading pair.

        Args:
            pair: Trading pair symbol.

        Returns:
            Current price as float.
        """
        ticker = self.get_ticker(pair)
        price = float(ticker[pair]["c"][0])
        return price


class Binance(CEX):
    """Binance exchange client for cryptocurrency trading.

    Attributes:
        key: API key.
        secret: API secret.
        client: Binance API client instance.
    """

    def __init__(
        self,
        key: str | None = None,
        secret: str | None = None,
        testnet: bool = False,
    ) -> None:
        """Initialize the Binance client.

        Args:
            key: API key. Defaults to BINANCE_KEY env var.
            secret: API secret. Defaults to BINANCE_SECRET env var.
            testnet: Use testnet if True.
        """
        super().__init__()
        self.key = key
        self.secret = secret
        if not key:
            if testnet:
                self.key = os.environ["BINANCE_TESTNET_KEY"]
            else:
                self.key = os.environ["BINANCE_KEY"]
        if not secret:
            if testnet:
                self.secret = os.environ["BINANCE_TESTNET_SECRET"]
            else:
                self.secret = os.environ["BINANCE_SECRET"]
        self.client = Client(self.key, self.secret, testnet=testnet, tld="us")

    def order(
        self,
        base: str,
        quote: str,
        side: str,
        spend_ratio: float = 1,
        test: bool = False,
    ) -> dict[str, Any]:
        """Place a market order.

        Args:
            base: Base currency.
            quote: Quote currency.
            side: 'BUY' or 'SELL'.
            spend_ratio: Fraction of balance to use.
            test: Validate order without executing.

        Returns:
            Order response data.

        Raises:
            Exception: If side is not BUY or SELL.
        """
        # fee is 0.1%, so max spend_ratio is 99.9%
        spend_ratio = spend_ratio - C.BINANCE_FEE
        pair = self.create_pair(base, quote)
        side = side.upper()
        order_type = self.client.ORDER_TYPE_MARKET
        params: dict[str, Any] = {"symbol": pair, "type": order_type}
        symbol_info = self.client.get_symbol_info(pair)
        if symbol_info:
            validated_symbol_info = symbol_info
        else:
            raise Exception(f"Symbol info not found for {pair}")

        if side == C.SELL:
            side = self.client.SIDE_SELL
            balance_label = base
            quantity_label = "quantity"
            filters = validated_symbol_info["filters"]
            for filter in filters:
                if filter["filterType"] == "LOT_SIZE":
                    step_size = float(filter["stepSize"])
        elif side == C.BUY:
            side = self.client.SIDE_BUY
            balance_label = quote
            quantity_label = "quoteOrderQty"
            precision = int(validated_symbol_info["quoteAssetPrecision"])
        else:
            raise Exception("Need to specify BUY or SELL side for order")

        balance = float(self.client.get_asset_balance(balance_label)["free"])
        amount = spend_ratio * balance

        if side == C.BUY:
            quantity = "{:0.0{}f}".format(amount, precision)
        else:
            quantity = round_step_size(amount, step_size)

        params[quantity_label] = quantity

        params["side"] = side
        fx = self.client.create_test_order if test else self.client.create_order

        order = fx(**params)
        return order


# TODO: nightly pipeline. Fetch the most recent data at 9pm EST, predict with the
# current model, write the prediction back to predict.csv, and record successful
# orders in binance.csv.
