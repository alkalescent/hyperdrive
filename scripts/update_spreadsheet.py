import gspread
import pandas as pd
from datetime import datetime, timedelta
from hyperdrive.Broker import Robinhood
from hyperdrive.Constants import DATE_FMT

gc = gspread.service_account()
sh = gc.open("FIRE").get_worksheet(0)
records = sh.get_all_records()
old = pd.DataFrame(records)
df = old.copy(deep=True)
cols = list(df.columns)
total_idx = cols.index("Total")
df = df[cols[:total_idx]]
df["Date"] = pd.to_datetime(df["Date"])
today = datetime.today()
df = df[(df["Date"] < today) & (df.eq("").any(axis=1))]
dates = df["Date"]

rh = Robinhood()
div = rh.get_dividends()
div_df = pd.DataFrame(div)

for date in dates:
    end = date
    start = end - timedelta(weeks=1)
    end = end.strftime(DATE_FMT)
    start = start.strftime(DATE_FMT)
    print(start, end)
# print(df["Eth 2.0"].iloc[-1]=="")

# print(div[10:15])
