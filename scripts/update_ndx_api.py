from hyperdrive import Constants as C
from hyperdrive.DataSource import MarketData
from hyperdrive.History import Historian

md = MarketData()
md.provider = "polygon"
hist = Historian()
alpc_orders_path = md.finder.get_new_orders_path("alpaca")

# TODO: filter to just from 2025-01-01 onwards
qqq = md.get_ohlc("QQQ")
holding_pf = hist.from_holding(qqq[C.CLOSE])
