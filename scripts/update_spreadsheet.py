import polars as pl
from hyperdrive.Broker import Robinhood

rh = Robinhood()
dividends = rh.get_dividends()
df = pl.from_dicts(dividends)

