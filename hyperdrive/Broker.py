import os
import pyotp
import robin_stocks.robinhood as rh
from dotenv import load_dotenv, find_dotenv
import pandas as pd
from Constants import PathFinder
import Constants as C
from FileOps import FileReader, FileWriter


class Robinhood:
    def __init__(self, usr=None, pwd=None, mfa=None):
        # Authentication
        load_dotenv(find_dotenv('config.env'))

        username = usr or os.environ['RH_USERNAME']
        password = pwd or os.environ['RH_PASSWORD']
        mfa_code = mfa or pyotp.TOTP(os.environ['RH_2FA']).now()

        rh.login(username, password, mfa_code=mfa_code)
        self.api = rh
        self.writer = FileWriter()
        self.reader = FileReader()
        self.finder = PathFinder()

    def flatten(self, xxs):
        # flattens 2d list into 1d list
        return [x for xs in xxs for x in xs]

    def get_hists(self, symbols, span='year', interval='day', save=False):
        # given a list of symbols,
        # return a DataFrame with historical data
        hists = [self.api.get_stock_historicals(
            symbol, interval, span) for symbol in symbols]
        clean = [hist for hist in hists if hist != [None]]
        df = pd.DataFrame.from_records(self.flatten(clean))
        # look into diff b/w tz_localize and tz_convert w param 'US/Eastern'
        # ideally store utc time
        df['begins_at'] = pd.to_datetime(df['begins_at']).apply(
            lambda x: x.tz_localize(None))
        # df = df.sort_values('begins_at')
        if save:
            self.writer.save_csv('data/data.csv', df)
        return df

    def get_names(self, symbols):
        # given a list of stock symbols
        # return a list of company names
        names = []
        for symbol in symbols:
            if hasattr(self, 'holdings') and symbol in self.holdings:
                names.append(self.holdings[symbol]['name'])
            else:
                names.append(self.api.get_name_by_symbol(symbol))
        return names

    def save_symbols(self):
        # save all the portfolio symbols in a table
        symbols = self.get_symbols()
        names = self.get_names(symbols)
        df = pd.DataFrame({
            C.SYMBOL: symbols,
            C.NAME: names
        })
        self.writer.save_csv(self.finder.get_symbols_path(), df)

    def get_holdings(self):
        if not hasattr(self, 'holdings'):
            self.holdings = self.api.build_holdings()
        return self.holdings

    def get_symbols(self):
        if not hasattr(self, 'holdings'):
            self.get_holdings()

        return [symbol for symbol in self.holdings]
