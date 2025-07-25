import os
import pytest
from time import sleep, time
from random import choice
import pandas as pd
from hyperdrive.DataSource import MarketData, Indices, Polygon, \
                        LaborStats, Glassnode, AlpacaData  # noqa autopep8
import hyperdrive.Constants as C  # noqa autopep8
from hyperdrive.Workflow import Flow  # noqa autopep8
from hyperdrive.Utils import SwissArmyKnife  # noqa autopep8


flow = Flow()
knife = SwissArmyKnife()
md = knife.use_dev(MarketData())
idc = knife.use_dev(Indices())
alpc = knife.use_dev(AlpacaData(paper=True))
poly = knife.use_dev(Polygon())
bls = knife.use_dev(LaborStats())
glass = knife.use_dev(Glassnode(use_cookies=True))

exp_symbols = ['AMZN', 'META', 'NFLX']
retries = 10


class TestMarketData:
    def test_init(self):
        assert type(md).__name__ == 'MarketData'
        assert hasattr(md, 'writer')
        assert hasattr(md, 'reader')
        assert hasattr(md, 'finder')
        assert hasattr(md, 'provider')

    def test_try_again(self):
        assert md.try_again(lambda: 0) == 0
        with pytest.raises(ZeroDivisionError):
            md.try_again(lambda: 0 / 0)

    def test_get_symbols(self):
        symbols = set(md.get_symbols())
        for symbol in exp_symbols:
            assert symbol in symbols

    def test_get_dividends(self):
        df = md.get_dividends(symbol='AAPL')
        assert {C.EX, C.PAY, C.DEC, C.DIV}.issubset(df.columns)
        assert len(df) > 15
        assert len(df[df[C.EX] < '2015-12-25']) > 0
        assert len(df[df[C.EX] > '2020-01-01']) > 0

    def test_standardize_dividends(self):
        columns = ['exDate', 'paymentDate', 'declaredDate', 'amount']
        new_cols = [C.EX, C.PAY, C.DEC, C.DIV]
        sel_idx = 2
        selected = columns[sel_idx:]
        df = pd.DataFrame({column: [0] for column in columns})
        standardized = md.standardize_dividends('AAPL', df)
        for column in new_cols:
            assert column in standardized

        df.drop(columns=selected, inplace=True)
        standardized = md.standardize_dividends('AAPL', df)
        for curr_idx, column in enumerate(new_cols):
            col_in_df = column in standardized
            assert col_in_df if curr_idx < sel_idx else not col_in_df

    def test_save_dividends(self):
        symbol = 'O'
        div_path = md.finder.get_dividends_path(symbol)
        temp_path = f'{div_path}_TEMP'

        if os.path.exists(div_path):
            os.rename(div_path, temp_path)

        for _ in range(retries):
            poly.save_dividends(
                symbol=symbol, timeframe='5y', retries=1, delay=0)
            if not md.reader.check_file_exists(div_path):
                delay = choice(range(5, 10))
                sleep(delay)
            else:
                break

        assert md.reader.check_file_exists(div_path)
        assert md.reader.store.modified_delta(div_path).total_seconds() < 60
        df = md.reader.load_csv(div_path)
        assert {C.EX, C.PAY, C.DEC, C.DIV}.issubset(df.columns)
        assert len(df) > 0

        if os.path.exists(temp_path):
            os.rename(temp_path, div_path)

    def test_get_splits(self):
        df = md.get_splits('NFLX')
        assert {C.EX, C.DEC, C.RATIO}.issubset(df.columns)
        assert len(df) > 0

    def test_standardize_splits(self):
        columns = ['exDate', 'paymentDate', 'declaredDate', 'ratio']
        new_cols = [C.EX, C.PAY, C.DEC, C.RATIO]
        sel_idx = 2
        selected = columns[sel_idx:]
        df = pd.DataFrame({column: [0] for column in columns})
        standardized = md.standardize_splits('NFLX', df)
        for column in new_cols:
            assert column in standardized

        df.drop(columns=selected, inplace=True)
        standardized = md.standardize_splits('NFLX', df)
        for curr_idx, column in enumerate(new_cols):
            col_in_df = column in standardized
            assert col_in_df if curr_idx < sel_idx else not col_in_df

    def test_save_splits(self):
        symbol = 'CMG'
        splt_path = md.finder.get_splits_path(symbol)
        temp_path = f'{splt_path}_TEMP'

        if os.path.exists(splt_path):
            os.rename(splt_path, temp_path)

        for _ in range(retries):
            poly.save_splits(symbol=symbol, timeframe='2y', retries=1, delay=0)
            if not md.reader.check_file_exists(splt_path):
                delay = choice(range(5, 10))
                sleep(delay)
            else:
                break

        assert md.reader.check_file_exists(splt_path)
        assert md.reader.store.modified_delta(splt_path).total_seconds() < 60
        df = md.reader.load_csv(splt_path)
        assert {C.EX, C.RATIO}.issubset(df.columns)
        assert len(df) > 0

        if os.path.exists(temp_path):
            os.rename(temp_path, splt_path)

    def test_standardize_ohlc(self):
        columns = ['date', 'open', 'high', 'low', 'close', 'volume']
        new_cols = [C.TIME, C.OPEN, C.HIGH, C.LOW, C.CLOSE, C.VOL]
        sel_idx = 2
        selected = columns[:sel_idx]
        df = pd.DataFrame({column: [0] for column in columns})
        standardized = md.standardize_ohlc('NFLX', df)
        for column in new_cols:
            assert column in standardized

        df.drop(columns=selected, inplace=True)
        standardized = md.standardize_ohlc('NFLX', df)
        for curr_idx, column in enumerate(new_cols):
            col_in_df = column in standardized
            assert col_in_df if curr_idx >= sel_idx else not col_in_df

    def test_save_ohlc(self):
        symbol = 'NFLX'
        ohlc_path = md.finder.get_ohlc_path(symbol)
        temp_path = f'{ohlc_path}_TEMP'

        if os.path.exists(ohlc_path):
            os.rename(ohlc_path, temp_path)

        for _ in range(retries):
            poly.save_ohlc(symbol=symbol, timeframe='1m', retries=1, delay=0)
            if not md.reader.check_file_exists(ohlc_path):
                delay = choice(range(5, 10))
                sleep(delay)
            else:
                break

        assert md.reader.check_file_exists(ohlc_path)
        assert md.reader.store.modified_delta(ohlc_path).total_seconds() < 60
        df = md.reader.load_csv(ohlc_path)
        assert {C.TIME, C.OPEN, C.HIGH, C.LOW,
                C.CLOSE, C.VOL}.issubset(df.columns)
        assert len(df) > 0

        if os.path.exists(temp_path):
            os.rename(temp_path, ohlc_path)

    def test_save_intraday(self):
        sleep(C.POLY_FREE_DELAY)
        symbol = 'NFLX'
        timeframe = '4d'
        dates = md.traveller.dates_in_range(timeframe)
        intra_paths = [md.finder.get_intraday_path(
            symbol, date) for date in dates]
        filenames = set(poly.save_intraday(
            symbol=symbol, timeframe=timeframe))
        intersection = filenames.intersection(intra_paths)
        assert intersection

        for path in intersection:
            df = md.reader.load_csv(path)
            assert {C.TIME, C.OPEN, C.HIGH, C.LOW,
                    C.CLOSE, C.VOL}.issubset(df.columns)
            assert len(df) > 0
            os.remove(path)

    def test_get_ohlc(self):
        df = md.get_ohlc('NFLX', '5y')
        assert {C.TIME, C.OPEN, C.HIGH, C.LOW,
                C.CLOSE, C.VOL}.issubset(df.columns)
        assert len(df) > 0

    def test_get_intraday(self):
        df = pd.concat(md.get_intraday(symbol='NFLX', timeframe='2m'))
        assert {C.TIME, C.OPEN, C.HIGH, C.LOW,
                C.CLOSE, C.VOL}.issubset(df.columns)
        assert len(df) > 0

    def test_get_unemployment_rate(self):
        df = md.get_unemployment_rate()
        assert {C.TIME, C.UN_RATE}.issubset(df.columns)
        assert len(df) > 100

    def test_standardize_unemployment(self):
        columns = ['time', 'value']
        new_cols = [C.TIME, C.UN_RATE]
        sel_idx = 1
        selected = columns[:sel_idx]
        df = pd.DataFrame({column: [0] for column in columns})
        standardized = md.standardize_unemployment(df)
        for column in new_cols:
            assert column in standardized

        df.drop(columns=selected, inplace=True)
        standardized = md.standardize_unemployment(df)
        for curr_idx, column in enumerate(new_cols):
            col_in_df = column in standardized
            assert col_in_df if curr_idx >= sel_idx else not col_in_df

    def test_save_unemployment_rate(self):
        assert 'unemployment.csv' in md.save_unemployment_rate(timeframe='2y')

    def test_save_s2f_ratio(self):
        assert 's2f.csv' in md.save_s2f_ratio()

    def test_save_diff_ribbon(self):
        assert 'diff_ribbon.csv' in md.save_diff_ribbon()

    def test_save_sopr(self):
        assert 'sopr.csv' in md.save_sopr()

    def test_get_ndx(self):
        ndx = md.get_ndx()
        assert {C.TIME, C.SYMBOL, C.DELTA}.issubset(ndx.columns)
        assert 'AAPL' in set(ndx[C.SYMBOL])
        assert (ndx[C.DELTA] == '+').all()

    def test_standardize_ndx(self):
        nonstd = pd.DataFrame({
            C.TIME: ['2020-01-03', '2020-01-01', '2020-01-02'],
            C.SYMBOL: ['AAPL', 'NFLX', 'AAPL'],
            C.DELTA: ['-', '+', '+'],
        })
        std = pd.DataFrame({
            C.TIME: ['2020-01-01'],
            C.SYMBOL: ['NFLX'],
            C.DELTA: ['+'],
        })
        assert md.standardize_ndx(nonstd).equals(std)

    def test_save_ndx(self):
        assert 'ndx.csv' in md.save_ndx()


class TestIndices:
    def test_init(self):
        assert isinstance(idc, Indices)

    def test_get_ndx(self):
        ndx = idc.get_ndx()
        assert {C.TIME, C.SYMBOL, C.DELTA}.issubset(ndx.columns)
        assert 'AAPL' in set(ndx[C.SYMBOL])
        assert (ndx[C.DELTA] == '+').all()


class TestAlpaca:
    def test_init(self):
        assert isinstance(alpc, AlpacaData)
        assert hasattr(alpc, 'base')
        assert hasattr(alpc, 'token')
        assert hasattr(alpc, 'secret')
        assert hasattr(alpc, 'provider')
        assert hasattr(alpc, 'free')

    def test_get_ohlc(self):
        if not flow.is_any_workflow_running():
            df = alpc.get_ohlc(symbol='AAPL', timeframe='1m')
            assert {C.TIME, C.OPEN, C.HIGH, C.LOW,
                    C.CLOSE, C.VOL, C.AVG}.issubset(df.columns)
            assert len(df) > 10
        else:
            print('Skipping Alpaca OHLC test because update in progress')


class TestPolygon:
    def test_init(self):
        assert isinstance(poly, Polygon)
        assert hasattr(poly, 'client')
        assert hasattr(poly, 'provider')

    def test_get_dividends(self):
        if not flow.is_any_workflow_running():
            df = poly.get_dividends(symbol='AAPL', timeframe='5y')
            assert {C.EX, C.PAY, C.DEC, C.DIV}.issubset(df.columns)
            assert len(df) > 0
        else:
            print(
                'Skipping Polygon.io dividends test because update in progress'
            )

    def test_get_splits(self):
        if not flow.is_any_workflow_running():
            df = poly.get_splits(symbol='AAPL')
            assert {C.EX, C.DEC, C.RATIO}.issubset(df.columns)
            assert len(df) > 0
        else:
            print('Skipping Polygon.io splits test because update in progress')

    def test_get_ohlc(self):
        if not flow.is_any_workflow_running():
            df = poly.get_ohlc(symbol='AAPL', timeframe='1m')
            assert {C.TIME, C.OPEN, C.HIGH, C.LOW,
                    C.CLOSE, C.VOL, C.AVG}.issubset(df.columns)
            assert len(df) > 10
        else:
            print('Skipping Polygon.io OHLC test because update in progress')

    def test_get_intraday(self):
        if not flow.is_any_workflow_running():
            df = pd.concat(poly.get_intraday(symbol='AAPL', timeframe='1w'))
            assert {C.TIME, C.OPEN, C.HIGH, C.LOW,
                    C.CLOSE, C.VOL}.issubset(df.columns)
            assert len(df) > 1000
        else:
            print(
                'Skipping Polygon.io intraday test because update in progress')

    def test_log_api_call_time(self):
        if hasattr(poly, 'last_api_call_time'):
            delattr(poly, 'last_api_call_time')
        poly.log_api_call_time()
        assert hasattr(poly, 'last_api_call_time')

    def test_obey_free_limit(self):
        if hasattr(poly, 'last_api_call_time'):
            delattr(poly, 'last_api_call_time')

        then = time()
        poly.log_api_call_time()
        poly.obey_free_limit(C.POLY_FREE_DELAY)
        now = time()
        assert now - then > C.POLY_FREE_DELAY


class TestLaborStats:
    def test_init(self):
        assert type(bls).__name__ == 'LaborStats'
        assert hasattr(bls, 'base')
        assert hasattr(bls, 'version')
        assert hasattr(bls, 'token')
        assert hasattr(bls, 'provider')

    def test_get_unemployment_rate(self):
        df = bls.get_unemployment_rate(timeframe='2y')
        assert {C.TIME, C.UN_RATE}.issubset(df.columns)
        assert len(df) > 12


class TestGlassnode:
    def test_init(self):
        assert type(glass).__name__ == 'Glassnode'
        assert hasattr(glass, 'base')
        assert hasattr(glass, 'version')
        assert hasattr(glass, 'token')
        assert hasattr(glass, 'provider')

    def test_get_s2f_ratio(self):
        df = glass.get_s2f_ratio(timeframe='max')
        assert len(df) > 3000
        assert {C.TIME, C.HALVING, C.RATIO}.issubset(df.columns)

    def test_get_diff_ribbon(self):
        df = glass.get_diff_ribbon(timeframe='max')
        assert len(df) > 3000
        assert set([C.TIME] + C.MAs).issubset(df.columns)

    def test_get_sopr(self):
        df = glass.get_sopr(timeframe='max')
        assert len(df) > 3000
        assert {C.TIME, C.SOPR}.issubset(df.columns)
