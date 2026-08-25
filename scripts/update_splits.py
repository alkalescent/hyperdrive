"""Update recent stock split data from Polygon."""

import os
from multiprocessing import get_context
from typing import Any

from hyperdrive import Constants as C
from hyperdrive.Constants import PathFinder
from hyperdrive.DataSource import MarketData, Polygon


def update_poly_splits(symbols: list[str], counter: Any) -> None:
    """Update split data with a client owned by this worker."""
    polygon = Polygon()
    for symbol in symbols:
        try:
            polygon.save_splits(
                symbol=symbol,
                timeframe="3m",
                retries=1 if C.TEST else C.DEFAULT_RETRIES,
            )
            with counter.get_lock():
                counter.value += 1
        except Exception as error:
            print(f"Polygon.io split update failed for {symbol}.")
            print(error)
        finally:
            filename = PathFinder().get_splits_path(
                symbol=symbol, provider=polygon.provider
            )
            if C.CI and os.path.exists(filename):
                os.remove(filename)


def main() -> int:
    """Run the split worker with spawn-based multiprocessing."""
    symbols = MarketData().get_symbols()
    context = get_context("spawn")
    counter = context.Value("i", 0)
    process = context.Process(target=update_poly_splits, args=(symbols, counter))
    process.start()
    process.join()
    if symbols:
        return 0 if counter.value / len(symbols) >= 0.05 else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
