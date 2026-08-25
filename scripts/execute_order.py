from datetime import datetime, timedelta

import pandas as pd

from hyperdrive import Constants as C
from hyperdrive.DataSource import MarketData
from hyperdrive.Exchange import Binance, Kraken

test = C.TEST or C.DEV

md = MarketData()
md.provider = "polygon"

signals_path = md.finder.get_signals_path()
orders_path = md.finder.get_orders_path()

signals_df = md.reader.load_csv(signals_path)
last_two_signals = signals_df[C.SIG].tail(2).to_numpy()
num_unique_signals = len(set(last_two_signals))
signal = last_two_signals[-1]
should_order = num_unique_signals > 1
should_order = False  # disable trading

if should_order:
    side = C.BUY if signal else C.SELL
    if C.PREF_EXCHANGE == C.BINANCE:
        # Built here rather than up top because the Binance client pings on
        # construction, and that call is refused from the regions CI runs in.
        bn = Binance(testnet=test)
        base = "BTC"
        quote = "USDT" if test else "USD"
        spend_ratio = C.BINANCE_TEST_SPEND if test else 1

        order = bn.order(base, quote, side, spend_ratio, test)
        order["exchange"] = C.BINANCE
    else:
        kr = Kraken(test=test)
        base = "XXBT"
        quote = "ZUSD"
        spend_ratio = C.KRAKEN_TEST_SPEND if test else 1
        if test:
            side = kr.get_test_side(base, quote)

        order = kr.order(base, quote, side, spend_ratio, test)
        if not test:
            order_id = order["txid"][0]
            order = kr.get_order(order_id)
            trades = kr.get_trades(order["trades"])
            order = kr.standardize_order(order, trades)
        order["exchange"] = C.KRAKEN

    order_df = pd.json_normalize(order)
    # to keep track of multiple orders (from multiple exchanges),
    # order_df = pd.concat(bin_order_df, kr_order_df)
    yesterday = (datetime.utcnow().date() - timedelta(days=1)).strftime(C.DATE_FMT)
    order_df[C.TIME] = [yesterday for _ in range(len(order_df))]

    orders = md.reader.update_df(orders_path, order_df, C.TIME, C.DATE_FMT)
    md.writer.update_csv(orders_path, orders)
