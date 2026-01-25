import gspread
import pandas as pd
from hyperdrive.Broker import Robinhood

gc = gspread.service_account()
sh = gc.open("FIRE").get_worksheet(0)
records = sh.get_all_records()
df = pd.DataFrame(records)
cols = list(df.columns)
total_idx = cols.index("Total")
# print(records)
# df = pl.from_pandas(pd.DataFrame(records))
print(df[cols[:total_idx]])



# print(list(df.columns).index("Total"))

# rh = Robinhood()
# dividends = rh.get_dividends()
# df = pl.from_dicts(dividends)

