"""Update the FIRE spreadsheet with dividends, options, and staking rewards.

Replaces the beaconcha.in dependency in update_spreadsheet.py with free,
keyless sources. Differences from the original:

- Crypto values are computed per row over the interval the balance ledger
  actually measured, and the same interval prices the ETH.
- ETH/USD comes from the live Polygon provider rather than a committed CSV.
- All cells are computed before any are written, so a failure partway through
  cannot leave the sheet half updated.
- A Crypto value that cannot be determined is left blank rather than written
  as zero. The empty cell filter picks the row up again on the next run.

Run with --dry-run to print the intended writes without touching the sheet.
"""

import sys
from datetime import datetime, timedelta
from decimal import Decimal

import gspread
import pandas as pd

from hyperdrive import Constants as C
from hyperdrive.Broker import Robinhood
from hyperdrive.Constants import CLOSE, DATE_FMT
from hyperdrive.DataSource import Polygon
from hyperdrive.Staking import StakingRewards

DRY_RUN = "--dry-run" in sys.argv


def calculate_options_value(opt_df: pd.DataFrame, start: str, end: str) -> float:
    """Calculate net options value for a date range.

    Scenarios:
    1. Expired: profit = sold option premium (credit)
    2. Rolled: profit = sold option - bought option (credit - debit)
    3. Assignment + Rebuy: After assignment, stock is rebought and a new
       longer-dated option is sold. The new option premium should NOT be
       counted as profit since it's reinvesting capital, not realized gains.
       Heuristic: Ignore credits for options with expiration >12 days out.

    Args:
        opt_df: Filled option orders.
        start: Start date string (inclusive)
        end: End date string (exclusive)

    Returns:
        Net options value (positive = profit)
    """
    if opt_df.empty:
        return 0.0

    mask = (opt_df["updated_at"] >= start) & (opt_df["updated_at"] < end)
    period_opts = opt_df[mask]

    if period_opts.empty:
        return 0.0

    net_value = 0.0

    for _, order in period_opts.iterrows():
        # Premium is total for the order (price * 100 * quantity)
        premium = float(order["premium"])
        direction = order["direction"]

        # Scenario 3 heuristic: Ignore credits for options expiring >12 days out
        # These are likely replacement calls after assignment, not realized profit
        if direction == "credit":
            order_date = pd.to_datetime(order["updated_at"])
            legs = order.get("legs", [])
            if legs:
                exp_date_str = legs[0].get("expiration_date")
                if exp_date_str:
                    exp_date = pd.to_datetime(exp_date_str)
                    if (exp_date - order_date).days > 12:
                        # Long-dated: rebuy after assignment, not realized profit
                        continue
            net_value += premium
        else:  # debit
            net_value -= premium

    return net_value


def price_for(eth: pd.DataFrame, start: datetime, end: datetime) -> Decimal | None:
    """Get the average ETH/USD close over an interval.

    Polygon returns a Time column over a range index, and crypto timestamps are
    timezone naive UTC, matching the sheet's parsed dates.

    Args:
        eth: OHLC frame from the Polygon provider.
        start: Interval start.
        end: Interval end.

    Returns:
        Average close as a Decimal, or None when the interval has no data.
    """
    times = pd.to_datetime(eth[C.TIME])
    window = eth[(times >= start) & (times < end)][CLOSE]
    if window.empty:
        return None
    return Decimal(str(window.mean()))


def main() -> None:
    """Compute every intended cell, then write the resolved ones."""
    gc = gspread.service_account()
    sh = gc.open("FIRE").get_worksheet(0)
    old = pd.DataFrame(sh.get_all_records())
    df = old.copy(deep=True)

    # Filter to only updateable rows
    cols = list(df.columns)
    total_idx = cols.index("Total")
    df = df[cols[:total_idx]]
    df["Date"] = pd.to_datetime(df["Date"])
    today = datetime.today()
    df = df[(df["Date"] < today) & (df.eq("").any(axis=1))]
    dates = df["Date"]

    if dates.empty:
        print("No rows to update.")
        return

    rh = Robinhood()

    div_df = pd.DataFrame(rh.get_dividends())

    opt_df = pd.DataFrame(rh.get_options())
    opt_df = opt_df[opt_df["state"] == "filled"]
    opt_df["updated_at"] = pd.to_datetime(opt_df["updated_at"]).dt.strftime(DATE_FMT)

    # Record this run's balance observation before valuing any row.
    rewards = StakingRewards()
    try:
        rewards.record_snapshot()
    except Exception as e:
        print(f"WARNING: could not record staking snapshot: {e}")

    # One price series covering every row being filled.
    span_days = (today - dates.min()).days + C.FEW
    md = Polygon()
    eth = md.get_ohlc(C.ETH_USD, f"{span_days}d")

    # Phase one: compute.
    row_buffer = 2  # account for header and 0 index
    col_buffer = 1  # account for 0 index
    col_idxs = {col: idx for idx, col in enumerate(cols)}
    writes: list[tuple[int, int, float]] = []
    skipped: list[str] = []

    for row_idx, date in enumerate(dates):
        end = date
        start = end - timedelta(weeks=1)
        end_str = end.strftime(DATE_FMT)
        start_str = start.strftime(DATE_FMT)
        sheet_row = df.index[row_idx] + row_buffer

        div = div_df[
            (div_df["payable_date"] >= start_str) & (div_df["payable_date"] < end_str)
        ]
        div_val = round(div["amount"].astype(float).sum())
        writes.append((sheet_row, col_idxs["Dividends"] + col_buffer, div_val))

        opt_val = round(calculate_options_value(opt_df, start_str, end_str))
        writes.append((sheet_row, col_idxs["Options"] + col_buffer, opt_val))

        crypto_val = crypto_for(rewards, eth, start, end)
        if crypto_val is None:
            skipped.append(end_str)
            continue
        writes.append((sheet_row, col_idxs["Crypto"] + col_buffer, round(crypto_val)))

    # Phase two: write.
    for row, col, value in writes:
        if DRY_RUN:
            print(f"row={row} col={col} value={value}")
        else:
            sh.update_cell(row, col, value)

    if skipped:
        print(f"Crypto left blank for {len(skipped)} row(s): {', '.join(skipped)}")
    print(f"{'Would write' if DRY_RUN else 'Wrote'} {len(writes)} cells.")


def crypto_for(
    rewards: StakingRewards, eth: pd.DataFrame, start: datetime, end: datetime
) -> float | None:
    """Value one row's staking rewards in USD.

    Consensus rewards, execution rewards, and pricing all use the interval the
    ledger actually measured, which is offset from the row's nominal dates by
    however long after the boundary the job ran.

    Args:
        rewards: Configured reward calculator.
        eth: ETH/USD OHLC frame.
        start: Row window start.
        end: Row window end.

    Returns:
        USD value, or None when any component is undeterminable.
    """
    interval = rewards.measured_interval(start, end)
    if interval is None:
        return None
    measured_start, measured_end = interval

    consensus = rewards.consensus_rewards(start, end)
    if consensus is None:
        return None
    execution = rewards.execution_rewards(measured_start, measured_end)
    if execution is None:
        return None
    price = price_for(eth, measured_start, measured_end)
    if price is None:
        return None
    return float((consensus + execution) * price)


if __name__ == "__main__":
    main()
