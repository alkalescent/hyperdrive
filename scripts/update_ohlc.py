"""Update OHLC price data from Polygon and Alpaca APIs."""

import os
from multiprocessing import get_context
from time import monotonic
from typing import Any

from hyperdrive import Constants as C
from hyperdrive.Constants import PathFinder
from hyperdrive.DataSource import AlpacaData, Indices, MarketData, Polygon

DEFAULT_WORKER_TIMEOUT_SECONDS = 60 * 60


def _limit_symbols(symbols: list[str], env_name: str) -> list[str]:
    """Return sorted unique symbols, optionally limited by an environment value."""
    ordered = sorted(set(symbols))
    raw_limit = os.environ.get(env_name)
    if raw_limit:
        try:
            limit = int(raw_limit)
        except ValueError as error:
            raise ValueError(f"{env_name} must be a positive integer") from error
        if limit < 1:
            raise ValueError(f"{env_name} must be a positive integer")
        return ordered[:limit]
    return ordered


def _worker_timeout() -> int:
    """Return the maximum number of seconds allowed for all workers."""
    raw_timeout = os.environ.get(
        "OHLC_WORKER_TIMEOUT_SECONDS", str(DEFAULT_WORKER_TIMEOUT_SECONDS)
    )
    try:
        timeout = int(raw_timeout)
    except ValueError as error:
        raise ValueError(
            "OHLC_WORKER_TIMEOUT_SECONDS must be a positive integer"
        ) from error
    if timeout < 1:
        raise ValueError("OHLC_WORKER_TIMEOUT_SECONDS must be a positive integer")
    return timeout


def _cleanup_local(symbol: str, provider: str) -> None:
    """Remove a downloaded data file after a CI update."""
    filename = PathFinder().get_ohlc_path(symbol=symbol, provider=provider)
    if C.CI and os.path.exists(filename):
        os.remove(filename)


def _update_symbol(
    source: MarketData,
    api_symbol: str,
    storage_symbol: str,
    index: int,
    total: int,
    counter: Any,
) -> None:
    """Update one symbol and report its result."""
    label = f"[{source.provider} {index}/{total}] {api_symbol}"
    started = monotonic()
    print(f"{label}: starting", flush=True)
    try:
        source.save_ohlc(
            symbol=api_symbol,
            timeframe=C.FEW_DAYS,
            retries=1,
        )
        with counter.get_lock():
            counter.value += 1
        elapsed = monotonic() - started
        print(f"{label}: completed in {elapsed:.1f}s", flush=True)
    except Exception as error:
        elapsed = monotonic() - started
        print(f"{label}: failed after {elapsed:.1f}s: {error}", flush=True)
    finally:
        _cleanup_local(storage_symbol, source.provider)


def update_poly_ohlc(symbols: list[str], counter: Any) -> None:
    """Update Polygon OHLC data using a client created inside the worker."""
    polygon = Polygon(os.environ["POLYGON"])
    total = len(symbols)
    for index, symbol in enumerate(symbols, start=1):
        _update_symbol(polygon, symbol, symbol, index, total, counter)


def update_alpc_ohlc(
    stock_symbols: list[str], crypto_symbols: list[str], counter: Any
) -> None:
    """Update Alpaca stock and crypto OHLC data inside the worker."""
    alpaca = AlpacaData(paper=C.TEST)
    symbol_pairs = [(symbol, symbol) for symbol in stock_symbols]
    symbol_pairs.extend(
        (symbol, C.ALPC_TO_POLY_CRYPTO.get(symbol, symbol)) for symbol in crypto_symbols
    )
    total = len(symbol_pairs)
    for index, (api_symbol, storage_symbol) in enumerate(symbol_pairs, start=1):
        _update_symbol(alpaca, api_symbol, storage_symbol, index, total, counter)


def _load_symbol_scope() -> tuple[list[str], list[str], list[str]]:
    """Load deterministic Polygon, Alpaca stock, and Alpaca crypto scopes."""
    stocks = _limit_symbols(MarketData().get_symbols(), "OHLC_STOCK_LIMIT")
    ndx = list(Indices().get_ndx()[C.SYMBOL])
    alpaca_stocks = _limit_symbols(list(set(stocks).union(ndx)), "OHLC_STOCK_LIMIT")
    polygon_crypto = _limit_symbols(C.POLY_CRYPTO_SYMBOLS, "OHLC_CRYPTO_LIMIT")
    alpaca_crypto = _limit_symbols(C.ALPC_CRYPTO_SYMBOLS, "OHLC_CRYPTO_LIMIT")
    return stocks + polygon_crypto, alpaca_stocks, alpaca_crypto


def _wait_for_processes(processes: list[Any], timeout: int) -> bool:
    """Wait for all workers within one shared deadline and terminate stalls."""
    deadline = monotonic() + timeout
    for process in processes:
        process.join(max(0.0, deadline - monotonic()))

    timed_out = [process for process in processes if process.is_alive()]
    if timed_out:
        names = ", ".join(process.name for process in timed_out)
        print(f"OHLC worker timeout after {timeout}s: {names}", flush=True)
        for process in timed_out:
            process.terminate()
        for process in timed_out:
            process.join(5)
        return False

    failed = [process for process in processes if process.exitcode != 0]
    if failed:
        failures = ", ".join(f"{process.name}={process.exitcode}" for process in failed)
        print(f"OHLC workers exited unsuccessfully: {failures}", flush=True)
        return False
    return True


def main() -> int:
    """Run the configured OHLC update and return a process exit code."""
    polygon_symbols, alpaca_stocks, alpaca_crypto = _load_symbol_scope()
    # Spawn prevents inherited boto3 and HTTP session state from deadlocking workers.
    context = get_context("spawn")
    counter = context.Value("i", 0)
    processes = [
        context.Process(
            name="alpaca",
            target=update_alpc_ohlc,
            args=(alpaca_stocks, alpaca_crypto, counter),
        )
    ]
    total_symbols = len(alpaca_stocks) + len(alpaca_crypto)

    if C.TEST:
        print("TEST=true: Polygon requests are excluded from this run", flush=True)
    else:
        processes.append(
            context.Process(
                name="polygon",
                target=update_poly_ohlc,
                args=(polygon_symbols, counter),
            )
        )
        total_symbols += len(polygon_symbols)

    print(
        "OHLC scope: "
        f"polygon={0 if C.TEST else len(polygon_symbols)}, "
        f"alpaca_stocks={len(alpaca_stocks)}, "
        f"alpaca_crypto={len(alpaca_crypto)}",
        flush=True,
    )
    for process in processes:
        process.start()

    workers_succeeded = _wait_for_processes(processes, _worker_timeout())
    if workers_succeeded:
        if total_symbols == 0:
            print("OHLC update has no configured symbols", flush=True)
            return 1

        success_rate = counter.value / total_symbols
        print(
            f"OHLC update completed: {counter.value}/{total_symbols} "
            f"({success_rate:.1%})",
            flush=True,
        )
        return 0 if success_rate >= C.SCRIPT_FAILURE_THRESHOLD else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
