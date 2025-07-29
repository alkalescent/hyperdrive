import os
import sys
from multiprocessing import Process, Value
sys.path.append('hyperdrive')
from DataSource import Polygon, AlpacaData  # noqa autopep8
from Constants import PathFinder  # noqa autopep8
import Constants as C  # noqa autopep8

counter = Value('i', 0)
alpc = AlpacaData(paper=C.TEST)
poly = Polygon(os.environ['POLYGON'])
stock_symbols = poly.get_symbols()
poly_symbols = stock_symbols + C.POLY_CRYPTO_SYMBOLS
alpc_symbols = set(alpc.get_ndx()[C.SYMBOL]).union(stock_symbols)


def update_poly_ohlc():
    for symbol in poly_symbols:
        try:
            if not C.TEST:
                filename = poly.save_ohlc(
                    symbol=symbol, timeframe=C.FEW_DAYS, retries=1)
            with counter.get_lock():
                counter.value += 1
        except Exception as e:
            print(f'Polygon.io OHLC update failed for {symbol}.')
            print(e)
        finally:
            filename = PathFinder().get_ohlc_path(
                symbol=symbol, provider=poly.provider)
            if C.CI and os.path.exists(filename):
                os.remove(filename)


def update_alpc_ohlc():
    for symbol in alpc_symbols:
        try:
            filename = alpc.save_ohlc(
                symbol=symbol, timeframe=C.FEW_DAYS, retries=1)
            with counter.get_lock():
                counter.value += 1
        except Exception as e:
            print(f'Alpaca OHLC update failed for {symbol}.')
            print(e)
        finally:
            filename = PathFinder().get_ohlc_path(
                symbol=symbol, provider=alpc.provider)
            if C.CI and os.path.exists(filename):
                os.remove(filename)


if __name__ == "__main__":
    p1 = Process(target=update_poly_ohlc)
    p2 = Process(target=update_alpc_ohlc)
    p1.start()
    p2.start()
    p1.join()
    p2.join()

    if counter.value / (len(poly_symbols) + len(alpc_symbols)) < 0.95:
        exit(1)
