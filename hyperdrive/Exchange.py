import os
import time
import hmac
import base64
import hashlib
import requests
import urllib.parse
from time import sleep
from binance import Client
from typing import Iterable, Union, Optional
from binance.helpers import round_step_size
from dotenv import load_dotenv, find_dotenv
import Constants as C
load_dotenv(find_dotenv('config.env'))


class CEX:
    def create_pair(self, base: str, quote: str) -> str:
        return f'{base}{quote}'


class AlpacaEx(CEX):
    def __init__(
            self,
            token: Optional[str] = os.environ.get('ALPACA'),
            secret: Optional[str] = os.environ.get('ALPACA_SECRET'),
            paper: bool = False
    ) -> None:
        super().__init__()
        self.base = (f'https://{"paper-" if paper or C.TEST else ""}'
                     'api.alpaca.markets')
        self.version = 'v2'
        self.token = os.environ.get(
            'ALPACA_PAPER') if paper or C.TEST else token
        self.secret = os.environ.get(
            'ALPACA_PAPER_SECRET') if paper or C.TEST else secret
        if not (self.token and self.secret):
            raise Exception('missing Alpaca credentials')

    def fill_orders(
            self,
            symbols: Iterable[str],
            func: callable,
            **kwargs: dict[str, any]
    ) -> list[dict[str, any]]:
        pending_orders = set()
        completed_orders = []
        for symbol in symbols:
            order = func(symbol, **kwargs)
            if order['status'] == 'filled':
                completed_orders.append(order)
            else:
                pending_orders.add(order['id'])
        while pending_orders:
            for id in list(pending_orders):
                order = self.get_order(id)
                if order['status'] == 'filled':
                    completed_orders.append(order)
                    pending_orders.discard(id)
            sleep(1)
        return completed_orders

    def make_request(
            self,
            method: str,
            route: str,
            payload: Optional[dict[str, any]] = {}
    ) -> any:
        parts = [self.base, self.version, route]
        url = '/'.join(parts)
        headers = {
            "accept": "application/json",
            "APCA-API-KEY-ID": self.token,
            "APCA-API-SECRET-KEY": self.secret
        }
        response = requests.request(method, url, json=payload, headers=headers)
        if response.ok:
            return response.json()
        else:
            raise Exception(response.text)

    def get_positions(self) -> any:
        return self.make_request('GET', 'positions')

    def close_position(self, symbol: str) -> any:
        return self.make_request('DELETE', f'positions/{symbol}')

    def get_order(self, id: str) -> any:
        return self.make_request('GET', f'orders/{id}')

    def get_account(self) -> any:
        return self.make_request('GET', 'account')

    def create_order(
            self,
            symbol: str,
            side: str,
            notional: Union[int, float, str]
    ) -> any:
        payload = {
            'symbol': symbol,
            'side': side.lower(),
            'type': 'market',
            'notional': str(notional),
            'time_in_force': (
                'gtc' if symbol in C.ALPC_CRYPTO_SYMBOLS else 'day'
            )
        }
        return self.make_request('POST', 'orders', payload)


class Kraken(CEX):
    def __init__(self, key=None, secret=None, test=False):
        super().__init__()
        self.key = key
        self.secret = secret
        self.test = test
        if not key:
            self.key = os.environ['KRAKEN_KEY']
        if not secret:
            self.secret = os.environ['KRAKEN_SECRET']
        self.api_url = 'https://api.kraken.com'
        self.version = '0'

    def get_signature(self, urlpath, data):
        postdata = urllib.parse.urlencode(data)
        encoded = (str(data['nonce']) + postdata).encode()
        message = urlpath.encode() + hashlib.sha256(encoded).digest()

        mac = hmac.new(base64.b64decode(self.secret), message, hashlib.sha512)
        sigdigest = base64.b64encode(mac.digest())
        return sigdigest.decode()

    def make_auth_req(self, uri_path, data={}):
        data['nonce'] = self.gen_nonce()
        headers = {}
        headers['API-Key'] = self.key
        # get_kraken_signature() as defined in the 'Authentication' section
        headers['API-Sign'] = self.get_signature(uri_path, data)
        response = requests.post(
            (self.api_url + uri_path),
            headers=headers,
            data=data
        )
        return self.handle_response(response)

    def gen_nonce(self):
        return str(int(1000 * time.time()))

    def get_balance(self):
        access = 'private'
        endpoint = 'Balance'
        parts = [
            '',
            self.version,
            access,
            endpoint,
        ]
        url = '/'.join(parts)
        response = self.make_auth_req(url)
        for asset in response:
            response[asset] = float(response[asset])
        return response

    def get_asset_pair(self, pair):
        access = 'public'
        endpoint = 'AssetPairs'
        parts = [
            self.api_url,
            self.version,
            access,
            endpoint,
        ]
        url = '/'.join(parts)
        params = {
            'pair': pair
        }
        response = requests.get(url, params=params)
        result = self.handle_response(response)[pair]
        return result

    def order(self, base, quote, side, spend_ratio=1, test=False):
        pair = self.create_pair(base, quote)
        pair_info = self.get_asset_pair(pair)
        fee = self.get_fee(pair) / 100
        spend_ratio = spend_ratio - fee
        side = side.lower()
        access = 'private'
        endpoint = 'AddOrder'
        parts = [
            '',
            self.version,
            access,
            endpoint,
        ]
        url = '/'.join(parts)

        oflags = ['nompp']
        balance_label = base
        precision_label = 'lot_decimals'

        if side.upper() == C.BUY:
            oflags.append('viqc')
            balance_label = quote
            precision_label = 'cost_decimals'
        elif side.upper() != C.SELL:
            raise Exception('Need to specify BUY or SELL side for order')

        balance = self.get_balance()[balance_label]
        amount = spend_ratio * balance
        precision = pair_info[precision_label]
        volume = "{:0.0{}f}".format(amount, precision)

        data = {
            'ordertype': 'market',
            'type': side.lower(),
            'pair': pair,
            'oflags': ','.join(oflags),
            'volume': volume,
            'validate': test or self.test
        }
        response = self.make_auth_req(url, data)
        return response

    def handle_response(self, response):
        response = response.json()
        error = response['error']
        if error:
            raise Exception(error)
        return response['result']

    def get_order(self, order_id):
        access = 'private'
        endpoint = 'QueryOrders'
        parts = [
            '',
            self.version,
            access,
            endpoint,
        ]
        url = '/'.join(parts)
        data = {
            'txid': order_id,
            'trades': True
        }
        response = self.make_auth_req(url, data)
        order = response[order_id]
        order['order_id'] = order_id
        return order

    def get_trades(self, trade_ids):
        access = 'private'
        endpoint = 'QueryTrades'
        parts = [
            '',
            self.version,
            access,
            endpoint,
        ]
        url = '/'.join(parts)
        data = {
            'txid': ','.join(trade_ids),
            'trades': True
        }
        response = self.make_auth_req(url, data)
        trades = [
            {
                **response[trade_id],
                **{'trade_id': trade_id}
            }
            for trade_id in trade_ids
        ]
        return trades

    def standardize_order(self, order, trades):
        std = {}
        std['symbol'] = order['descr']['pair']
        std['orderId'] = order['order_id']
        std['transactTime'] = int(
            (order['closetm'] + order['opentm']) / 2 * 1000)
        std['price'] = round(float(order['price']), 10)
        side = order['descr']['type'].upper()
        origQty = float(order['vol'])
        if side == C.BUY:
            # other test would be [if 'viqc' in order['oflags'].split(','):]
            origQty = round(origQty / std['price'], 10)
        std['origQty'] = origQty
        std['executedQty'] = float(order['vol_exec'])
        std['cummulativeQuoteQty'] = round(
            std['price'] * std['executedQty'], 10)
        std['status'] = order['status'].upper()
        std['type'] = order['descr']['ordertype'].upper()
        std['side'] = side

        def standardize_trade(trade):
            std_trade = {}
            std_trade['price'] = str(round(float(trade['price']), 10))
            std_trade['qty'] = trade['vol']
            std_trade['commission'] = trade['fee']
            std_trade['tradeId'] = trade['trade_id']
            return std_trade
        fills = [standardize_trade(trade) for trade in trades]
        std['fills'] = fills
        return std

    def get_test_side(self, base, quote):
        pair = f'{base}{quote}'
        balances = self.get_balance()
        base_bal = balances[base]
        quote_bal = balances[quote]
        price = self.get_price(pair)
        base_val = base_bal * price
        side = 'buy' if quote_bal > base_val else 'sell'
        return side

    def get_fee(self, pair):
        access = 'private'
        endpoint = 'TradeVolume'
        parts = [
            '',
            self.version,
            access,
            endpoint,
        ]
        url = '/'.join(parts)
        data = {
            "pair": pair
        }
        response = self.make_auth_req(url, data)
        fee = float(response['fees'][pair]['fee'])
        return fee

    def get_ticker(self, pair=None):
        access = 'public'
        endpoint = 'Ticker'
        parts = [
            '',
            self.version,
            access,
            endpoint,
        ]
        url = '/'.join(parts)
        data = {
            "pair": pair
        } if pair else {}
        response = self.make_auth_req(url, data)
        return response

    def get_price(self, pair):
        ticker = self.get_ticker(pair)
        price = float(ticker[pair]['c'][0])
        return price


class Binance(CEX):
    def __init__(self, key=None, secret=None, testnet=False):
        super().__init__()
        self.key = key
        self.secret = secret
        if not key:
            if testnet:
                self.key = os.environ['BINANCE_TESTNET_KEY']
            else:
                self.key = os.environ['BINANCE_KEY']
        if not secret:
            if testnet:
                self.secret = os.environ['BINANCE_TESTNET_SECRET']
            else:
                self.secret = os.environ['BINANCE_SECRET']
        self.client = Client(self.key, self.secret, testnet=testnet, tld='us')

    def order(self, base, quote, side, spend_ratio=1, test=False):
        # fee is 0.1%, so max spend_ratio is 99.9%
        spend_ratio = spend_ratio - C.BINANCE_FEE
        pair = self.create_pair(base, quote)
        side = side.upper()
        order_type = self.client.ORDER_TYPE_MARKET
        params = {'symbol': pair, 'type': order_type}
        symbol_info = self.client.get_symbol_info(pair)

        if side == C.SELL:
            side = self.client.SIDE_SELL
            balance_label = base
            quantity_label = 'quantity'
            filters = symbol_info['filters']
            for filter in filters:
                if filter['filterType'] == 'LOT_SIZE':
                    step_size = float(filter['stepSize'])
        elif side == C.BUY:
            side = self.client.SIDE_BUY
            balance_label = quote
            quantity_label = 'quoteOrderQty'
            precision = int(symbol_info['quoteAssetPrecision'])
        else:
            raise Exception('Need to specify BUY or SELL side for order')

        balance = float(self.client.get_asset_balance(balance_label)['free'])
        amount = spend_ratio * balance

        if side == C.BUY:
            quantity = "{:0.0{}f}".format(amount, precision)
        else:
            quantity = round_step_size(amount, step_size)

        params[quantity_label] = quantity

        params['side'] = side
        fx = (
            self.client.create_test_order
            if test else self.client.create_order
        )

        order = fx(**params)
        return order

# write script that gets most recent data at 9pm est
# predicts using model
# writes that back to predict.csv
# write successful orders to binance.csv
