import os
import json
import requests
from time import sleep, time
from bs4 import BeautifulSoup
import pandas as pd
from random import random
from polygon import RESTClient, exceptions
from dotenv import load_dotenv, find_dotenv
from FileOps import FileReader, FileWriter
from Calculus import Calculator
from TimeMachine import TimeTraveller
from Constants import PathFinder
import Constants as C
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys


class MarketData:
    def __init__(self):
        load_dotenv(find_dotenv('config.env'))
        self.writer = FileWriter()
        self.reader = FileReader()
        self.finder = PathFinder()
        self.traveller = TimeTraveller()
        self.calculator = Calculator()
        self.provider = 'polygon'

    def get_indexer(self, s1, s2):
        return list(s1.intersection(s2))

    def try_again(self, func, **kwargs):
        retries = (kwargs['retries']
                   if 'retries' in kwargs
                   else C.DEFAULT_RETRIES)
        delay = (kwargs['delay']
                 if 'delay' in kwargs
                 else C.DEFAULT_DELAY)
        func_args = {k: v for k, v in kwargs.items() if k not in {
            'retries', 'delay'}}
        for retry in range(retries):
            try:
                return func(**func_args)
            except Exception as e:
                if retry == retries - 1:
                    raise e
                else:
                    sleep(delay)

    def get_symbols(self):
        # get cached list of symbols
        symbols_path = self.finder.get_symbols_path()
        return list(self.reader.load_csv(symbols_path)[C.SYMBOL])

    def get_dividends(self, symbol, timeframe='max'):
        # given a symbol, return a cached dataframe
        df = self.reader.load_csv(
            self.finder.get_dividends_path(symbol, self.provider))
        filtered = self.reader.data_in_timeframe(df, C.EX, timeframe)
        return filtered

    def standardize(self, df, full_mapping,
                    filename, columns, default):
        mapping = {k: v for k, v in full_mapping.items() if k in df}

        df = df[list(mapping)].rename(columns=mapping)
        time_col, val_cols = columns[0], columns[1:]

        if time_col in df and set(val_cols).issubset(df.columns):
            df = self.reader.update_df(
                filename, df, time_col).sort_values(by=[time_col])
            # since time col is pd.datetime,
            # consider converting to YYYY-MM-DD str format
            for val_col in val_cols:
                df[val_col] = df[val_col].apply(
                    lambda val: float(val) if val else default)

        return df

    def standardize_dividends(self, symbol, df):
        full_mapping = dict(
            zip(
                ['exDate', 'paymentDate', 'declaredDate', 'amount'],
                [C.EX, C.PAY, C.DEC, C.DIV]
            )
        )
        filename = self.finder.get_dividends_path(symbol, self.provider)
        return self.standardize(
            df,
            full_mapping,
            filename,
            [C.EX, C.DIV],
            0
        )

    def save_dividends(self, **kwargs):
        # given a symbol, save its dividend history
        symbol = kwargs['symbol']
        filename = self.finder.get_dividends_path(symbol, self.provider)
        if os.path.exists(filename):
            os.remove(filename)
        df = self.reader.update_df(
            filename, self.get_dividends(**kwargs), C.EX, C.DATE_FMT)
        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename

    def get_splits(self, symbol, timeframe='max'):
        # given a symbol, return a cached dataframe
        df = self.reader.load_csv(
            self.finder.get_splits_path(symbol, self.provider))
        filtered = self.reader.data_in_timeframe(df, C.EX, timeframe)
        return filtered

    def standardize_splits(self, symbol, df):
        full_mapping = dict(
            zip(
                ['exDate', 'paymentDate', 'declaredDate', 'ratio'],
                [C.EX, C.PAY, C.DEC, C.RATIO]
            )
        )
        filename = self.finder.get_splits_path(symbol, self.provider)
        return self.standardize(
            df,
            full_mapping,
            filename,
            [C.EX, C.RATIO],
            1
        )

    def save_splits(self, **kwargs):
        # given a symbol, save its splits history
        symbol = kwargs['symbol']
        filename = self.finder.get_splits_path(symbol, self.provider)
        if os.path.exists(filename):
            os.remove(filename)
        df = self.reader.update_df(
            filename, self.get_splits(**kwargs), C.EX, C.DATE_FMT)
        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename

    def standardize_ohlc(self, symbol, df, filename=None):
        full_mapping = dict(
            zip(
                ['date', 'open', 'high', 'low', 'close',
                 'volume', 'average', 'trades'],
                [C.TIME, C.OPEN, C.HIGH, C.LOW, C.CLOSE,
                 C.VOL, C.AVG, C.TRADES]
            )
        )

        filename = filename or self.finder.get_ohlc_path(symbol, self.provider)

        df = self.standardize(
            df,
            full_mapping,
            filename,
            [C.TIME, C.OPEN, C.HIGH, C.LOW, C.CLOSE],
            0
        )

        for col in [C.VOL, C.TRADES]:
            if col in df:
                df[col] = df[col].apply(
                    lambda val: 0 if pd.isnull(val) else int(val))

        return df

    def get_ohlc(self, symbol, timeframe='max'):
        df = self.reader.load_csv(
            self.finder.get_ohlc_path(symbol, self.provider))
        filtered = self.reader.data_in_timeframe(df, C.TIME, timeframe)
        return filtered

    def save_ohlc(self, **kwargs):
        symbol = kwargs['symbol']
        filename = self.finder.get_ohlc_path(symbol, self.provider)
        if os.path.exists(filename):
            os.remove(filename)
        df = self.reader.update_df(
            filename, self.get_ohlc(**kwargs), C.TIME, C.DATE_FMT)
        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename

    def get_intraday(self, symbol, min=1, timeframe='max', extra_hrs=False):
        # implement way to transform 1 min dataset to 5 min data
        #  or 30 or 60 should be flexible soln
        # implement way to only get market hours
        # given a symbol, return a cached dataframe
        dates = self.traveller.dates_in_range(timeframe)
        for date in dates:
            df = self.reader.load_csv(
                self.finder.get_intraday_path(symbol, date, self.provider))
            yield self.reader.data_in_timeframe(df, C.TIME, timeframe)

    def save_intraday(self, **kwargs):
        symbol = kwargs['symbol']
        dfs = self.get_intraday(**kwargs)
        filenames = []

        for df in dfs:
            date = df[C.TIME].iloc[0].strftime(C.DATE_FMT)
            filename = self.finder.get_intraday_path(
                symbol, date, self.provider)
            if os.path.exists(filename):
                os.remove(filename)
            save_fmt = f'{C.DATE_FMT} {C.TIME_FMT}'
            df = self.reader.update_df(
                filename, df, C.TIME, save_fmt)
            self.writer.update_csv(filename, df)
            if os.path.exists(filename):
                filenames.append(filename)
        return filenames

    def get_unemployment_rate(self, timeframe='max'):
        # given a timeframe, return a cached dataframe
        df = self.reader.load_csv(
            self.finder.get_unemployment_path())
        filtered = self.reader.data_in_timeframe(df, C.TIME, timeframe)
        return filtered

    def standardize_unemployment(self,  df):
        full_mapping = dict(
            zip(
                ['time', 'value'],
                [C.TIME, C.UN_RATE]
            )
        )
        filename = self.finder.get_unemployment_path()
        return self.standardize(
            df,
            full_mapping,
            filename,
            [C.TIME, C.UN_RATE],
            0
        )

    def save_unemployment_rate(self, **kwargs):
        # given a symbol, save its dividend history
        filename = self.finder.get_unemployment_path()
        if os.path.exists(filename):
            os.remove(filename)
        df = self.reader.update_df(
            filename, self.get_unemployment_rate(**kwargs), C.TIME, '%Y-%m')
        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename

    def standardize_s2f_ratio(self, df):
        full_mapping = dict(
            zip(
                ['t', 'o.daysTillHalving', 'o.ratio'],
                [C.TIME, C.HALVING, C.RATIO]
            )
        )
        filename = self.finder.get_s2f_path()
        df = self.standardize(
            df,
            full_mapping,
            filename,
            [C.TIME, C.HALVING, C.RATIO],
            0
        )
        return df[self.get_indexer({C.TIME, C.HALVING, C.RATIO}, df.columns)]

    def get_s2f_ratio(self, timeframe='max'):
        # given a symbol, return a cached dataframe
        df = self.reader.load_csv(
            self.finder.get_s2f_path())
        filtered = self.reader.data_in_timeframe(df, C.TIME, timeframe)[
            [C.TIME, C.HALVING, C.RATIO]]
        return filtered

    def save_s2f_ratio(self, **kwargs):
        # # given a symbol, save its s2f data
        filename = self.finder.get_s2f_path()

        if os.path.exists(filename):
            os.remove(filename)

        df = self.reader.update_df(
            filename, self.get_s2f_ratio(**kwargs), C.TIME, C.DATE_FMT)

        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename

    def standardize_diff_ribbon(self, df):
        full_mapping = dict(
            zip(
                ['t', 'o.ma9', 'o.ma14', 'o.ma25', 'o.ma40',
                    'o.ma60', 'o.ma90', 'o.ma128', 'o.ma200'],
                [C.TIME] + C.MAs
            )
        )
        filename = self.finder.get_diff_ribbon_path()
        df = self.standardize(
            df,
            full_mapping,
            filename,
            [C.TIME] + C.MAs,
            0
        )
        return df[self.get_indexer(set([C.TIME] + C.MAs), df.columns)]

    def get_diff_ribbon(self, timeframe='max'):
        # given a symbol, return a cached dataframe
        df = self.reader.load_csv(
            self.finder.get_diff_ribbon_path())
        filtered = self.reader.data_in_timeframe(df, C.TIME, timeframe)[
            [C.TIME] + C.MAs]
        return filtered

    def save_diff_ribbon(self, **kwargs):
        # # given a symbol, save its s2f data
        filename = self.finder.get_diff_ribbon_path()

        if os.path.exists(filename):
            os.remove(filename)

        df = self.reader.update_df(
            filename, self.get_diff_ribbon(**kwargs), C.TIME, C.DATE_FMT)

        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename

    def standardize_sopr(self, df):
        full_mapping = dict(
            zip(
                ['t', 'v'],
                [C.TIME, C.SOPR]
            )
        )
        filename = self.finder.get_diff_ribbon_path()
        df = self.standardize(
            df,
            full_mapping,
            filename,
            [C.TIME, C.SOPR],
            1
        )
        return df[self.get_indexer({C.TIME, C.SOPR}, df.columns)]

    def get_sopr(self, timeframe='max'):
        # given a symbol, return a cached dataframe
        df = self.reader.load_csv(
            self.finder.get_sopr_path())
        filtered = self.reader.data_in_timeframe(df, C.TIME, timeframe)[
            [C.TIME, C.SOPR]]
        return filtered

    def save_sopr(self, **kwargs):
        # # given a symbol, save its s2f data
        filename = self.finder.get_sopr_path()

        if os.path.exists(filename):
            os.remove(filename)

        df = self.reader.update_df(
            filename, self.get_sopr(**kwargs), C.TIME, C.DATE_FMT)

        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename
    # def handle_request(self, url, err_msg):

    def standardize_ndx(self, df):
        if df.empty:
            df = pd.DataFrame(columns=[C.TIME, C.SYMBOL, C.DELTA])
        df = df.sort_values(
            by=[C.TIME, C.SYMBOL]
        ).drop_duplicates(C.SYMBOL, keep='last')
        df = df[df[C.DELTA] == '+'].reset_index(drop=True)
        return df

    def get_saved_ndx(self):
        df = self.reader.load_csv(self.finder.get_ndx_path())
        return df

    def get_ndx(self, date=datetime.now()):
        date = self.traveller.convert_date(date)
        df = self.get_saved_ndx()
        return self.standardize_ndx(
            df[df[C.TIME] <= date] if C.TIME in df else df)

    def get_latest_ndx(self, **kwargs):
        def _get_latest_ndx():
            url = "https://en.wikipedia.org/wiki/Nasdaq-100#Components"
            # alternatives:
            # https://www.nasdaq.com/solutions/nasdaq-100/companies
            # https://www.cnbc.com/nasdaq-100/
            res = requests.get(url)
            soup = BeautifulSoup(res.text, 'html.parser')
            html = soup.select("table#constituents")[0]
            df = pd.read_html(str(html))[0]
            symbols = df['Ticker']
            today = datetime.today().strftime(C.DATE_FMT)
            df = pd.DataFrame({
                C.TIME: len(symbols) * [today],
                C.SYMBOL: symbols,
                C.DELTA: len(symbols) * ['+']
            })
            return df
        return self.try_again(func=_get_latest_ndx, **kwargs)

    def save_ndx(self, **kwargs):
        filename = self.finder.get_ndx_path()

        if os.path.exists(filename):
            os.remove(filename)

        saved = self.get_saved_ndx()
        before = set(self.standardize_ndx(saved)[C.SYMBOL])
        after = set(self.get_latest_ndx(**kwargs)[C.SYMBOL])
        today = datetime.now().strftime(C.DATE_FMT)
        minus, plus = self.calculator.get_difference(before, after)
        union = list(minus.union(plus))
        to_append = pd.DataFrame({
            C.TIME: [today] * len(union),
            C.SYMBOL: union,
            C.DELTA: ['+' if u in plus else '-' for u in union]
        })
        df = pd.concat([saved, to_append], ignore_index=True).sort_values(
            by=[C.TIME, C.SYMBOL]).reset_index(drop=True)
        self.writer.update_csv(filename, df)

        if os.path.exists(filename):
            return filename

    def log_api_call_time(self):
        self.last_api_call_time = time()

    def obey_free_limit(self, free_delay):
        if self.free and hasattr(self, 'last_api_call_time'):
            time_since_last_call = time() - self.last_api_call_time
            delay = free_delay - time_since_last_call
            if delay > 0:
                sleep(delay)


class Indices(MarketData):
    def __init__(self):
        super().__init__()

    def get_ndx(self, date=datetime.now()):
        old = super().get_ndx(date)
        date = self.traveller.convert_date(date)
        new = self.get_latest_ndx()
        new = new[new[C.TIME] <= date]
        df = pd.concat([old, new])
        return self.standardize_ndx(df)


class AlpacaData(MarketData):
    def __init__(
            self,
            token=os.environ.get('ALPACA'),
            secret=os.environ.get('ALPACA_SECRET'),
            free=True,
            paper=False
    ):
        super().__init__()
        self.base = 'https://data.alpaca.markets'
        self.token = os.environ.get(
            'ALPACA_PAPER') if paper or C.TEST else token
        self.secret = os.environ.get(
            'ALPACA_PAPER_SECRET') if paper or C.TEST else secret
        if not (self.token and self.secret):
            raise Exception('missing Alpaca credentials')
        self.provider = 'alpaca'
        self.free = free

    # def get_dividends(self, **kwargs):
    #     pass
    # def get_splits(self, **kwargs):
    #     pass

    def get_ohlc(self, **kwargs):
        def _get_ohlc(symbol, timeframe='max'):
            is_crypto = symbol in C.ALPC_CRYPTO_SYMBOLS
            version = 'v1beta3' if is_crypto else 'v2'
            page_token = None
            start, _ = self.traveller.convert_dates(timeframe)
            parts = [
                self.base,
                version,
                'crypto/us' if is_crypto else 'stocks',
                'bars',
            ]
            url = '/'.join(parts)
            pre_params = {
                'symbols': symbol,
                'timeframe': '1D',
                'start': start,
                # end should be > 15 min before current UTC time in this format
                # 2025-01-01T00:00:00Z
                'limit': 10000,
            } | ({} if is_crypto else {'adjustment': 'all'})
            headers = {
                'APCA-API-KEY-ID': self.token,
                'APCA-API-SECRET-KEY': self.secret
            }
            results = []
            while True:
                self.obey_free_limit(C.ALPACA_FREE_DELAY)
                try:
                    post_params = {
                        'page_token': page_token} if page_token else {}
                    params = pre_params | post_params
                    response = requests.get(url, params, headers=headers)
                    if not response.ok:
                        raise Exception(
                            'Invalid response from Alpaca for OHLC',
                            response.status_code,
                            response.text
                        )
                    data = response.json()
                    if data.get('bars') and data['bars'].get(symbol):
                        results += data['bars'][symbol]
                finally:
                    self.log_api_call_time()
                if data.get('next_page_token'):
                    page_token = data['next_page_token']
                else:
                    break
            df = pd.DataFrame(results)
            columns = {
                't': 'date',
                'o': 'open',
                'h': 'high',
                'l': 'low',
                'c': 'close',
                'v': 'volume',
                'vw': 'average',
                'n': 'trades'
            }
            df = df.rename(columns=columns)
            df['date'] = pd.to_datetime(df['date']).dt.tz_convert(
                C.TZ).dt.tz_localize(None)
            df = self.standardize_ohlc(symbol, df)
            return self.reader.data_in_timeframe(df, C.TIME, timeframe)
        return self.try_again(func=_get_ohlc, **kwargs)

        # def get_intraday(self, **kwargs):
        #     pass

        # def get_news(self, **kwargs):
        #     pass


class Polygon(MarketData):
    def __init__(self, token=os.environ.get('POLYGON'), free=True):
        super().__init__()
        self.client = RESTClient(token)
        self.provider = 'polygon'
        self.free = free

    def paginate(self, gen, apply):
        results = []
        for idx, item in enumerate(gen):
            if idx % C.POLY_MAX_LIMIT == 0:
                self.log_api_call_time()
            if self.free and idx % C.POLY_MAX_LIMIT == C.POLY_MAX_LIMIT - 1:
                sleep(C.POLY_FREE_DELAY)
            results.append(apply(item))
        return results

    def get_dividends(self, **kwargs):
        def _get_dividends(symbol, timeframe='max'):
            self.obey_free_limit(C.POLY_FREE_DELAY)
            try:
                start, _ = self.traveller.convert_dates(timeframe)
                response = self.paginate(
                    self.client.list_dividends(
                        symbol,
                        ex_dividend_date_gte=start,
                        order='desc',
                        sort='ex_dividend_date',
                        limit=C.POLY_MAX_LIMIT
                    ),
                    lambda div: {
                        'exDate': div.ex_dividend_date,
                        'paymentDate': div.pay_date,
                        'declaredDate': div.declaration_date,
                        'amount': div.cash_amount
                    }
                )
            finally:
                self.log_api_call_time()
            raw = pd.DataFrame(response)
            df = self.standardize_dividends(symbol, raw)
            return self.reader.data_in_timeframe(df, C.EX, timeframe)
        return self.try_again(func=_get_dividends, **kwargs)

    def get_splits(self, **kwargs):
        def _get_splits(symbol, timeframe='max'):
            self.obey_free_limit(C.POLY_FREE_DELAY)
            try:
                start, _ = self.traveller.convert_dates(timeframe)
                response = self.paginate(
                    self.client.list_splits(
                        symbol,
                        execution_date_gte=start,
                        order='desc',
                        sort='execution_date',
                        limit=C.POLY_MAX_LIMIT
                    ),
                    lambda split: {
                        'exDate': split.execution_date,
                        'ratio': split.split_from / split.split_to
                    }
                )
            finally:
                self.log_api_call_time()
            raw = pd.DataFrame(response)
            df = self.standardize_splits(symbol, raw)
            return self.reader.data_in_timeframe(df, C.EX, timeframe)
        return self.try_again(func=_get_splits, **kwargs)

    def get_ohlc(self, **kwargs):
        def _get_ohlc(symbol, timeframe='max'):
            is_crypto = symbol.find('X%3A') == 0
            formatted_start, formatted_end = self.traveller.convert_dates(
                timeframe)
            self.obey_free_limit(C.POLY_FREE_DELAY)
            try:
                response = self.client.get_aggs(
                    symbol, 1, 'day',
                    from_=formatted_start, to=formatted_end, adjusted=True, limit=C.POLY_MAX_AGGS_LIMIT
                )
            finally:
                self.log_api_call_time()

            raw = [vars(item) for item in response]
            columns = {'timestamp': 'date',
                       'vwap': 'average', 'transactions': 'trades'}
            df = pd.DataFrame(raw).rename(columns=columns)
            if is_crypto:
                df['date'] = pd.to_datetime(
                    df['date'], unit='ms')
            else:
                df['date'] = pd.to_datetime(
                    df['date'], unit='ms').dt.tz_localize(
                    'UTC').dt.tz_convert(
                    C.TZ).dt.tz_localize(None)
            df = self.standardize_ohlc(symbol, df)
            return self.reader.data_in_timeframe(df, C.TIME, timeframe)

        return self.try_again(func=_get_ohlc, **kwargs)

    def get_intraday(self, **kwargs):
        def _get_intraday(symbol, min=1, timeframe='max', extra_hrs=True):
            # pass min directly into stock_aggs function as multiplier
            is_crypto = symbol.find('X%3A') == 0
            dates = self.traveller.dates_in_range(timeframe)
            if dates == []:
                raise Exception(f'No dates in timeframe: {timeframe}.')

            for _, date in enumerate(dates):
                self.obey_free_limit(C.POLY_FREE_DELAY)
                try:
                    response = self.client.get_aggs(
                        symbol, min, 'minute', from_=date, to=date,
                        adjusted=True, limit=C.POLY_MAX_AGGS_LIMIT
                    )
                except exceptions.NoResultsError:
                    # This is to prevent breaking the loop over weekends
                    continue
                finally:
                    self.log_api_call_time()

                raw = [vars(item) for item in response]
                columns = {'timestamp': 'date',
                           'vwap': 'average', 'transactions': 'trades'}
                df = pd.DataFrame(raw).rename(columns=columns)
                if is_crypto:
                    df['date'] = pd.to_datetime(
                        df['date'], unit='ms')
                else:
                    df['date'] = pd.to_datetime(
                        df['date'], unit='ms').dt.tz_localize(
                        'UTC').dt.tz_convert(
                        C.TZ).dt.tz_localize(None)
                filename = self.finder.get_intraday_path(
                    symbol, date, self.provider)
                df = self.standardize_ohlc(symbol, df, filename)
                df = df[df[C.TIME].dt.strftime(C.DATE_FMT) == date]
                yield df

        return self.try_again(func=_get_intraday, **kwargs)


# newShares = oldShares / ratio


class LaborStats(MarketData):
    def __init__(self):
        super().__init__()
        self.base = 'https://api.bls.gov'
        self.version = 'v2'
        self.token = os.environ.get('BLS')
        self.provider = 'bls'

    def get_unemployment_rate(self, **kwargs):
        def _get_unemployment_rate(timeframe):
            start, end = self.traveller.convert_dates(timeframe, '%Y')

            parts = [
                self.base,
                'publicAPI',
                self.version,
                'timeseries',
                'data'
            ]
            url = '/'.join(parts)
            params = {'registrationkey': self.token,
                      'startyear': start, 'endyear': end,
                      'seriesid': 'LNS14000000'}

            response = requests.post(url, data=params)

            if (
                    response.ok and
                    response.json()['status'] == 'REQUEST_SUCCEEDED'
            ):

                payload = response.json()
                if payload['status'] == 'REQUEST_SUCCEEDED':
                    data = payload['Results']['series'][0]['data']
                else:
                    raise Exception(
                        f'''
                        Invalid response from BLS because {data["message"][0]}
                        '''
                    )
            else:
                raise Exception(
                    'Invalid response from BLS for unemployment rate',
                    response.status_code, response.json()
                )

            df = pd.DataFrame(data)
            df['time'] = df['year'] + '-' + \
                df['period'].str.slice(start=1)

            df = self.standardize_unemployment(df)
            return self.reader.data_in_timeframe(df, C.TIME, timeframe)

        return self.try_again(func=_get_unemployment_rate, **kwargs)


class Glassnode(MarketData):
    def __init__(self, use_cookies=False):
        super().__init__()
        self.base = 'https://api.glassnode.com'
        self.version = 'v1'
        self.token = os.environ.get('GLASSNODE')
        self.provider = 'glassnode'
        self.use_cookies = use_cookies
        if self.use_cookies:
            self.use_auth()

    def use_auth(self):
        options = ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.set_capability('goog:loggingPrefs', {"performance": "ALL"})

        driver = webdriver.Chrome(options=options)
        driver.get('https://studio.glassnode.com/auth/login')
        delay = 10

        def get_element(id):
            return WebDriverWait(driver, delay).until(
                EC.presence_of_element_located((By.ID, id)))

        email = get_element('email')
        email.send_keys(os.environ['RH_USERNAME'])
        password = get_element('current-password')
        password.send_keys(os.environ['GLASSNODE_PASS'])
        password.send_keys(Keys.ENTER)
        sleep(15)
        driver.get('https://studio.glassnode.com/metrics')
        sleep(5)
        url = "https://api.glassnode.com/v1/metrics/market/price_usd_close?a=BTC&i=24h&referer=charts"
        driver.get(url)
        sleep(5)  # wait for the requests to take place

        # extract requests from logs
        raw_logs = driver.get_log("performance")
        logs = [json.loads(raw_log["message"])["message"]
                for raw_log in raw_logs]

        def log_filter(log_):
            return (
                log_["method"] == "Network.requestWillBeSent" and
                log_['params']['request']['url'] == url and
                log_['params']['request']['method'] == 'GET'
            )

        self.headers = [log['params']['request']['headers']
                        for log in filter(log_filter, logs)][-1]
        self.cookies = {cookie['name']: cookie['value']
                        for cookie in driver.get_cookies()}

    def make_request(self, url):
        params = {'a': 'BTC', 'c': 'native', 'i': '24h', 'referer': 'charts'}
        if self.use_cookies:
            headers = self.headers
            cookies = self.cookies
        else:
            params['api_key'] = self.token
            headers = {}
            cookies = {}
        response = requests.get(
            url, params=params, headers=headers, cookies=cookies)
        sleep(random() * 5)
        return response

    def get_s2f_ratio(self, **kwargs):
        def _get_s2f_ratio(timeframe):
            parts = [
                self.base,
                self.version,
                'metrics',
                'indicators',
                'stock_to_flow_ratio'
            ]
            url = '/'.join(parts)
            empty = pd.DataFrame()
            response = self.make_request(url)

            if response.ok:
                data = response.json()
            else:
                raise Exception(
                    'Invalid response from Glassnode for S2F Ratio', response)

            if data == []:
                return empty

            df = pd.json_normalize(data)
            df['t'] = pd.to_datetime(df['t'], unit='s')
            df = self.standardize_s2f_ratio(df)
            return self.reader.data_in_timeframe(df, C.TIME, timeframe)

        return self.try_again(func=_get_s2f_ratio, **kwargs)

    def get_diff_ribbon(self, **kwargs):
        def _get_diff_ribbon(timeframe):
            parts = [
                self.base,
                self.version,
                'metrics',
                'indicators',
                'difficulty_ribbon'
            ]
            url = '/'.join(parts)
            empty = pd.DataFrame()
            response = self.make_request(url)

            if response.ok:
                data = response.json()
            else:
                raise Exception(
                    'Invalid response from Glassnode for Difficulty Ribbon',
                    response
                )

            if data == []:
                return empty

            df = pd.json_normalize(data)
            df['t'] = pd.to_datetime(df['t'], unit='s')
            df = self.standardize_diff_ribbon(df)
            return self.reader.data_in_timeframe(df, C.TIME, timeframe)

        return self.try_again(func=_get_diff_ribbon, **kwargs)

    def get_sopr(self, **kwargs):
        def _get_sopr(timeframe):
            parts = [
                self.base,
                self.version,
                'metrics',
                'indicators',
                'sopr'
            ]
            url = '/'.join(parts)
            empty = pd.DataFrame()
            response = self.make_request(url)

            if response.ok:
                data = response.json()
            else:
                raise Exception(
                    'Invalid response from Glassnode for SOPR', response)

            if data == []:
                return empty

            df = pd.json_normalize(data)
            df['t'] = pd.to_datetime(df['t'], unit='s')
            df = self.standardize_sopr(df)
            return self.reader.data_in_timeframe(df, C.TIME, timeframe)

        return self.try_again(func=_get_sopr, **kwargs)
