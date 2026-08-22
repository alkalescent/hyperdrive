"""Update historical stock split data from Polygon."""

import os
from multiprocessing import get_context

from hyperdrive import Constants as C
from hyperdrive.Constants import PathFinder
from hyperdrive.DataSource import MarketData, Polygon


def update_poly_splits(symbols: list[str]) -> None:
    """Update historical splits with a client owned by this worker."""
    polygon = Polygon()
    for symbol in symbols:
        filename = PathFinder().get_splits_path(
            symbol=symbol,
            provider=polygon.provider,
        )
        try:
            polygon.save_splits(symbol=symbol, timeframe="max")
        except Exception as error:
            print(f"Polygon.io split update failed for {symbol}.")
            print(error)
        finally:
            if C.CI and os.path.exists(filename):
                os.remove(filename)


def main() -> int:
    """Run the historical split worker with spawn-based multiprocessing."""
    symbols = MarketData().get_symbols()[250:]
    context = get_context("spawn")
    process = context.Process(target=update_poly_splits, args=(symbols,))
    process.start()
    process.join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
