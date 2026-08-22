"""Data source classes for fetching market data from various providers.

This module contains classes for retrieving financial data including stock prices,
dividends, splits, and crypto indicators from providers like Polygon, Alpaca,
BLS, and Glassnode.
"""

import json
import logging
import os
from collections.abc import Callable, Generator, Iterable, Iterator
from datetime import datetime
from io import StringIO
from random import random
from time import sleep, time
from typing import Any

import pandas as pd
import requests
from dotenv import find_dotenv, load_dotenv
from polygon import RESTClient
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from . import Constants as C
from .Calculus import Calculator
from .Constants import PathFinder
from .FileOps import FileReader, FileWriter
from .TimeMachine import TimeTraveller

LOGGER = logging.getLogger(__name__)
WIKIPEDIA_NDX_URL = "https://en.wikipedia.org/wiki/List_of_NASDAQ-100_companies"
NASDAQ_NDX_API_URL = "https://api.nasdaq.com/api/quote/list-type/nasdaq100"
# Unused alternative sources, kept for when both of the above break:
# https://www.cnbc.com/nasdaq-100/
# https://indexes.nasdaqomx.com/Index/Weighting/NDX (authenticated)
NDX_MIN_SECURITIES = 100
NDX_MAX_SECURITIES = 110
NDX_MAX_API_AGE_DAYS = 7


class MarketData:
    """Base class for market data providers.

    Provides common functionality for fetching and storing market data including
    OHLC prices, dividends, splits, and other financial indicators.
    """

    def __init__(self) -> None:
        """Initialize the MarketData instance with default components."""
        load_dotenv(find_dotenv("config.env"))
        self.writer = FileWriter()
        self.reader = FileReader()
        self.finder = PathFinder()
        self.traveller = TimeTraveller()
        self.calculator = Calculator()
        self.provider = "polygon"

    def get_indexer(self, s1: set[str], s2: Iterable[str]) -> list[str]:
        """Get intersection of two sets as a list.

        Args:
            s1: First set of strings.
            s2: Second iterable of strings.

        Returns:
            List of strings that appear in both s1 and s2.
        """
        return list(s1.intersection(s2))

    def try_again(self, func: Callable[..., Any], **kwargs: Any) -> Any:
        """Retry a function with exponential backoff on failure.

        Args:
            func: The function to retry.
            **kwargs: Arguments passed to the function. Special keys:
                - retries: Number of retry attempts (default: C.DEFAULT_RETRIES)
                - delay: Seconds to wait between retries (default: C.DEFAULT_DELAY)

        Returns:
            The result of the function call.

        Raises:
            Exception: If all retries are exhausted.
        """
        retries = kwargs.get("retries", C.DEFAULT_RETRIES)
        delay = kwargs.get("delay", C.DEFAULT_DELAY)
        func_args = {k: v for k, v in kwargs.items() if k not in {"retries", "delay"}}
        for retry in range(retries):
            try:
                return func(**func_args)
            except Exception as e:
                if retry == retries - 1:
                    raise e
                else:
                    sleep(delay)

    def get_symbols(self) -> list[str]:
        """Get cached list of tradable symbols.

        Returns:
            List of stock/crypto symbols.
        """
        symbols_path = self.finder.get_symbols_path()
        return list(self.reader.load_csv(symbols_path)[C.SYMBOL])

    def get_dividends(
        self, symbol: str = "", timeframe: str = "max", **kwargs: Any
    ) -> pd.DataFrame:
        """Get cached dividend data for a symbol.

        Args:
            symbol: The stock symbol.
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments for subclass implementations.

        Returns:
            DataFrame with dividend history.
        """
        df = self.reader.load_csv(self.finder.get_dividends_path(symbol, self.provider))
        filtered = self.reader.data_in_timeframe(df, C.EX, timeframe)
        return filtered

    def standardize(
        self,
        df: pd.DataFrame,
        full_mapping: dict[str, str],
        filename: str,
        columns: list[str],
        default: float | int,
    ) -> pd.DataFrame:
        """Standardize a DataFrame to a common column format.

        Args:
            df: Input DataFrame to standardize.
            full_mapping: Column name mapping (old -> new).
            filename: Path to save/load cached data.
            columns: List of column names [time_col, *value_cols].
            default: Default value for missing data.

        Returns:
            Standardized DataFrame.
        """
        mapping = {k: v for k, v in full_mapping.items() if k in df}

        df = df[list(mapping)].rename(columns=mapping)
        time_col, val_cols = columns[0], columns[1:]

        if time_col in df and set(val_cols).issubset(df.columns):
            # TODO: the time column is a pd.Timestamp here. Consider normalizing it
            # to a YYYY-MM-DD string so stored CSVs round-trip without reparsing.
            df = self.reader.update_df(filename, df, time_col).sort_values(
                by=[time_col]
            )
            for val_col in val_cols:
                df[val_col] = df[val_col].apply(
                    lambda val: float(val) if val else default
                )

        return df

    def standardize_dividends(self, symbol: str, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize dividend data to common format.

        Args:
            symbol: The stock symbol.
            df: Raw dividend DataFrame.

        Returns:
            Standardized DataFrame with columns [EX, PAY, DEC, DIV].
        """
        full_mapping = dict(
            zip(
                ["exDate", "paymentDate", "declaredDate", "amount"],
                [C.EX, C.PAY, C.DEC, C.DIV],
                strict=True,
            )
        )
        filename = self.finder.get_dividends_path(symbol, self.provider)
        return self.standardize(df, full_mapping, filename, [C.EX, C.DIV], 0)

    def save_dividends(self, **kwargs: Any) -> str | None:
        """Save dividend history for a symbol.

        Args:
            **kwargs: Must include 'symbol'. Other args passed to get_dividends.

        Returns:
            Path to saved file, or None if save failed.
        """
        symbol = kwargs["symbol"]
        filename = self.finder.get_dividends_path(symbol, self.provider)
        if os.path.exists(filename):
            os.remove(filename)
        df = self.reader.update_df(
            filename, self.get_dividends(**kwargs), C.EX, C.DATE_FMT
        )
        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename
        return None

    def get_splits(
        self, symbol: str = "", timeframe: str = "max", **kwargs: Any
    ) -> pd.DataFrame:
        """Get cached split data for a symbol.

        Args:
            symbol: The stock symbol.
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments for subclass implementations.

        Returns:
            DataFrame with split history.
        """
        df = self.reader.load_csv(self.finder.get_splits_path(symbol, self.provider))
        filtered = self.reader.data_in_timeframe(df, C.EX, timeframe)
        return filtered

    def standardize_splits(self, symbol: str, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize split data to common format.

        Args:
            symbol: The stock symbol.
            df: Raw split DataFrame.

        Returns:
            Standardized DataFrame with columns [EX, PAY, DEC, RATIO].
        """
        full_mapping = dict(
            zip(
                ["exDate", "paymentDate", "declaredDate", "ratio"],
                [C.EX, C.PAY, C.DEC, C.RATIO],
                strict=True,
            )
        )
        filename = self.finder.get_splits_path(symbol, self.provider)
        return self.standardize(df, full_mapping, filename, [C.EX, C.RATIO], 1)

    def save_splits(self, **kwargs: Any) -> str | None:
        """Save split history for a symbol.

        Args:
            **kwargs: Must include 'symbol'. Other args passed to get_splits.

        Returns:
            Path to saved file, or None if save failed.
        """
        symbol = kwargs["symbol"]
        filename = self.finder.get_splits_path(symbol, self.provider)
        if os.path.exists(filename):
            os.remove(filename)
        df = self.reader.update_df(
            filename, self.get_splits(**kwargs), C.EX, C.DATE_FMT
        )
        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename
        return None

    def standardize_ohlc(
        self, symbol: str, df: pd.DataFrame, filename: str | None = None
    ) -> pd.DataFrame:
        """Standardize OHLC data to common format.

        Args:
            symbol: The stock/crypto symbol.
            df: Raw OHLC DataFrame.
            filename: Optional custom filename for caching.

        Returns:
            Standardized DataFrame with OHLC columns.
        """
        full_mapping = dict(
            zip(
                ["date", "open", "high", "low", "close", "volume", "average", "trades"],
                [C.TIME, C.OPEN, C.HIGH, C.LOW, C.CLOSE, C.VOL, C.AVG, C.TRADES],
                strict=True,
            )
        )

        filename = filename or self.finder.get_ohlc_path(symbol, self.provider)

        df = self.standardize(
            df, full_mapping, filename, [C.TIME, C.OPEN, C.HIGH, C.LOW, C.CLOSE], 0
        )

        for col in [C.VOL, C.TRADES]:
            if col in df:
                df[col] = df[col].apply(lambda val: 0 if pd.isnull(val) else int(val))

        return df

    def get_ohlc(
        self, symbol: str = "", timeframe: str = "max", **kwargs: Any
    ) -> pd.DataFrame:
        """Get cached OHLC data for a symbol.

        Args:
            symbol: The stock/crypto symbol.
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments for subclass implementations.

        Returns:
            DataFrame with OHLC price history.
        """
        df = self.reader.load_csv(self.finder.get_ohlc_path(symbol, self.provider))
        filtered = self.reader.data_in_timeframe(df, C.TIME, timeframe)
        return filtered

    def save_ohlc(self, **kwargs: Any) -> str | None:
        """Save OHLC data for a symbol.

        Args:
            **kwargs: Must include 'symbol'. Other args passed to get_ohlc.

        Returns:
            Path to saved file, or None if save failed.
        """
        return self._save_ohlc(kwargs["symbol"], **kwargs)

    def _save_ohlc(self, storage_symbol: str, **kwargs: Any) -> str | None:
        """Save fetched OHLC data under a possibly different storage symbol."""
        filename = self.finder.get_ohlc_path(storage_symbol, self.provider)
        if os.path.exists(filename):
            os.remove(filename)
        fetched = self.get_ohlc(**kwargs)
        df = self.reader.update_df(filename, fetched, C.TIME, C.DATE_FMT)
        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename
        return None

    def get_intraday(
        self,
        symbol: str = "",
        min: int = 1,  # noqa: A002
        timeframe: str = "max",
        extra_hrs: bool = False,
        **kwargs: Any,
    ) -> Generator[pd.DataFrame, None, None] | None:
        """Get cached intraday data for a symbol.

        Args:
            symbol: The stock/crypto symbol.
            min: Minute interval for data (default: 1).
            timeframe: Time range for data (default: "max").
            extra_hrs: Include extended hours data (default: False).
            **kwargs: Additional arguments for subclass implementations.

        Yields:
            DataFrames with intraday OHLC data for each date.
        """
        # TODO: resample the 1 minute dataset to 5, 30, or 60 minute bars rather
        # than refetching, and add an option to return market hours only.
        dates = self.traveller.dates_in_range(timeframe)
        for date in dates:
            date_str = date if isinstance(date, str) else date.strftime("%Y-%m-%d")
            df = self.reader.load_csv(
                self.finder.get_intraday_path(symbol, date_str, self.provider)
            )
            yield self.reader.data_in_timeframe(df, C.TIME, timeframe)

    def save_intraday(self, **kwargs: Any) -> list[str]:
        """Save intraday data for a symbol.

        Args:
            **kwargs: Must include 'symbol'. Other args passed to get_intraday.

        Returns:
            List of paths to saved files.
        """
        symbol = kwargs["symbol"]
        dfs = self.get_intraday(**kwargs)
        filenames = []

        if dfs:
            for df in dfs:
                date = df[C.TIME].iloc[0].strftime(C.DATE_FMT)
                filename = self.finder.get_intraday_path(symbol, date, self.provider)
                if os.path.exists(filename):
                    os.remove(filename)
                save_fmt = f"{C.DATE_FMT} {C.TIME_FMT}"
                df = self.reader.update_df(filename, df, C.TIME, save_fmt)
                self.writer.update_csv(filename, df)
                if os.path.exists(filename):
                    filenames.append(filename)
        return filenames

    def get_unemployment_rate(
        self, timeframe: str = "max", **kwargs: Any
    ) -> pd.DataFrame:
        """Get cached unemployment rate data.

        Args:
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments for subclass implementations.

        Returns:
            DataFrame with unemployment rate history.
        """
        df = self.reader.load_csv(self.finder.get_unemployment_path())
        filtered = self.reader.data_in_timeframe(df, C.TIME, timeframe)
        return filtered

    def standardize_unemployment(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize unemployment data to common format.

        Args:
            df: Raw unemployment DataFrame.

        Returns:
            Standardized DataFrame with [TIME, UN_RATE] columns.
        """
        full_mapping = dict(
            zip(
                ["time", "value"],
                [C.TIME, C.UN_RATE],
                strict=True,
            )
        )
        filename = self.finder.get_unemployment_path()
        return self.standardize(df, full_mapping, filename, [C.TIME, C.UN_RATE], 0)

    def save_unemployment_rate(self, **kwargs: Any) -> str | None:
        """Save unemployment rate data.

        Args:
            **kwargs: Arguments passed to get_unemployment_rate.

        Returns:
            Path to saved file, or None if save failed.
        """
        filename = self.finder.get_unemployment_path()
        if os.path.exists(filename):
            os.remove(filename)
        df = self.reader.update_df(
            filename, self.get_unemployment_rate(**kwargs), C.TIME, "%Y-%m"
        )
        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename
        return None

    def standardize_s2f_ratio(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize stock-to-flow ratio data.

        Args:
            df: Raw S2F DataFrame.

        Returns:
            Standardized DataFrame with [TIME, HALVING, RATIO] columns.
        """
        full_mapping = dict(
            zip(
                ["t", "o.daysTillHalving", "o.ratio"],
                [C.TIME, C.HALVING, C.RATIO],
                strict=True,
            )
        )
        filename = self.finder.get_s2f_path()
        df = self.standardize(
            df, full_mapping, filename, [C.TIME, C.HALVING, C.RATIO], 0
        )
        return df[self.get_indexer({C.TIME, C.HALVING, C.RATIO}, df.columns)]

    def get_s2f_ratio(self, timeframe: str = "max", **kwargs: Any) -> pd.DataFrame:
        """Get cached stock-to-flow ratio data.

        Args:
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments for subclass implementations.

        Returns:
            DataFrame with S2F ratio history.
        """
        df = self.reader.load_csv(self.finder.get_s2f_path())
        filtered = self.reader.data_in_timeframe(df, C.TIME, timeframe)[
            [C.TIME, C.HALVING, C.RATIO]
        ]
        return filtered

    def save_s2f_ratio(self, **kwargs: Any) -> str | None:
        """Save stock-to-flow ratio data.

        Args:
            **kwargs: Arguments passed to get_s2f_ratio.

        Returns:
            Path to saved file, or None if save failed.
        """
        filename = self.finder.get_s2f_path()

        if os.path.exists(filename):
            os.remove(filename)

        df = self.reader.update_df(
            filename, self.get_s2f_ratio(**kwargs), C.TIME, C.DATE_FMT
        )

        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename
        return None

    def standardize_diff_ribbon(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize difficulty ribbon data.

        Args:
            df: Raw difficulty ribbon DataFrame.

        Returns:
            Standardized DataFrame with moving average columns.
        """
        full_mapping = dict(
            zip(
                [
                    "t",
                    "o.ma9",
                    "o.ma14",
                    "o.ma25",
                    "o.ma40",
                    "o.ma60",
                    "o.ma90",
                    "o.ma128",
                    "o.ma200",
                ],
                [C.TIME] + C.MAs,
                strict=True,
            )
        )
        filename = self.finder.get_diff_ribbon_path()
        df = self.standardize(df, full_mapping, filename, [C.TIME] + C.MAs, 0)
        return df[self.get_indexer(set([C.TIME] + C.MAs), df.columns)]

    def get_diff_ribbon(self, timeframe: str = "max", **kwargs: Any) -> pd.DataFrame:
        """Get cached difficulty ribbon data.

        Args:
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments for subclass implementations.

        Returns:
            DataFrame with difficulty ribbon moving averages.
        """
        df = self.reader.load_csv(self.finder.get_diff_ribbon_path())
        filtered = self.reader.data_in_timeframe(df, C.TIME, timeframe)[
            [C.TIME] + C.MAs
        ]
        return filtered

    def save_diff_ribbon(self, **kwargs: Any) -> str | None:
        """Save difficulty ribbon data.

        Args:
            **kwargs: Arguments passed to get_diff_ribbon.

        Returns:
            Path to saved file, or None if save failed.
        """
        filename = self.finder.get_diff_ribbon_path()

        if os.path.exists(filename):
            os.remove(filename)

        df = self.reader.update_df(
            filename, self.get_diff_ribbon(**kwargs), C.TIME, C.DATE_FMT
        )

        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename
        return None

    def standardize_sopr(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize SOPR (Spent Output Profit Ratio) data.

        Args:
            df: Raw SOPR DataFrame.

        Returns:
            Standardized DataFrame with [TIME, SOPR] columns.
        """
        full_mapping = dict(
            zip(
                ["t", "v"],
                [C.TIME, C.SOPR],
                strict=True,
            )
        )
        filename = self.finder.get_sopr_path()
        df = self.standardize(df, full_mapping, filename, [C.TIME, C.SOPR], 1)
        return df[self.get_indexer({C.TIME, C.SOPR}, df.columns)]

    def get_sopr(self, timeframe: str = "max", **kwargs: Any) -> pd.DataFrame:
        """Get cached SOPR data.

        Args:
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments for subclass implementations.

        Returns:
            DataFrame with SOPR history.
        """
        df = self.reader.load_csv(self.finder.get_sopr_path())
        filtered = self.reader.data_in_timeframe(df, C.TIME, timeframe)[
            [C.TIME, C.SOPR]
        ]
        return filtered

    def save_sopr(self, **kwargs: Any) -> str | None:
        """Save SOPR data.

        Args:
            **kwargs: Arguments passed to get_sopr.

        Returns:
            Path to saved file, or None if save failed.
        """
        filename = self.finder.get_sopr_path()

        if os.path.exists(filename):
            os.remove(filename)

        df = self.reader.update_df(
            filename, self.get_sopr(**kwargs), C.TIME, C.DATE_FMT
        )

        self.writer.update_csv(filename, df)
        if os.path.exists(filename):
            return filename
        return None

    def standardize_ndx(self, df: pd.DataFrame) -> pd.DataFrame:
        """Standardize NDX (Nasdaq-100) constituency data.

        Args:
            df: Raw NDX DataFrame.

        Returns:
            Standardized DataFrame with current NDX constituents.
        """
        if df.empty:
            df = pd.DataFrame(columns=pd.Index([C.TIME, C.SYMBOL, C.DELTA]))
        df = df.sort_values(by=[C.TIME, C.SYMBOL]).drop_duplicates(
            C.SYMBOL, keep="last"
        )
        df = df[df[C.DELTA] == "+"].reset_index(drop=True)
        return df

    def get_saved_ndx(self) -> pd.DataFrame:
        """Get cached NDX constituency data.

        Returns:
            DataFrame with NDX constituency history.
        """
        df = self.reader.load_csv(self.finder.get_ndx_path())
        return df

    def get_ndx(self, date: datetime | None = None) -> pd.DataFrame:
        """Get NDX constituents as of a specific date.

        Args:
            date: Date to get constituents for (default: now).

        Returns:
            DataFrame with NDX constituents.
        """
        date = date or datetime.now()
        date_str = self.traveller.convert_date(date)
        df = self.get_saved_ndx()
        return self.standardize_ndx(df[df[C.TIME] <= date_str] if C.TIME in df else df)

    def get_latest_ndx(self, **kwargs: Any) -> pd.DataFrame:
        """Fetch latest NDX securities from Nasdaq, falling back to Wikipedia.

        Args:
            **kwargs: Arguments for retry logic (retries, delay).

        Returns:
            DataFrame with current NDX constituents.
        """
        try:
            symbols = self.try_again(func=self._get_nasdaq_ndx_symbols, **kwargs)
        except Exception as nasdaq_error:
            LOGGER.warning("Nasdaq NDX constituents unavailable: %s", nasdaq_error)
            try:
                symbols = self.try_again(func=self._get_wikipedia_ndx_symbols, **kwargs)
            except Exception as wikipedia_error:
                raise RuntimeError(
                    "No NDX constituent source succeeded "
                    f"(Nasdaq: {nasdaq_error}; Wikipedia: {wikipedia_error})"
                ) from wikipedia_error
            LOGGER.warning("Using Wikipedia NDX constituent fallback")
        today = datetime.today().strftime(C.DATE_FMT)
        return pd.DataFrame(
            {
                C.TIME: len(symbols) * [today],
                C.SYMBOL: symbols,
                C.DELTA: len(symbols) * ["+"],
            }
        )

    def _get_wikipedia_ndx_symbols(self) -> list[str]:
        """Fetch NDX security symbols from Wikipedia's dedicated list page."""
        response = requests.get(
            WIKIPEDIA_NDX_URL,
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=C.API_TIMEOUT,
        )
        response.raise_for_status()
        tables = pd.read_html(StringIO(response.text), attrs={"id": "constituents"})
        if not tables:
            raise ValueError("Wikipedia constituent table is missing")
        return self._validate_ndx_symbols(tables[0], "Ticker", "Wikipedia")

    def _get_nasdaq_ndx_symbols(self) -> list[str]:
        """Fetch NDX security symbols from Nasdaq's live JSON endpoint."""
        response = requests.get(
            NASDAQ_NDX_API_URL,
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=C.API_TIMEOUT,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Nasdaq returned a non-object response")
        status = payload.get("status")
        if not isinstance(status, dict) or status.get("rCode") != 200:
            raise ValueError("Nasdaq returned an unsuccessful status")
        data = payload.get("data")
        if not isinstance(data, dict):
            raise ValueError("Nasdaq response has no data")
        reported = data.get("totalrecords")
        rows_container = data.get("data")
        if not isinstance(rows_container, dict):
            raise ValueError("Nasdaq response has no row container")
        rows = rows_container.get("rows")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise ValueError("Nasdaq constituent rows are malformed")
        if isinstance(reported, bool) or not isinstance(reported, int):
            raise ValueError("Nasdaq record count is malformed")
        if reported != len(rows):
            raise ValueError(
                f"Nasdaq reported {reported} records but returned {len(rows)}"
            )
        timestamp = data.get("date")
        if not isinstance(timestamp, str):
            raise ValueError("Nasdaq response has no timestamp")
        try:
            updated = datetime.strptime(timestamp, "%b %d, %Y %I:%M %p")
        except ValueError:
            updated = datetime.strptime(timestamp, "%b %d, %Y")
        age = (datetime.today().date() - updated.date()).days
        if age < 0 or age > NDX_MAX_API_AGE_DAYS:
            raise ValueError(f"Nasdaq response is {age} days old")
        return self._validate_ndx_symbols(pd.DataFrame(rows), "symbol", "Nasdaq")

    @staticmethod
    def _validate_ndx_symbols(
        table: pd.DataFrame, column: str, source: str
    ) -> list[str]:
        """Normalize and validate a complete list of NDX security symbols."""
        if column not in table:
            raise ValueError(f"{source} constituent table has no {column} column")
        symbols = table[column].dropna().astype(str).str.strip().str.upper()
        invalid = symbols[~symbols.str.fullmatch(r"[A-Z][A-Z0-9.-]*")]
        if not invalid.empty:
            raise ValueError(f"{source} returned invalid symbols: {invalid.tolist()}")
        duplicates = symbols[symbols.duplicated()].tolist()
        if duplicates:
            raise ValueError(f"{source} returned duplicate symbols: {duplicates}")
        if not NDX_MIN_SECURITIES <= len(symbols) <= NDX_MAX_SECURITIES:
            raise ValueError(
                f"{source} returned {len(symbols)} securities; expected "
                f"{NDX_MIN_SECURITIES}-{NDX_MAX_SECURITIES}"
            )
        return symbols.tolist()

    def save_ndx(self, **kwargs: Any) -> str | None:
        """Save NDX constituency data with changes.

        Args:
            **kwargs: Arguments for get_latest_ndx.

        Returns:
            Path to saved file, or None if save failed.
        """
        filename = self.finder.get_ndx_path()

        if os.path.exists(filename):
            os.remove(filename)

        saved = self.get_saved_ndx()
        before = set(self.standardize_ndx(saved)[C.SYMBOL])
        after = set(self.get_latest_ndx(**kwargs)[C.SYMBOL])
        today = datetime.now().strftime(C.DATE_FMT)
        minus, plus = self.calculator.get_difference(before, after)
        union = list(minus.union(plus))
        to_append = pd.DataFrame(
            {
                C.TIME: [today] * len(union),
                C.SYMBOL: union,
                C.DELTA: ["+" if u in plus else "-" for u in union],
            }
        )
        df = (
            pd.concat([saved, to_append], ignore_index=True)
            .sort_values(by=[C.TIME, C.SYMBOL])
            .reset_index(drop=True)
        )
        self.writer.update_csv(filename, df)

        if os.path.exists(filename):
            return filename
        return None

    def log_api_call_time(self) -> None:
        """Record the timestamp of the last API call."""
        self.last_api_call_time = time()

    def obey_free_limit(self, free_delay: float) -> None:
        """Wait if needed to respect free tier rate limits.

        Args:
            free_delay: Minimum seconds between API calls.
        """
        if hasattr(self, "free") and self.free and hasattr(self, "last_api_call_time"):
            time_since_last_call = time() - self.last_api_call_time
            delay = free_delay - time_since_last_call
            if delay > 0:
                sleep(delay)


class Indices(MarketData):
    """Market data provider for index constituency data."""

    def __init__(self) -> None:
        """Initialize the Indices provider."""
        super().__init__()

    def get_ndx(self, date: datetime | None = None) -> pd.DataFrame:
        """Get NDX constituents combining cached and live data.

        Args:
            date: Date to get constituents for (default: now).

        Returns:
            DataFrame with NDX constituents.
        """
        date = date or datetime.now()
        old = super().get_ndx(date)
        date_str = self.traveller.convert_date(date)
        new = self.get_latest_ndx()
        new = new[new[C.TIME] <= date_str]
        df = pd.concat([old, new])
        return self.standardize_ndx(df)


class AlpacaData(MarketData):
    """Market data provider for Alpaca API."""

    def __init__(
        self,
        token: str | None = None,
        secret: str | None = None,
        free: bool = True,
        paper: bool = False,
    ) -> None:
        """Initialize the Alpaca data provider.

        Args:
            token: API key (default: from ALPACA env var).
            secret: API secret (default: from ALPACA_SECRET env var).
            free: Use free tier rate limits (default: True).
            paper: Use paper trading credentials (default: False).

        Raises:
            Exception: If credentials are missing.
        """
        super().__init__()
        token = token or os.environ.get("ALPACA")
        secret = secret or os.environ.get("ALPACA_SECRET")
        self.base = "https://data.alpaca.markets"
        self.token = os.environ.get("ALPACA_PAPER") if paper or C.TEST else token
        self.secret = (
            os.environ.get("ALPACA_PAPER_SECRET") if paper or C.TEST else secret
        )
        if not (self.token and self.secret):
            raise Exception("missing Alpaca credentials")
        self.provider = "alpaca"
        self.free = free

    def get_ohlc(
        self, symbol: str = "", timeframe: str = "max", **kwargs: Any
    ) -> pd.DataFrame:
        """Fetch OHLC data from Alpaca API.

        Args:
            symbol: The stock/crypto symbol.
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments.

        Returns:
            DataFrame with OHLC price history.

        Raises:
            Exception: If API request fails.
        """

        def _get_ohlc(symbol: str, timeframe: str = "max") -> pd.DataFrame:
            is_crypto = symbol in C.ALPC_CRYPTO_SYMBOLS
            version = "v1beta3" if is_crypto else "v2"
            page_token = None
            start, _ = self.traveller.convert_dates(timeframe)
            parts = [
                self.base,
                version,
                "crypto/us" if is_crypto else "stocks",
                "bars",
            ]
            url = "/".join(parts)
            pre_params = {
                "symbols": symbol,
                "timeframe": "1D",
                "start": start,
                # An explicit end is omitted deliberately. Alpaca requires it to be
                # at least 15 minutes behind current UTC, formatted 2025-01-01T00:00:00Z.
                "limit": 10000,
            } | ({} if is_crypto else {"adjustment": "all"})
            headers = {
                "APCA-API-KEY-ID": self.token,
                "APCA-API-SECRET-KEY": self.secret,
            }
            results: list[dict[str, Any]] = []
            seen_page_tokens: set[str] = set()
            while True:
                self.obey_free_limit(C.ALPACA_FREE_DELAY)
                try:
                    post_params = {"page_token": page_token} if page_token else {}
                    params = pre_params | post_params
                    response = requests.get(
                        url, params, headers=headers, timeout=C.API_TIMEOUT
                    )
                    if not response.ok:
                        raise Exception(
                            "Invalid response from Alpaca for OHLC",
                            response.status_code,
                            response.text,
                        )
                    data = response.json()
                    if data.get("bars") and data["bars"].get(symbol):
                        results += data["bars"][symbol]
                finally:
                    self.log_api_call_time()
                next_page_token = data.get("next_page_token")
                if next_page_token:
                    if next_page_token in seen_page_tokens:
                        raise ValueError(
                            f"Alpaca repeated page token for {symbol}: "
                            f"{next_page_token}"
                        )
                    seen_page_tokens.add(next_page_token)
                    page_token = next_page_token
                else:
                    break
            df = pd.DataFrame(results)
            columns = {
                "t": "date",
                "o": "open",
                "h": "high",
                "l": "low",
                "c": "close",
                "v": "volume",
                "vw": "average",
                "n": "trades",
            }
            df = df.rename(columns=columns)
            df["date"] = (
                pd.to_datetime(df["date"]).dt.tz_convert(C.TZ).dt.tz_localize(None)
            )
            storage_symbol = C.ALPC_TO_POLY_CRYPTO.get(symbol, symbol)
            df = self.standardize_ohlc(storage_symbol, df)
            return self.reader.data_in_timeframe(df, C.TIME, timeframe)

        return self.try_again(
            func=_get_ohlc, symbol=symbol, timeframe=timeframe, **kwargs
        )

    def save_ohlc(self, **kwargs: Any) -> str | None:
        """Save OHLC data, converting Alpaca crypto symbols to Polygon format.

        Overrides base save_ohlc to convert Alpaca crypto symbols
        (e.g., 'BTC/USD') to Polygon format (e.g., 'X%3ABTCUSD')
        for S3-safe file paths.

        Args:
            **kwargs: Must include 'symbol'. Other args passed to parent.

        Returns:
            Path to saved file, or None if save failed.
        """
        storage_symbol = C.ALPC_TO_POLY_CRYPTO.get(kwargs["symbol"], kwargs["symbol"])
        return self._save_ohlc(storage_symbol, **kwargs)


class Polygon(MarketData):
    """Market data provider for Polygon.io API."""

    def __init__(self, token: str | None = None, free: bool = True) -> None:
        """Initialize the Polygon data provider.

        Args:
            token: API key (default: from POLYGON env var).
            free: Use free tier rate limits (default: True).
        """
        super().__init__()
        token = token or os.environ.get("POLYGON")
        self.client = RESTClient(token)
        self.provider = "polygon"
        self.free = free

    def paginate(
        self,
        gen: Generator[Any, None, None] | Iterator[Any],
        apply: Callable[[Any], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Paginate through API results with rate limiting.

        Args:
            gen: Generator or iterator yielding API response items.
            apply: Function to transform each item.

        Returns:
            List of transformed results.
        """
        results: list[dict[str, Any]] = []
        for idx, item in enumerate(gen):
            if idx % C.POLY_MAX_LIMIT == 0:
                self.log_api_call_time()
            if self.free and idx % C.POLY_MAX_LIMIT == C.POLY_MAX_LIMIT - 1:
                sleep(C.POLY_FREE_DELAY)
            results.append(apply(item))
        return results

    def get_dividends(
        self, symbol: str = "", timeframe: str = "max", **kwargs: Any
    ) -> pd.DataFrame:
        """Fetch dividend data from Polygon API.

        Args:
            symbol: The stock symbol.
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments.

        Returns:
            DataFrame with dividend history.
        """

        def _get_dividends(symbol: str, timeframe: str = "max") -> pd.DataFrame:
            self.obey_free_limit(C.POLY_FREE_DELAY)
            try:
                start, _ = self.traveller.convert_dates(timeframe)
                response = self.paginate(
                    self.client.list_dividends(
                        symbol,
                        ex_dividend_date_gte=start,
                        order="desc",
                        sort="ex_dividend_date",
                        limit=C.POLY_MAX_LIMIT,
                    ),
                    lambda div: {
                        "exDate": div.ex_dividend_date,
                        "paymentDate": div.pay_date,
                        "declaredDate": div.declaration_date,
                        "amount": div.cash_amount,
                    },
                )
            finally:
                self.log_api_call_time()
            raw = pd.DataFrame(response)
            df = self.standardize_dividends(symbol, raw)
            return self.reader.data_in_timeframe(df, C.EX, timeframe)

        return self.try_again(
            func=_get_dividends, symbol=symbol, timeframe=timeframe, **kwargs
        )

    def get_splits(
        self, symbol: str = "", timeframe: str = "max", **kwargs: Any
    ) -> pd.DataFrame:
        """Fetch split data from Polygon API.

        Args:
            symbol: The stock symbol.
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments.

        Returns:
            DataFrame with split history.
        """

        def _get_splits(symbol: str, timeframe: str = "max") -> pd.DataFrame:
            self.obey_free_limit(C.POLY_FREE_DELAY)
            try:
                start, _ = self.traveller.convert_dates(timeframe)
                response = self.paginate(
                    self.client.list_splits(
                        symbol,
                        execution_date_gte=start,
                        order="desc",
                        sort="execution_date",
                        limit=C.POLY_MAX_LIMIT,
                    ),
                    lambda split: {
                        "exDate": split.execution_date,
                        "ratio": split.split_from / split.split_to,
                    },
                )
            finally:
                self.log_api_call_time()
            raw = pd.DataFrame(response)
            df = self.standardize_splits(symbol, raw)
            return self.reader.data_in_timeframe(df, C.EX, timeframe)

        return self.try_again(
            func=_get_splits, symbol=symbol, timeframe=timeframe, **kwargs
        )

    def get_ohlc(
        self, symbol: str = "", timeframe: str = "max", **kwargs: Any
    ) -> pd.DataFrame:
        """Fetch OHLC data from Polygon API.

        Args:
            symbol: The stock/crypto symbol.
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments.

        Returns:
            DataFrame with OHLC price history.
        """

        def _get_ohlc(symbol: str, timeframe: str = "max") -> pd.DataFrame:
            is_crypto = symbol.find("X%3A") == 0
            formatted_start, formatted_end = self.traveller.convert_dates(timeframe)
            self.obey_free_limit(C.POLY_FREE_DELAY)
            try:
                response = self.client.get_aggs(
                    symbol,
                    1,
                    "day",
                    from_=formatted_start,
                    to=formatted_end,
                    adjusted=True,
                    limit=C.POLY_MAX_AGGS_LIMIT,
                )
            finally:
                self.log_api_call_time()

            raw = [vars(item) for item in response]
            columns = {"timestamp": "date", "vwap": "average", "transactions": "trades"}
            df = pd.DataFrame(raw).rename(columns=columns)
            if is_crypto:
                df["date"] = pd.to_datetime(df["date"], unit="ms")
            else:
                df["date"] = (
                    pd.to_datetime(df["date"], unit="ms")
                    .dt.tz_localize("UTC")
                    .dt.tz_convert(C.TZ)
                    .dt.tz_localize(None)
                )
            df = self.standardize_ohlc(symbol, df)
            return self.reader.data_in_timeframe(df, C.TIME, timeframe)

        return self.try_again(
            func=_get_ohlc, symbol=symbol, timeframe=timeframe, **kwargs
        )

    def get_intraday(
        self,
        symbol: str = "",
        min: int = 1,  # noqa: A002
        timeframe: str = "max",
        extra_hrs: bool = False,
        **kwargs: Any,
    ) -> Generator[pd.DataFrame, None, None] | None:
        """Fetch intraday data from Polygon API.

        Args:
            symbol: The stock/crypto symbol.
            min: Minute interval for data (default: 1).
            timeframe: Time range for data (default: "max").
            extra_hrs: Include extended hours data (default: False).
            **kwargs: Additional arguments.
            **kwargs: Must include 'symbol'. Optional 'min', 'timeframe', 'extra_hrs'.

        Returns:
            Generator yielding DataFrames with intraday OHLC data.
        """

        def _get_intraday(
            symbol: str,
            min: int = 1,  # noqa: A002
            timeframe: str = "max",
            extra_hrs: bool = True,
        ) -> Generator[pd.DataFrame, None, None]:
            is_crypto = symbol.find("X%3A") == 0
            dates = self.traveller.dates_in_range(timeframe)
            if dates == []:
                raise Exception(f"No dates in timeframe: {timeframe}.")

            for _, date in enumerate(dates):
                self.obey_free_limit(C.POLY_FREE_DELAY)
                try:
                    response = self.client.get_aggs(
                        symbol,
                        min,
                        "minute",
                        from_=date,
                        to=date,
                        adjusted=True,
                        limit=C.POLY_MAX_AGGS_LIMIT,
                    )
                except (
                    Exception
                ):  # NoResultsError may not be available in all polygon versions
                    # Weekends and holidays have no bars. Skip the date rather
                    # than break the loop over the rest of the timeframe.
                    continue
                finally:
                    self.log_api_call_time()

                raw = [vars(item) for item in response]
                columns = {
                    "timestamp": "date",
                    "vwap": "average",
                    "transactions": "trades",
                }
                df = pd.DataFrame(raw).rename(columns=columns)
                if is_crypto:
                    df["date"] = pd.to_datetime(df["date"], unit="ms")
                else:
                    df["date"] = (
                        pd.to_datetime(df["date"], unit="ms")
                        .dt.tz_localize("UTC")
                        .dt.tz_convert(C.TZ)
                        .dt.tz_localize(None)
                    )
                filename = self.finder.get_intraday_path(symbol, date, self.provider)
                df = self.standardize_ohlc(symbol, df, filename)
                df = df[df[C.TIME].dt.strftime(C.DATE_FMT) == date]
                yield df

        return self.try_again(
            func=_get_intraday,
            symbol=symbol,
            min=min,
            timeframe=timeframe,
            extra_hrs=extra_hrs,
            **kwargs,
        )


class LaborStats(MarketData):
    """Market data provider for Bureau of Labor Statistics API."""

    def __init__(self) -> None:
        """Initialize the BLS data provider."""
        super().__init__()
        self.base = "https://api.bls.gov"
        self.version = "v2"
        self.token = os.environ.get("BLS")
        self.provider = "bls"

    def get_unemployment_rate(
        self, timeframe: str = "max", **kwargs: Any
    ) -> pd.DataFrame:
        """Fetch unemployment rate from BLS API.

        Args:
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments.

        Returns:
            DataFrame with unemployment rate history.

        Raises:
            Exception: If API request fails.
        """

        def _get_unemployment_rate(timeframe: str) -> pd.DataFrame:
            start, end = self.traveller.convert_dates(timeframe, "%Y")

            parts = [self.base, "publicAPI", self.version, "timeseries", "data"]
            url = "/".join(parts)
            params = {
                "registrationkey": self.token,
                "startyear": start,
                "endyear": end,
                "seriesid": "LNS14000000",
            }

            response = requests.post(url, data=params)

            if response.ok and response.json()["status"] == "REQUEST_SUCCEEDED":
                payload = response.json()
                if payload["status"] == "REQUEST_SUCCEEDED":
                    data = payload["Results"]["series"][0]["data"]
                else:
                    raise Exception(
                        f"""
                        Invalid response from BLS because {payload.get("message", ["Unknown error"])[0]}
                        """
                    )
            else:
                raise Exception(
                    "Invalid response from BLS for unemployment rate",
                    response.status_code,
                    response.json(),
                )

            df = pd.DataFrame(data)
            df["time"] = df["year"] + "-" + df["period"].str.slice(start=1)

            df = self.standardize_unemployment(df)
            return self.reader.data_in_timeframe(df, C.TIME, timeframe)

        return self.try_again(
            func=_get_unemployment_rate, timeframe=timeframe, **kwargs
        )


class Glassnode(MarketData):
    """Market data provider for Glassnode crypto analytics API."""

    def __init__(self, use_cookies: bool = False) -> None:
        """Initialize the Glassnode data provider.

        Args:
            use_cookies: Use browser-based authentication (default: False).
        """
        super().__init__()
        self.base = "https://api.glassnode.com"
        self.version = "v1"
        self.token = os.environ.get("GLASSNODE")
        self.provider = "glassnode"
        self.use_cookies = use_cookies
        if self.use_cookies:
            self.use_auth()

    def use_auth(self) -> None:
        """Authenticate via browser to get session cookies."""
        options = ChromeOptions()
        options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.set_capability("goog:loggingPrefs", {"performance": "ALL"})

        driver = webdriver.Chrome(options=options)
        driver.get("https://studio.glassnode.com/auth/login")
        delay = 10

        def get_element(id: str) -> Any:  # noqa: A002
            return WebDriverWait(driver, delay).until(
                EC.presence_of_element_located((By.ID, id))
            )

        email = get_element("email")
        email.send_keys(os.environ["RH_USERNAME"])
        password = get_element("current-password")
        password.send_keys(os.environ["GLASSNODE_PASS"])
        password.send_keys(Keys.ENTER)
        sleep(15)
        driver.get("https://studio.glassnode.com/metrics")
        sleep(5)
        url = (
            "https://api.glassnode.com/v1/metrics/market/price_usd_close"
            "?a=BTC&i=24h&referer=charts"
        )
        driver.get(url)
        sleep(5)

        raw_logs = driver.get_log("performance")
        logs = [json.loads(raw_log["message"])["message"] for raw_log in raw_logs]

        def log_filter(log_: dict[str, Any]) -> bool:
            return (
                log_["method"] == "Network.requestWillBeSent"
                and log_["params"]["request"]["url"] == url
                and log_["params"]["request"]["method"] == "GET"
            )

        self.headers = [
            log["params"]["request"]["headers"] for log in filter(log_filter, logs)
        ][-1]
        self.cookies = {
            cookie["name"]: cookie["value"] for cookie in driver.get_cookies()
        }

    def make_request(self, url: str) -> requests.Response:
        """Make authenticated request to Glassnode API.

        Args:
            url: API endpoint URL.

        Returns:
            Response object from the API.
        """
        params: dict[str, str] = {
            "a": "BTC",
            "c": "native",
            "i": "24h",
            "referer": "charts",
        }
        if self.use_cookies:
            headers = self.headers
            cookies = self.cookies
        else:
            params["api_key"] = self.token or ""
            headers = {}
            cookies = {}
        response = requests.get(url, params=params, headers=headers, cookies=cookies)
        sleep(random() * 5)
        return response

    def get_s2f_ratio(self, timeframe: str = "max", **kwargs: Any) -> pd.DataFrame:
        """Fetch stock-to-flow ratio from Glassnode API.

        Args:
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments.

        Returns:
            DataFrame with S2F ratio history.

        Raises:
            Exception: If API request fails.
        """

        def _get_s2f_ratio(timeframe: str) -> pd.DataFrame:
            parts = [
                self.base,
                self.version,
                "metrics",
                "indicators",
                "stock_to_flow_ratio",
            ]
            url = "/".join(parts)
            empty = pd.DataFrame()
            response = self.make_request(url)

            if response.ok:
                data = response.json()
            else:
                raise Exception(
                    "Invalid response from Glassnode for S2F Ratio", response
                )

            if data == []:
                return empty

            df = pd.json_normalize(data)
            df["t"] = pd.to_datetime(df["t"], unit="s")
            df = self.standardize_s2f_ratio(df)
            return self.reader.data_in_timeframe(df, C.TIME, timeframe)

        return self.try_again(func=_get_s2f_ratio, timeframe=timeframe, **kwargs)

    def get_diff_ribbon(self, timeframe: str = "max", **kwargs: Any) -> pd.DataFrame:
        """Fetch difficulty ribbon from Glassnode API.

        Args:
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments.

        Returns:
            DataFrame with difficulty ribbon moving averages.

        Raises:
            Exception: If API request fails.
        """

        def _get_diff_ribbon(timeframe: str) -> pd.DataFrame:
            parts = [
                self.base,
                self.version,
                "metrics",
                "indicators",
                "difficulty_ribbon",
            ]
            url = "/".join(parts)
            empty = pd.DataFrame()
            response = self.make_request(url)

            if response.ok:
                data = response.json()
            else:
                raise Exception(
                    "Invalid response from Glassnode for Difficulty Ribbon", response
                )

            if data == []:
                return empty

            df = pd.json_normalize(data)
            df["t"] = pd.to_datetime(df["t"], unit="s")
            df = self.standardize_diff_ribbon(df)
            return self.reader.data_in_timeframe(df, C.TIME, timeframe)

        return self.try_again(func=_get_diff_ribbon, timeframe=timeframe, **kwargs)

    def get_sopr(self, timeframe: str = "max", **kwargs: Any) -> pd.DataFrame:
        """Fetch SOPR from Glassnode API.

        Args:
            timeframe: Time range for data (default: "max").
            **kwargs: Additional arguments.

        Returns:
            DataFrame with SOPR history.

        Raises:
            Exception: If API request fails.
        """

        def _get_sopr(timeframe: str) -> pd.DataFrame:
            parts = [self.base, self.version, "metrics", "indicators", "sopr"]
            url = "/".join(parts)
            empty = pd.DataFrame()
            response = self.make_request(url)

            if response.ok:
                data = response.json()
            else:
                raise Exception("Invalid response from Glassnode for SOPR", response)

            if data == []:
                return empty

            df = pd.json_normalize(data)
            df["t"] = pd.to_datetime(df["t"], unit="s")
            df = self.standardize_sopr(df)
            return self.reader.data_in_timeframe(df, C.TIME, timeframe)

        return self.try_again(func=_get_sopr, timeframe=timeframe, **kwargs)
