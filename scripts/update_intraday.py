import os
from multiprocessing import Process, Value

from hyperdrive import Constants as C
from hyperdrive.Constants import FEW_DAYS, POLY_CRYPTO_SYMBOLS
from hyperdrive.DataSource import Polygon

counter = Value("i", 0)
poly = Polygon(os.environ["POLYGON"])
stock_symbols = poly.get_symbols()
crypto_symbols = POLY_CRYPTO_SYMBOLS
all_symbols = stock_symbols + crypto_symbols


def update_poly_intraday() -> None:
    """Update intraday data from Polygon.io for all symbols."""
    for symbol in all_symbols:
        try:
            filenames = poly.save_intraday(symbol=symbol, timeframe=FEW_DAYS, retries=1)
            with counter.get_lock():
                counter.value += 1
        except Exception as e:
            print(f"Polygon.io intraday update failed for {symbol}.")
            print(e)
        finally:
            if C.CI:
                for filename in filenames:
                    if os.path.exists(filename):
                        os.remove(filename)


p1 = Process(target=update_poly_intraday)
p1.start()
p1.join()

if counter.value / len(all_symbols) < 0.95:
    exit(1)
