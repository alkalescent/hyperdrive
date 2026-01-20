"""Robinhood brokerage integration for portfolio management."""

import os
from typing import Any

import pandas as pd
import pyotp
import robin_stocks.robinhood as rh
from dotenv import find_dotenv, load_dotenv

from . import Constants as C
from .Constants import PathFinder
from .FileOps import FileReader, FileWriter


class Robinhood:
    """Robinhood brokerage client for portfolio operations.

    Handles authentication and provides methods for retrieving
    historical data, holdings, and portfolio symbols.

    Attributes:
        api: The robin_stocks Robinhood API module.
        writer: FileWriter instance for saving data.
        reader: FileReader instance for loading data.
        finder: PathFinder instance for path resolution.
    """

    def __init__(
        self,
        usr: str | None = None,
        pwd: str | None = None,
        mfa: str | None = None,
    ) -> None:
        """Initialize and authenticate with Robinhood.

        Args:
            usr: Robinhood username. Defaults to RH_USERNAME env var.
            pwd: Robinhood password. Defaults to RH_PASSWORD env var.
            mfa: MFA code. Defaults to generated code from RH_2FA env var.
        """
        # Authentication
        load_dotenv(find_dotenv("config.env"))

        username = usr or os.environ["RH_USERNAME"]
        password = pwd or os.environ["RH_PASSWORD"]
        mfa_code = mfa or pyotp.TOTP(os.environ["RH_2FA"]).now()

        rh.login(username, password, mfa_code=mfa_code)
        self.api = rh
        self.writer = FileWriter()
        self.reader = FileReader()
        self.finder = PathFinder()

    def flatten(self, xxs: list[list[Any]]) -> list[Any]:
        """Flatten a 2D list into a 1D list.

        Args:
            xxs: A list of lists to flatten.

        Returns:
            A single flattened list.
        """
        return [x for xs in xxs for x in xs]

    def get_hists(
        self,
        symbols: list[str],
        span: str = "year",
        interval: str = "day",
        save: bool = False,
    ) -> pd.DataFrame:
        """Get historical price data for multiple symbols.

        Args:
            symbols: List of stock symbols.
            span: Time span for historical data.
            interval: Data interval (e.g., 'day', 'hour').
            save: Whether to save the data to CSV.

        Returns:
            DataFrame with historical OHLC data.
        """
        hists = [
            self.api.get_stock_historicals(symbol, interval, span) for symbol in symbols
        ]
        clean = [hist for hist in hists if hist != [None]]
        df = pd.DataFrame.from_records(self.flatten(clean))
        # look into diff b/w tz_localize and tz_convert w param 'US/Eastern'
        # ideally store utc time
        df["begins_at"] = pd.to_datetime(df["begins_at"]).apply(
            lambda x: x.tz_localize(None)
        )
        # df = df.sort_values('begins_at')
        if save:
            self.writer.save_csv("data/data.csv", df)
        return df

    def get_names(self, symbols: list[str]) -> list[str]:
        """Get company names for a list of stock symbols.

        Args:
            symbols: List of stock symbols.

        Returns:
            List of company names.
        """
        names = []
        for symbol in symbols:
            if hasattr(self, "holdings") and symbol in self.holdings:
                names.append(self.holdings[symbol]["name"])
            else:
                names.append(self.api.get_name_by_symbol(symbol))
        return names

    def save_symbols(self) -> None:
        """Save portfolio symbols and names to CSV."""
        symbols = self.get_symbols()
        names = self.get_names(symbols)
        df = pd.DataFrame({C.SYMBOL: symbols, C.NAME: names})
        self.writer.save_csv(self.finder.get_symbols_path(), df)

    def get_holdings(self) -> dict[str, Any]:
        """Get current portfolio holdings.

        Returns:
            Dictionary of holdings keyed by symbol.
        """
        if not hasattr(self, "holdings"):
            self.holdings = self.api.build_holdings()
        return self.holdings

    def get_symbols(self) -> list[str]:
        """Get list of symbols in portfolio.

        Returns:
            List of stock symbols in holdings.
        """
        if not hasattr(self, "holdings"):
            self.get_holdings()

        return list(self.holdings)
