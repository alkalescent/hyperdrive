import gspread
import polars as pl
import pandas as pd
from hyperdrive.Broker import Robinhood

gc = gspread.service_account()
sh = gc.open("FIRE").get_worksheet(0)
records = sh.get_all_records()
# df = pl.DataFrame(records[:-755])
# print(records)
df = pl.from_pandas(pd.DataFrame(records))
print(df)

# rh = Robinhood()
# dividends = rh.get_dividends()
# df = pl.from_dicts(dividends)

