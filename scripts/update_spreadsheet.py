from datetime import datetime, timedelta

import gspread
import pandas as pd
import robin_stocks.robinhood as rh_api

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
    opt_df["updated_at"] = pd.to_datetime(opt_df["updated_at"]).dt.tz_localize(None)

# Get all option events (assignments, exercises, expirations)
# Query by unique symbols from option orders
all_events = []
if not opt_df.empty:
    symbols = opt_df["chain_symbol"].unique()
    for sym in symbols:
        events = rh_api.get_events(sym)
        if events:
            all_events.extend(events)
evt_df = pd.DataFrame(all_events) if all_events else pd.DataFrame()
if not evt_df.empty:
    evt_df["event_date"] = pd.to_datetime(evt_df["event_date"])

# Get stock orders (for finding rebuy after assignment)
stock_orders = rh_api.get_all_stock_orders()
stock_df = pd.DataFrame(stock_orders) if stock_orders else pd.DataFrame()
if not stock_df.empty:
    stock_df = stock_df[stock_df["state"] == "filled"]
    stock_df["last_transaction_at"] = pd.to_datetime(
        stock_df["last_transaction_at"]
    ).dt.tz_localize(None)
    # Add symbol column by resolving instrument URLs
    stock_df["symbol"] = stock_df["instrument"].apply(rh_api.get_symbol_by_url)


def calculate_options_value(start: str, end: str) -> float:
    """Calculate net options value for a date range.

    Scenarios:
    1. Sold option (credit) - keep premium
    2. Bought option (debit) - pay premium (rolling out)
    3. Assignment - get assignment credit, subtract cost to rebuy shares

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
    symbols_traded = set()

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

        symbols_traded.add(order["chain_symbol"])

    # Check for assignment events in this period
    if not evt_df.empty:
        # Filter events in date range
        evt_mask = (evt_df["event_date"] >= start) & (evt_df["event_date"] < end)
        period_events = evt_df[evt_mask]

        for _, event in period_events.iterrows():
            if event["type"] == "assignment" and event["state"] == "confirmed":
                # Assignment credit (selling shares at strike)
                cash_amount = float(event.get("total_cash_amount", 0) or 0)
                if event["direction"] == "credit":
                    net_value += cash_amount
                else:
                    net_value -= cash_amount

                # Find rebuy cost - look for stock buy after assignment
                equity_comps = event.get("equity_components", [])
                if equity_comps and not stock_df.empty:
                    for comp in equity_comps:
                        comp_symbol = comp.get("symbol")
                        comp_qty = float(comp.get("quantity", 0))
                        event_date = event["event_date"]

                        # Look for buy orders after assignment (within 7 days)
                        buy_mask = (
                            (stock_df["symbol"] == comp_symbol)
                            & (stock_df["side"] == "buy")
                            & (stock_df["last_transaction_at"] >= event_date)
                            & (
                                stock_df["last_transaction_at"]
                                < event_date + timedelta(days=7)
                            )
                        )
                        potential_buys = stock_df[buy_mask]

                        for _, buy in potential_buys.iterrows():
                            buy_qty = float(buy["quantity"])
                            buy_price = float(buy["average_price"])
                            # Match by quantity (assignment qty matches rebuy)
                            if abs(buy_qty - comp_qty) < 1:
                                rebuy_cost = buy_qty * buy_price
                                net_value -= rebuy_cost
                                break

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
    div = div_df[(div_df["payable_date"] >= start_str) & (div_df["payable_date"] < end_str)]
    div_val = round(div["amount"].astype(float).sum())
    sh.update_cell(df.index[row_idx] + row_buffer, col_idxs[col] + col_buffer, div_val)

    # Update options
    col = "Options"
    opt_val = round(calculate_options_value(start_str, end_str))
    sh.update_cell(df.index[row_idx] + row_buffer, col_idxs[col] + col_buffer, opt_val)
