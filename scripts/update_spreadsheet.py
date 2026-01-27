from datetime import datetime, timedelta

import gspread
import pandas as pd

from hyperdrive.Broker import Robinhood
from hyperdrive.Constants import DATE_FMT

# Open spreadsheet
gc = gspread.service_account()
sh = gc.open("FIRE").get_worksheet(0)
records = sh.get_all_records()
old = pd.DataFrame(records)
df = old.copy(deep=True)

# Filter to only updateable rows
cols = list(df.columns)
total_idx = cols.index("Total")
df = df[cols[:total_idx]]
df["Date"] = pd.to_datetime(df["Date"])
today = datetime.today()
df = df[(df["Date"] < today) & (df.eq("").any(axis=1))]
dates = df["Date"]

rh = Robinhood()

# Get dividends
div = rh.get_dividends()
div_df = pd.DataFrame(div)

# Get option orders
opt = rh.get_options()
opt_df = pd.DataFrame(opt)
# Filter to filled orders
if not opt_df.empty:
    opt_df = opt_df[opt_df["state"] == "filled"]
    opt_df["updated_at"] = pd.to_datetime(
        opt_df["updated_at"]
    ).dt.tz_localize(None)


def calculate_options_value(start: str, end: str) -> float:
    """Calculate net options value for a date range.

    Scenarios:
    1. Expired: profit = sold option premium (credit)
    2. Rolled: profit = sold option - bought option (credit - debit)

    Args:
        start: Start date string (exclusive)
        end: End date string (inclusive)

    Returns:
        Net options value (positive = profit)
    """
    if opt_df.empty:
        return 0.0

    # Filter option orders in date range
    mask = (opt_df["updated_at"] >= start) & (opt_df["updated_at"] < end)
    period_opts = opt_df[mask]

    if period_opts.empty:
        return 0.0

    net_value = 0.0

    for _, order in period_opts.iterrows():
        # Premium is total for the order (price * 100 * quantity)
        premium = float(order["premium"])
        direction = order["direction"]

        if direction == "credit":
            # Sold option - receive premium
            net_value += premium
        else:  # debit
            # Bought option - pay premium (e.g., rolling)
            net_value -= premium

    return net_value


# Set up indices
row_buffer = 2  # account for header and 0 index
col_buffer = 1  # account for 0 index
col_idxs = {col: idx for idx, col in enumerate(cols)}

for row_idx, date in enumerate(dates):
    end = date
    start = end - timedelta(weeks=1)
    end_str = end.strftime(DATE_FMT)
    start_str = start.strftime(DATE_FMT)

    # Update dividends
    col = "Dividends"
    div = div_df[(div_df["payable_date"] >= start_str)
                 & (div_df["payable_date"] < end_str)]
    div_val = round(div["amount"].astype(float).sum())
    sh.update_cell(df.index[row_idx] + row_buffer,
                   col_idxs[col] + col_buffer, div_val)

    # Update options
    col = "Options"
    opt_val = round(calculate_options_value(start_str, end_str))
    sh.update_cell(df.index[row_idx] + row_buffer,
                   col_idxs[col] + col_buffer, opt_val)
