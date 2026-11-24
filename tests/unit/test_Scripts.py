"""Tests for import-safe multiprocessing script entry points."""

import importlib
from contextlib import nullcontext
from types import ModuleType
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from hyperdrive import Constants as C

RECENT_SCRIPTS = [
    ("scripts.update_dividends", "update_poly_dividends", "save_dividends"),
    ("scripts.update_splits", "update_poly_splits", "save_splits"),
    ("scripts.update_intraday", "update_poly_intraday", "save_intraday"),
]

HISTORICAL_SCRIPTS = [
    ("scripts.update_hist_dividends", "update_poly_dividends", "save_dividends"),
    ("scripts.update_hist_splits", "update_poly_splits", "save_splits"),
]

ALL_SCRIPTS = [
    *(case[0] for case in RECENT_SCRIPTS),
    *(case[0] for case in HISTORICAL_SCRIPTS),
    "scripts.update_hist_ohlc",
]


class Counter:
    """Minimal shared-counter replacement for direct worker tests."""

    def __init__(self) -> None:
        """Initialize the counter."""
        self.value = 0

    def get_lock(self) -> nullcontext[None]:
        """Return a no-op context manager."""
        return nullcontext()


def load_script(name: str) -> ModuleType:
    """Import a script module without executing its guarded entry point."""
    return importlib.import_module(name)


@pytest.mark.parametrize("module_name", ALL_SCRIPTS)
def test_script_import_has_no_runtime_state(module_name: str) -> None:
    """Keep clients, symbol scopes, counters, and processes out of imports."""
    module = load_script(module_name)

    for runtime_name in ("alpc", "counter", "p1", "p2", "poly", "symbols"):
        assert runtime_name not in vars(module)


@pytest.mark.parametrize("module_name", [case[0] for case in RECENT_SCRIPTS])
def test_recent_main_uses_spawn(module_name: str) -> None:
    """Build recent-data workers and counters from the spawn context."""
    module = load_script(module_name)
    stocks = ["AAPL", "MSFT"]
    market = MagicMock()
    market.get_symbols.return_value = stocks
    context = MagicMock()
    context.Value.return_value.value = 100
    provider = patch.object(module, "Polygon")

    with (
        patch.object(module, "MarketData", return_value=market),
        patch.object(module, "get_context", return_value=context) as get_context,
        provider as provider_class,
    ):
        result = module.main()

    get_context.assert_called_once_with("spawn")
    context.Value.assert_called_once_with("i", 0)
    context.Process.return_value.start.assert_called_once_with()
    context.Process.return_value.join.assert_called_once_with()
    provider_class.assert_not_called()
    assert result == 0
    process_symbols = context.Process.call_args.kwargs["args"][0]
    expected = (
        stocks + module.POLY_CRYPTO_SYMBOLS if "intraday" in module_name else stocks
    )
    assert process_symbols == expected


@pytest.mark.parametrize("module_name", [case[0] for case in HISTORICAL_SCRIPTS])
def test_historical_main_uses_spawn_and_slice(module_name: str) -> None:
    """Preserve the historical scripts' second-half symbol scope."""
    module = load_script(module_name)
    symbols = [f"S{index}" for index in range(252)]
    market = MagicMock()
    market.get_symbols.return_value = symbols
    context = MagicMock()

    with (
        patch.object(module, "MarketData", return_value=market),
        patch.object(module, "get_context", return_value=context) as get_context,
        patch.object(module, "Polygon") as provider_class,
    ):
        result = module.main()

    get_context.assert_called_once_with("spawn")
    context.Process.return_value.start.assert_called_once_with()
    context.Process.return_value.join.assert_called_once_with()
    provider_class.assert_not_called()
    assert context.Process.call_args.kwargs["args"] == (symbols[250:],)
    assert result == 0


def test_historical_ohlc_main_uses_spawn() -> None:
    """Build the historical Alpaca scope before spawning its worker."""
    module = load_script("scripts.update_hist_ohlc")
    market = MagicMock()
    market.get_symbols.return_value = ["MSFT", "AAPL"]
    market.get_ndx.return_value = pd.DataFrame({C.SYMBOL: ["AAPL", "NVDA"]})
    context = MagicMock()

    with (
        patch.object(module, "MarketData", return_value=market),
        patch.object(module, "get_context", return_value=context) as get_context,
        patch.object(module, "AlpacaData") as provider_class,
    ):
        result = module.main()

    get_context.assert_called_once_with("spawn")
    provider_class.assert_not_called()
    assert context.Process.call_args.kwargs["args"] == (["AAPL", "MSFT", "NVDA"],)
    assert result == 0


@pytest.mark.parametrize(("module_name", "worker_name", "save_name"), RECENT_SCRIPTS)
def test_recent_worker_owns_provider(
    module_name: str,
    worker_name: str,
    save_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Construct recent-data providers inside their worker functions."""
    module = load_script(module_name)
    monkeypatch.setenv("POLYGON", "token")
    monkeypatch.setattr(module.C, "CI", False)
    provider = MagicMock(provider="polygon")
    getattr(provider, save_name).return_value = (
        [] if save_name == "save_intraday" else ""
    )
    counter = Counter()

    with patch.object(module, "Polygon", return_value=provider) as provider_class:
        getattr(module, worker_name)(["AAPL"], counter)

    provider_class.assert_called_once()
    getattr(provider, save_name).assert_called_once()
    assert counter.value == 1


@pytest.mark.parametrize(
    ("module_name", "worker_name", "save_name"), HISTORICAL_SCRIPTS
)
def test_historical_worker_owns_provider(
    module_name: str,
    worker_name: str,
    save_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Construct historical Polygon providers inside their workers."""
    module = load_script(module_name)
    monkeypatch.setattr(module.C, "CI", False)
    provider = MagicMock(provider="polygon")

    with patch.object(module, "Polygon", return_value=provider) as provider_class:
        getattr(module, worker_name)(["AAPL"])

    provider_class.assert_called_once_with()
    getattr(provider, save_name).assert_called_once()


def test_historical_ohlc_worker_owns_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Construct the historical Alpaca provider inside its worker."""
    module = load_script("scripts.update_hist_ohlc")
    monkeypatch.setattr(module.C, "CI", False)
    provider = MagicMock(provider="alpaca")

    with patch.object(module, "AlpacaData", return_value=provider) as provider_class:
        module.update_alpc_ohlc(["AAPL"])

    provider_class.assert_called_once_with(paper=module.C.TEST)
    provider.save_ohlc.assert_called_once_with(symbol="AAPL", timeframe="10y")


def test_ohlc_worker_uses_timeframe_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use the workflow timeframe when updating OHLC data."""
    module = load_script("scripts.update_ohlc")
    monkeypatch.setenv("OHLC_TIMEFRAME", "1m")
    monkeypatch.setattr(module.C, "CI", False)
    provider = MagicMock(provider="alpaca")
    counter = Counter()

    module._update_symbol(provider, "AAPL", "AAPL", 1, 1, counter)

    provider.save_ohlc.assert_called_once_with(symbol="AAPL", timeframe="1m", retries=1)
    assert counter.value == 1


def test_update_api_import_has_no_runtime_state() -> None:
    """Build the API clients and read the signals only when main runs."""
    module = load_script("scripts.update_api")

    for runtime_name in ("df", "hist", "kr", "md", "signals", "symbol"):
        assert runtime_name not in vars(module)


@pytest.mark.parametrize(
    ("times", "dropped"),
    [
        (pd.date_range("2026-01-01", periods=30, freq="D"), 7),
        (pd.bdate_range("2026-01-01", periods=30), 5),
    ],
)
def test_update_api_preview_ends_a_week_early(
    times: pd.DatetimeIndex, dropped: int
) -> None:
    """Cut the preview by date for daily (crypto) and trading-day (stock) rows."""
    module = load_script("scripts.update_api")
    df = pd.DataFrame({C.TIME: times})

    delayed = module.delay_preview(df)

    assert delayed[C.TIME].max() == times[-1] - pd.Timedelta(days=7)
    assert len(delayed) == len(times) - dropped


def test_update_api_main_saves_delayed_previews(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Save USD and BTC previews that end one week before the latest row."""
    module = load_script("scripts.update_api")
    monkeypatch.setenv("SYMBOL", "BTC")
    times = pd.date_range("2026-01-01", periods=40, freq="D")
    market = MagicMock()
    market.get_ohlc.return_value = pd.DataFrame(
        {C.TIME: times, C.CLOSE: [100.0 + day for day in range(40)]}
    )
    market.reader.load_csv.return_value = pd.DataFrame(
        {C.TIME: times.strftime("%Y-%m-%d"), C.SIG: [day % 10 < 5 for day in range(40)]}
    )

    with (
        patch.object(module, "MarketData", return_value=market),
        patch.object(module, "Kraken") as kraken,
    ):
        kraken.return_value.get_fee.return_value = 0.26
        assert module.main() == 0

    _, preview = market.writer.save_json.call_args.args
    last = (times[-1] - pd.Timedelta(days=7)).strftime("%m/%d/%Y")
    for currency in ("BTC", "USD"):
        assert preview[currency]["data"][-1][C.TIME] == last
        assert len(preview[currency]["data"]) == 2 * (40 - 7)
