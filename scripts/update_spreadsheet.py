import gspread
import pandas as pd
from datetime import datetime, timedelta
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

# Get dividends
rh = Robinhood()
div = rh.get_dividends()
div_df = pd.DataFrame(div)

# Set up indices
row_buffer = 2 # account for header and 0 index
col_buffer = 1 # account for 0 index
col_idxs = {col: idx for idx, col in enumerate(cols)}

for row_idx, date in enumerate(dates):
    end = date
    start = end - timedelta(weeks=1)
    end = end.strftime(DATE_FMT)
    start = start.strftime(DATE_FMT)
    # Update dividends
    col = "Dividends"
    div = div_df[(div_df["payable_date"] >= start) & (div_df["payable_date"] < end)]
    div = round(div["amount"].astype(float).sum())
    sh.update_cell(df.index[row_idx] + row_buffer, col_idxs[col] + col_buffer, div)
