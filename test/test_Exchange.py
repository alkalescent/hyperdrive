import sys
import pytest
from collections import OrderedDict
sys.path.append('hyperdrive')
from Exchange import Binance, Kraken, AlpacaEx  # noqa autopep8
import Constants as C  # noqa


bn = Binance(testnet=True)
kr = Kraken(test=True)
alpc = AlpacaEx(paper=True)


class TestAlpacaEx:
    def test_init(self):
        assert isinstance(alpc, AlpacaEx)
        assert hasattr(alpc, 'base')
        assert alpc.base == 'https://paper-api.alpaca.markets'
        assert hasattr(alpc, 'version')
        assert hasattr(alpc, 'token')
        assert hasattr(alpc, 'secret')

    def test_fill_orders(self):
        positions = alpc.get_positions()
        if any([position['symbol'] == 'LTC/USD' for position in positions]):
            orders = alpc.fill_orders(['LTC/USD'], alpc.close_position)
        else:
            orders = alpc.fill_orders(
                ['LTC/USD'], alpc.create_order, side='buy', notional=10)

        for order in orders:
            assert 'id' in order

    def test_make_request(self):
        acct = alpc.make_request('GET', 'account')
        assert acct['status'] == 'ACTIVE'

        with pytest.raises(Exception):
            alpc.make_request('GET', 'not_a_real_route')

    def test_get_positions(self):
        positions = alpc.get_positions()
        assert all('symbol' in position for position in positions)

    def test_close_position(self):
        positions = alpc.get_positions()
        if any([position['symbol'] == 'LTC/USD' for position in positions]):
            order = alpc.close_position('LTC/USD')
            assert 'id' in order

    def test_get_order(self):
        with pytest.raises(Exception):
            alpc.get_order('not_a_real_id')

    def test_get_account(self):
        acct = alpc.get_account()
        assert acct['status'] == 'ACTIVE'

    def test_create_order(self):
        positions = alpc.get_positions()
        side = 'buy'
        if 'LTC/USD' in [position['symbol'] for position in positions]:
            side = 'sell'
        order = alpc.create_order('LTC/USD', side, 10)
        assert 'id' in order


class TestBinance:
    def test_init(self):
        assert type(bn).__name__ == 'Binance'
        assert hasattr(bn, 'key')
        assert hasattr(bn, 'secret')
        assert hasattr(bn, 'client')

    def test_order(self):
        # https://testnet.binance.vision/
        base = 'BTC'
        quote = 'USDT'
        bn.order(base, quote, 'buy', C.BINANCE_TEST_SPEND, test=True)
        bn.order(base, quote, 'sell', 1, test=True)

    # selling btc response
    # {'symbol': 'BTCUSD', 'orderId': 664894061, 'orderListId': -1,
    # 'clientOrderId': 'EACZgyd3kO4r28V2Che5x9', 'transactTime': 1634612257816,
    # 'price': '0.0000', 'origQty': '0.00080000', 'executedQty': '0.00080000',
    # 'cummulativeQuoteQty': '49.4641', 'status': 'FILLED', 'timeInForce':
    # 'GTC', 'type': 'MARKET', 'side': 'SELL', 'fills': [{'price':
    # '61830.1400', 'qty': '0.00080000', 'commission': '0.0500',
    # 'commissionAsset': 'USD', 'tradeId': 24328534}]}

    # buying btc response
    # {'symbol': 'BTCUSD', 'orderId': 664895034, 'orderListId': -1,
    # 'clientOrderId': 'S3ALGacJPWtYZ8IKLnTAXE', 'transactTime': 1634612303994,
    # 'price': '0.0000', 'origQty': '0.00079900', 'executedQty': '0.00079900',
    # 'cummulativeQuoteQty': '49.3823', 'status': 'FILLED', 'timeInForce':
    # 'GTC', 'type': 'MARKET', 'side': 'BUY', 'fills': [{'price':
    # '61805.2400', 'qty': '0.00079900', 'commission': '0.00000080',
    # 'commissionAsset': 'BTC', 'tradeId': 24328549}]}

    # symbol_info response
    # {'baseAsset': 'BTC',
    #  'baseAssetPrecision': 8,
    #  'baseCommissionPrecision': 8,
    #  'filters': [{'filterType': 'PRICE_FILTER',
    #               'maxPrice': '100000.0000',
    #               'minPrice': '0.0100',
    #               'tickSize': '0.0100'},
    #              {'avgPriceMins': 5,
    #               'filterType': 'PERCENT_PRICE',
    #               'multiplierDown': '0.2',
    #               'multiplierUp': '5'},
    #              {'filterType': 'LOT_SIZE',
    #               'maxQty': '9000.00000000',
    #               'minQty': '0.00000100',
    #               'stepSize': '0.00000100'},
    #              {'applyToMarket': True,
    #               'avgPriceMins': 5,
    #               'filterType': 'MIN_NOTIONAL',
    #               'minNotional': '10.0000'},
    #              {'filterType': 'ICEBERG_PARTS', 'limit': 10},
    #              {'filterType': 'MARKET_LOT_SIZE',
    #               'maxQty': '3200.00000000',
    #               'minQty': '0.00000000',
    #               'stepSize': '0.00000000'},
    #              {'filterType': 'MAX_NUM_ORDERS', 'maxNumOrders': 200},
    #              {'filterType': 'MAX_NUM_ALGO_ORDERS', 'maxNumAlgoOrders': 5}
    # ],
    #  'icebergAllowed': True,
    #  'isMarginTradingAllowed': False,
    #  'isSpotTradingAllowed': True,
    #  'ocoAllowed': True,
    #  'orderTypes': ['LIMIT',
    #                 'LIMIT_MAKER',
    #                 'MARKET',
    #                 'STOP_LOSS_LIMIT',
    #                 'TAKE_PROFIT_LIMIT'],
    #  'permissions': ['SPOT'],
    #  'quoteAsset': 'USD',
    #  'quoteAssetPrecision': 4,
    #  'quoteCommissionPrecision': 2,
    #  'quoteOrderQtyMarketAllowed': True,
    #  'quotePrecision': 4,
    #  'status': 'TRADING',
    #  'symbol': 'BTCUSD'}


class TestKraken:
    def test_init(self):
        assert type(kr).__name__ == 'Kraken'
        assert hasattr(kr, 'key')
        assert hasattr(kr, 'secret')
        assert hasattr(kr, 'version')
        assert hasattr(kr, 'api_url')

    def test_order(self):
        base = 'XXBT'
        quote = 'ZUSD'
        side = kr.get_test_side(base, quote)
        try:
            kr.order(base, quote, side, C.KRAKEN_TEST_SPEND, test=True)
        except Exception as e:
            # if Kraken balance is low/zero, then tests may fail
            exception_name = e.__str__()
            vol_error = "['EGeneral:Invalid arguments:volume minimum not met']"
            if not (exception_name == vol_error):
                raise e

    def test_standardize_order(self):
        order = kr.get_order('OD74VW-UPIQ7-A47XCN')
        trades = kr.get_trades(order['trades'])
        std_order = kr.standardize_order(order, trades)
        expected = OrderedDict([('symbol', 'USDCUSD'),
                                ('orderId', 'OD74VW-UPIQ7-A47XCN'),
                                ('transactTime', 1671356188514),
                                ('price', 0.9999),
                                ('origQty', 5.41394641),
                                ('executedQty', 5.41394641),
                                ('cummulativeQuoteQty', 5.4134050154),
                                ('status', 'CLOSED'),
                                ('type', 'MARKET'),
                                ('side', 'SELL'),
                                ('fills',
                                    [OrderedDict([('price', '0.9999'),
                                                  ('qty', '5.41394641'),
                                                  ('commission', '0.01082681'),
                                                  ('tradeId', 'TZX2YO-WCZN5-6GIH3E')])])])
        assert std_order == expected


# pprint(kr.get_trade('TZX2YO-WCZN5-6GIH3E'))

# {
#     'cost': '5.41340502',
#     'fee': '0.01082681',
#     'margin': '0.00000000',
#     'misc': '',
#     'ordertxid': 'OD74VW-UPIQ7-A47XCN',
#     'ordertype': 'market',
#     'pair': 'USDCUSD',
#     'postxid': 'TKH2SE-M7IF5-CFI7LT',
#     'price': '0.99990000',
#     'time': 1671356188.5147705,
#     'type': 'sell',
#     'vol': '5.41394641'
# }


# pprint(kr.get_order('OD74VW-UPIQ7-A47XCN'))
# w trades
# {
#     'closetm': 1671356188.5147808,
#     'cost': '5.41340502',
#     'descr': {
#         'close': '',
#         'leverage': 'none',
#         'order': 'sell 5.41394641 USDCUSD @ market',
#         'ordertype': 'market',
#         'pair': 'USDCUSD',
#         'price': '0',
#         'price2': '0',
#         'type': 'sell'
#     },
#     'expiretm': 0,
#     'fee': '0.01082681',
#     'limitprice': '0.00000000',
#     'misc': '',
#     'oflags': 'fciq,nompp',
#     'opentm': 1671356188.5141125,
#     'price': '0.9999',
#     'reason': None,
#     'refid': None,
#     'starttm': 0,
#     'status': 'closed',
#     'stopprice': '0.00000000',
#     'trades': ['TZX2YO-WCZN5-6GIH3E'],
#     'userref': 0,
#     'vol': '5.41394641',
#     'vol_exec': '5.41394641'
# }

# pprint(kr.order('USDC', 'USD', 'sell', spend_ratio=0.00017, test=False))

# {
#     'descr': {'order': 'sell 5.41394641 USDCUSD @ market'},
#     'txid': ['OD74VW-UPIQ7-A47XCN']
# }

# pprint(kr.get_balance())

# {'BCH': '0.0000000000',
#  'ETH2': '9.6955774510',
#  'ETH2.S': '100.6050600000',
#  'ETHW': '0.0000035',
#  'NANO': '0.0000000000',
#  'USDC': '31846.74358400',
#  'XETH': '0.4304932490',
#  'XLTC': '0.0000075300',
#  'XXBT': '-0.0000000010',
#  'XXMR': '0.0000041900',
#  'ZUSD': '0.0001'}

# pprint(kr.get_asset_pair('XXBTZUSD'))

# {'aclass_base': 'currency',
#  'aclass_quote': 'currency',
#  'altname': 'XBTUSD',
#  'base': 'XXBT',
#  'cost_decimals': 5,
#  'costmin': '0.5',
#  'fee_volume_currency': 'ZUSD',
#  'fees': [[0, 0.26],
#           [50000, 0.24],
#           [100000, 0.22],
#           [250000, 0.2],
#           [500000, 0.18],
#           [1000000, 0.16],
#           [2500000, 0.14],
#           [5000000, 0.12],
#           [10000000, 0.1],
#           [100000000, 0.08]],
#  'fees_maker': [[0, 0.16],
#                 [50000, 0.14],
#                 [100000, 0.12],
#                 [250000, 0.1],
#                 [500000, 0.08],
#                 [1000000, 0.06],
#                 [2500000, 0.04],
#                 [5000000, 0.02],
#                 [10000000, 0.0],
#                 [100000000, 0.0]],
#  'leverage_buy': [2, 3, 4, 5],
#  'leverage_sell': [2, 3, 4, 5],
#  'long_position_limit': 270,
#  'lot': 'unit',
#  'lot_decimals': 8,
#  'lot_multiplier': 1,
#  'margin_call': 80,
#  'margin_stop': 40,
#  'ordermin': '0.0001',
#  'pair_decimals': 1,
#  'quote': 'ZUSD',
#  'short_position_limit': 180,
#  'status': 'online',
#  'tick_size': '0.1',
#  'wsname': 'XBT/USD'}
