import sys
sys.path.append('hyperdrive')
from DataSource import MarketData  # noqa
from History import Historian  # noqa
import Constants as C  # noqa

md = MarketData()
md.provider = 'polygon'
hist = Historian()
alpc_orders_path = md.finder.get_new_orders_path('alpaca')

# TODO: filter to just from 2025-01-01 onwards
qqq = md.get_ohlc('QQQ')
holding_pf = hist.from_holding(qqq[C.CLOSE])
