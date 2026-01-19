import os
from datetime import datetime
from time import sleep

from hyperdrive.Constants import CI, POLY_CRYPTO_SYMBOLS, TIME_FMT
from hyperdrive.DataSource import Polygon

poly = Polygon(os.environ["POLYGON"])
stock_symbols = poly.get_symbols()
crypto_symbols = POLY_CRYPTO_SYMBOLS
all_symbols = stock_symbols + crypto_symbols


def update_poly_intraday():
    for symbol in all_symbols:
        now = datetime.now()
        hour = now.hour
        while hour in set(range(8, 12)):
            print(datetime.now().strftime(TIME_FMT))
            print("Sleeping for 1 hr")
            sleep(3600)
            hour = datetime.now().hour
        filenames = []
        try:
            filenames = poly.save_intraday(symbol=symbol, timeframe="30d", retries=1)
        except Exception as e:
            print(f"Polygon.io intraday update failed for {symbol}.")
            print(e)
        finally:
            if CI:
                for filename in filenames:
                    if os.path.exists(filename):
                        os.remove(filename)


update_poly_intraday()
