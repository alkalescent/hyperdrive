"""Update API with portfolio performance data."""

import os
from typing import Any

import numpy as np
import pandas as pd

from hyperdrive import Constants as C
from hyperdrive.DataSource import MarketData
from hyperdrive.Exchange import Kraken
from hyperdrive.History import Historian

# The public preview ends one week before the latest signal.
PREVIEW_DELAY = pd.Timedelta(days=7)


def transform_stats(stats: Any, metrics: list[str]) -> dict[str, float | None]:
    """Transform portfolio stats to a simplified dictionary.

    Args:
        stats: Stats object from vectorbt portfolio.
        metrics: List of metric names to extract.

    Returns:
        Dictionary mapping metric names to rounded values.
    """
    return {
        k: (None if pd.isna(v) else round(v, 2))
        for k, v in dict(stats[metrics]).items()
    }


def delay_preview(df: pd.DataFrame) -> pd.DataFrame:
    """Drop the last week of rows, counted by date.

    Crypto has a row for every day and stocks only for trading days, so a
    fixed number of rows would delay the two by different spans.

    Args:
        df: Rows with a datetime time column.

    Returns:
        The rows dated at least PREVIEW_DELAY before the latest row.
    """
    return df[df[C.TIME] <= df[C.TIME].max() - PREVIEW_DELAY]


def create_portfolio_preview(
    df: pd.DataFrame, invert: bool, hist: Historian, kr: Kraken
) -> dict[str, Any]:
    """Create portfolio preview data comparing HODL vs hyperdrive strategy.

    Args:
        df: Rows with time, closing price, and signal columns.
        invert: If True, invert for BTC-denominated returns.
        hist: Historian that builds the portfolios.
        kr: Kraken client for the trading fee.

    Returns:
        Dictionary with 'data' (time series) and 'stats' (metrics).
    """
    close = df[C.CLOSE]
    signals = df[C.SIG]
    metrics = [
        "Total Return [%]",
        "Max Drawdown [%]",
        "Win Rate [%]",
        "Profit Factor",
    ]
    if invert:
        close = 1 / close
        init_cash = 1 + C.ABS_TOL
        metrics.append("Total Fees Paid")
    else:
        init_cash = close.iloc[0]
        metrics.append("Sharpe Ratio")
        metrics.append("Sortino Ratio")

    holding_signals = np.full(len(signals), not invert)

    holding_pf = hist.from_signals(close, holding_signals, init_cash)
    if C.PREF_EXCHANGE == C.BINANCE:
        fee = C.BINANCE_FEE
    else:
        base = C.KRAKEN_SYMBOLS["BTC"]
        quote = C.KRAKEN_SYMBOLS["USD"]
        pair = kr.create_pair(base, quote)
        fee = kr.get_fee(pair) / 100
    hyper_pf = hist.from_signals(close, ~signals if invert else signals, init_cash, fee)

    holding_values = holding_pf.value()
    hyper_values = hyper_pf.value()
    holding_balances = [round(bal, 2) for bal in list(holding_values)]
    hyper_balances = [round(bal, 2) for bal in list(hyper_values)]

    holding_stats = transform_stats(holding_pf.stats(), metrics)
    hyper_stats = transform_stats(hyper_pf.stats(), metrics)

    if invert:
        holding_stats["Max Drawdown [%]"] = 0.0
        profitable_time = sum((hyper_values - holding_values) > 0) / len(hyper_values)
        new_metric = "Profitable Time [%]"
        hyper_stats[new_metric] = round(profitable_time * 100, 2)
        holding_stats[new_metric] = round(100 - hyper_stats[new_metric], 2)
        metrics.append(new_metric)

    dates = list(df[C.TIME].dt.strftime("%m/%d/%Y"))
    full_signals = list(df[C.SIG])
    signals_unfilled = hist.unfill(full_signals)
    records = []

    for idx, date in enumerate(dates):
        records.append(
            {
                "Name": "HODL",
                C.TIME: date,
                C.BAL: holding_balances[idx],
            }
        )

        records.append(
            {
                "Name": "hyperdrive",
                C.TIME: date,
                C.BAL: hyper_balances[idx],
                C.SIG: signals_unfilled[idx],
                f"Full_{C.SIG}": full_signals[idx],
            }
        )

    stats = []
    for idx, metric in enumerate(metrics):
        stats.append(
            {
                "key": idx,
                "metric": metric,
                "HODL": holding_stats[metric],
                "hyperdrive": hyper_stats[metric],
            }
        )

    preview = {"data": records, "stats": stats}
    return preview


def main() -> int:
    """Build the USD and BTC previews and save them for the API."""
    md = MarketData()
    md.provider = "polygon"
    hist = Historian()
    kr = Kraken(test=True)
    symbol = os.environ["SYMBOL"]
    signals_path = md.finder.get_signals_path()
    signals = md.reader.load_csv(signals_path)
    signals[C.TIME] = pd.to_datetime(signals[C.TIME])
    df = delay_preview(md.get_ohlc(symbol).merge(signals, on=C.TIME))

    usd_preview = create_portfolio_preview(df, False, hist, kr)
    btc_preview = create_portfolio_preview(df, True, hist, kr)

    preview = {"BTC": btc_preview, "USD": usd_preview}

    preview_path = md.finder.get_api_path("preview")
    md.writer.save_json(preview_path, preview)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
