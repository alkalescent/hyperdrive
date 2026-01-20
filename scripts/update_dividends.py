import os
from multiprocessing import Process, Value

from hyperdrive import Constants as C
from hyperdrive.Constants import PathFinder
from hyperdrive.DataSource import Polygon

counter = Value("i", 0)
poly = Polygon()
symbols = poly.get_symbols()


def update_poly_dividends() -> None:
    """Update dividend data from Polygon.io for all symbols."""
    for symbol in symbols:
        try:
            filename = poly.save_dividends(
                symbol=symbol,
                timeframe="3m",
                retries=1 if C.TEST else C.DEFAULT_RETRIES,
            )
            with counter.get_lock():
                counter.value += 1
        except Exception as e:
            print(f"Polygon.io dividend update failed for {symbol}.")
            print(e)
        finally:
            filename = PathFinder().get_dividends_path(
                symbol=symbol, provider=poly.provider
            )
            if C.CI and os.path.exists(filename):
                os.remove(filename)


p1 = Process(target=update_poly_dividends)
p1.start()
p1.join()

if counter.value / len(symbols) < 0.05:
    exit(1)
