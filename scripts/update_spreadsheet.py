import os
import math
from datetime import datetime, timedelta

import gspread
import pandas as pd
import requests

from hyperdrive.Broker import Robinhood
from hyperdrive.Constants import CLOSE, DATE_FMT
from hyperdrive.DataSource import MarketData


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
opt_df = opt_df[opt_df["state"] == "filled"]
opt_df["updated_at"] = pd.to_datetime(opt_df["updated_at"]).dt.strftime(DATE_FMT)


def calculate_crypto_value(days_since_update: int) -> float:
    """Calculate crypto staking rewards estimated per week.

    Selects the largest Beaconchain evaluation window that fits within
    the time since the last update, fetches aggregate ETH validator
    rewards for that window, and scales to a weekly estimate using the
    aggregate average.

    Args:
        days_since_update: Number of days since the last spreadsheet update.

    Returns:
        Estimated weekly staking rewards value in USD.
    """
    # Beaconchain windows mapped to their duration in days
    windows = [("24h", 1), ("7d", 7), ("30d", 30), ("90d", 90)]

    # Pick the closest window based on the last update
    window, window_days = min(
        windows, key=lambda wd: abs(math.log(wd[1] / max(days_since_update, 1)))
    )
    url = "https://beaconcha.in/api/v2/ethereum/validators/rewards-aggregate"
    payload = {
        "validator": {"validator_identifiers": [690345]},
        "range": {"evaluation_window": window},
        "chain": "mainnet",
    }
    headers = {
        "Authorization": f"Bearer {os.environ['BEACONCHAIN']}",
        "Content-Type": "application/json",
    }

    response = requests.post(url, json=payload, headers=headers)
    data = response.json()
    total_amt = float(f"0.{data['data']['total']}")

    # Scale aggregate rewards to a weekly estimate
    weekly_amt = total_amt / window_days * 7

    md = MarketData()
    md.provider = "polygon"
    ohlc_timeframe = f"{window_days}d"
    cost = md.calculator.avg(md.get_ohlc("X%3AETHUSD", ohlc_timeframe)[CLOSE])
    return weekly_amt * cost


def calculate_options_value(start: str, end: str) -> float:
    """Calculate net options value for a date range.

    Scenarios:
    1. Expired: profit = sold option premium (credit)
    2. Rolled: profit = sold option - bought option (credit - debit)
    3. Assignment + Rebuy: After assignment, stock is rebought and a new
       longer-dated option is sold. The new option premium should NOT be
       counted as profit since it's reinvesting capital, not realized gains.
       Heuristic: Ignore credits for options with expiration >12 days out.

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

        # Scenario 3 heuristic: Ignore credits for options expiring >12 days out
        # These are likely replacement calls after assignment, not realized profit
        if direction == "credit":
            order_date = pd.to_datetime(order["updated_at"])
            # Get expiration from first leg
            legs = order.get("legs", [])
            if legs:
                exp_date_str = legs[0].get("expiration_date")
                if exp_date_str:
                    exp_date = pd.to_datetime(exp_date_str)
                    days_to_expiry = (exp_date - order_date).days
                    if days_to_expiry > 12:
                        # Skip long-dated options (Scenario 3 - rebuy after assignment)
                        continue
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
days_since_update = (today - dates.min()).days

# weekly estimate
crypto_val = round(calculate_crypto_value(days_since_update))

for row_idx, date in enumerate(dates):
    end = date
    start = end - timedelta(weeks=1)
    end_str = end.strftime(DATE_FMT)
    start_str = start.strftime(DATE_FMT)

    # Update dividends
    col = "Dividends"
    div = div_df[
        (div_df["payable_date"] >= start_str) & (div_df["payable_date"] < end_str)
    ]
    div_val = round(div["amount"].astype(float).sum())
    sh.update_cell(df.index[row_idx] + row_buffer, col_idxs[col] + col_buffer, div_val)

    # Update options
    col = "Options"
    opt_val = round(calculate_options_value(start_str, end_str))
    sh.update_cell(df.index[row_idx] + row_buffer, col_idxs[col] + col_buffer, opt_val)

    # Update crypto
    col = "Crypto"
    sh.update_cell(
        df.index[row_idx] + row_buffer, col_idxs[col] + col_buffer, crypto_val
    )
