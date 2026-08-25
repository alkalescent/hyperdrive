from hyperdrive.DataSource import Polygon
from hyperdrive.Storage import Store

store = Store()
poly = Polygon()

# stocks to download all 15+ years of data
to_download = []

# s3://hyperdrive.pro/data/intraday/polygon/

# stocks to update (last month of data)
symbols = []

if __name__ == "__main__":
    for symbol in symbols:
        store.upload_dir(path=f"data/intraday/polygon/{symbol}")
        poly.save_intraday(symbol=symbol, timeframe="30d", retries=1)
    for symbol in to_download:
        poly.save_intraday(symbol=symbol, timeframe="6300d", retries=1)
