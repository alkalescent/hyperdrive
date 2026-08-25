"""Update historical OHLC data from Alpaca."""

import os
from multiprocessing import get_context

from hyperdrive import Constants as C
from hyperdrive.Constants import PathFinder
from hyperdrive.DataSource import AlpacaData, MarketData

TIMEFRAME = "10y"


def update_alpc_ohlc(symbols: list[str]) -> None:
    """Update OHLC data with a client owned by this worker."""
    alpaca = AlpacaData(paper=C.TEST)
    for symbol in symbols:
        filename = PathFinder().get_ohlc_path(
            symbol=symbol,
            provider=alpaca.provider,
        )
        try:
            alpaca.save_ohlc(symbol=symbol, timeframe=TIMEFRAME)
        except Exception as error:
            print(f"Alpaca OHLC update failed for {symbol}.")
            print(error)
        finally:
            if C.CI and os.path.exists(filename):
                os.remove(filename)


def main() -> int:
    """Run the historical OHLC worker with spawn-based multiprocessing."""
    market = MarketData()
    stocks = market.get_symbols()
    ndx = list(market.get_ndx()[C.SYMBOL])
    symbols = sorted(set(stocks).union(ndx))
    context = get_context("spawn")
    process = context.Process(target=update_alpc_ohlc, args=(symbols,))
    process.start()
    process.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
