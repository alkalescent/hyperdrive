import os
from multiprocessing import Process

from hyperdrive import Constants as C
from hyperdrive.Constants import PathFinder
from hyperdrive.DataSource import AlpacaData, Polygon

alpc = AlpacaData(paper=C.TEST)
poly = Polygon(os.environ["POLYGON"])
stock_symbols = poly.get_symbols()
poly_symbols = stock_symbols + C.POLY_CRYPTO_SYMBOLS
alpc_symbols = set(alpc.get_ndx()[C.SYMBOL]).union(stock_symbols)
timeframe = "10y"

# Double redundancy
# 1st pass


# def update_poly_ohlc():
#     for symbol in poly_symbols:
#         filename = PathFinder().get_ohlc_path(
#             symbol=symbol, provider=poly.provider)
#         try:
#             poly.save_ohlc(symbol=symbol, timeframe=timeframe)
#         except Exception as e:
#             print(f'Polygon.io OHLC update failed for {symbol}.')
#             print(e)
#         finally:
#             if C.CI and os.path.exists(filename):
#                 os.remove(filename)

# 2nd pass


def update_alpc_ohlc():
    for symbol in alpc_symbols:
        filename = PathFinder().get_ohlc_path(symbol=symbol, provider=alpc.provider)
        try:
            alpc.save_ohlc(symbol=symbol, timeframe=timeframe)
        except Exception as e:
            print(f"Alpaca OHLC update failed for {symbol}.")
            print(e)
        finally:
            if C.CI and os.path.exists(filename):
                os.remove(filename)


if __name__ == "__main__":
    # p1 = Process(target=update_poly_ohlc)
    p2 = Process(target=update_alpc_ohlc)
    # p1.start()
    p2.start()
    # p1.join()
    p2.join()
