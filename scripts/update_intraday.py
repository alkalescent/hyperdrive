"""Update recent intraday stock and crypto data from Polygon."""

import os
from multiprocessing import get_context
from typing import Any

from hyperdrive import Constants as C
from hyperdrive.Constants import FEW_DAYS, POLY_CRYPTO_SYMBOLS
from hyperdrive.DataSource import MarketData, Polygon


def update_poly_intraday(symbols: list[str], counter: Any) -> None:
    """Update intraday data with a client owned by this worker."""
    polygon = Polygon(os.environ["POLYGON"])
    for symbol in symbols:
        filenames: list[str] = []
        try:
            filenames = polygon.save_intraday(
                symbol=symbol, timeframe=FEW_DAYS, retries=1
            )
            with counter.get_lock():
                counter.value += 1
        except Exception as error:
            print(f"Polygon.io intraday update failed for {symbol}.")
            print(error)
        finally:
            if C.CI:
                for filename in filenames:
                    if os.path.exists(filename):
                        os.remove(filename)


def main() -> int:
    """Run the intraday worker with spawn-based multiprocessing."""
    symbols = MarketData().get_symbols() + POLY_CRYPTO_SYMBOLS
    context = get_context("spawn")
    counter = context.Value("i", 0)
    process = context.Process(target=update_poly_intraday, args=(symbols, counter))
    process.start()
    process.join()
    if symbols:
        return 0 if counter.value / len(symbols) >= C.SCRIPT_FAILURE_THRESHOLD else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
