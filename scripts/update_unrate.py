from hyperdrive.DataSource import LaborStats

bls = LaborStats()
bls.save_unemployment_rate(timeframe="2y")
