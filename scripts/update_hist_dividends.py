"""Update historical stock dividend data from Polygon."""

import os
from multiprocessing import get_context

from hyperdrive import Constants as C
from hyperdrive.Constants import PathFinder
from hyperdrive.DataSource import MarketData, Polygon


def update_poly_dividends(symbols: list[str]) -> None:
    """Update historical dividends with a client owned by this worker."""
    polygon = Polygon()
    for symbol in symbols:
        filename = PathFinder().get_dividends_path(
            symbol=symbol,
            provider=polygon.provider,
        )
        try:
            polygon.save_dividends(symbol=symbol, timeframe="max")
        except Exception as error:
            print(f"Polygon.io dividend update failed for {symbol}.")
            print(error)
        finally:
            if C.CI and os.path.exists(filename):
                os.remove(filename)


def main() -> int:
    """Run the historical dividend worker with spawn-based multiprocessing."""
    symbols = MarketData().get_symbols()[250:]
    context = get_context("spawn")
    process = context.Process(target=update_poly_dividends, args=(symbols,))
    process.start()
    process.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
