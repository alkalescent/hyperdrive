"""Constants, configuration values, and path utilities for hyperdrive."""

import os
from pathlib import Path

import vectorbt as vbt
from dotenv import find_dotenv, load_dotenv
from pytz import timezone

load_dotenv(find_dotenv("config.env"))


def get_env_int(var_name: str, default: int | None = None) -> int | None:
    """Get an environment variable as an integer.

    Args:
        var_name: Name of the environment variable.
        default: Default value if variable is not set or not numeric.

    Returns:
        The integer value or default.
    """
    return (
        int(os.environ[var_name])
        if os.environ.get(var_name) and os.environ[var_name].isnumeric()
        else default
    )


def get_env_bool(var_name: str) -> bool:
    """Get an environment variable as a boolean.

    Args:
        var_name: Name of the environment variable.

    Returns:
        True if the variable is set to 'true' (case-insensitive).
    """
    return bool(os.environ.get(var_name) and os.environ[var_name].lower() == "true")


# Environment
DEV = get_env_bool("DEV")
CI = get_env_bool("CI")
TEST = get_env_bool("TEST")

# File Paths
# data
DATA_DIR = "data"
API_DIR = "api"
DEV_DIR = "dev"
DIV_DIR = "dividends"
SPLT_DIR = "splits"
OHLC_DIR = "ohlc"
SENT_DIR = "sentiment"
INTRA_DIR = "intraday"
IDX_DIR = "indices"
# providers
POLY_DIR = "polygon"
ALPACA_DIR = "alpaca"
# models
MODELS_DIR = "models"

folders = {"polygon": POLY_DIR, "alpaca": ALPACA_DIR}

# Column Names
# Symbols / Generic
SYMBOL = "Symbol"
NAME = "Name"

# Dividends
DIV = "Div"
EX = "Ex"  # Ex Dividend Date
DEC = "Dec"  # Declaration Date
PAY = "Pay"  # Payment Date

# Splits
RATIO = "Ratio"

# OHLCV
# DATE = 'Date'
TIME = "Time"
OPEN = "Open"
HIGH = "High"
LOW = "Low"
CLOSE = "Close"
VOL = "Vol"
AVG = "Avg"
TRADES = "Trades"

# Time
TZ = timezone("US/Eastern")
UTC = timezone("UTC")
DATE_FMT = "%Y-%m-%d"
TIME_FMT = "%H:%M"
PRECISE_TIME_FMT = "%H:%M:%S"

# Sentiment
POS = "Pos"
NEG = "Neg"
DELTA = "Delta"

# Unemployment
UN_RATE = "UnRate"

# S2F
HALVING = "Halving"

# Difficulty Ribbon
MAs = ["MA9", "MA14", "MA25", "MA40", "MA60", "MA90", "MA128", "MA200"]

# SOPR
SOPR = "SOPR"

# Oracle
SIG = "Sig"
BUY = "BUY"
SELL = "SELL"

# API
BAL = "Bal"
NAME = "Name"
ABS_TOL = vbt.utils.math_.abs_tol

# Model
MAX_MODEL_AGE_DAYS = 90  # 3 months
MIN_MODEL_ACCURACY = 0.925

# Misc
POLY_CRYPTO_SYMBOLS = [
    "X%3ABTCUSD",
    "X%3AETHUSD",
    "X%3ALTCUSD",
    "X%3AXMRUSD",
    "X%3AIOTUSD",
]

ALPC_CRYPTO_SYMBOLS = ["BTC/USD", "ETH/USD", "LTC/USD"]

SENTIMENT_SYMBOLS_IGNORE = {
    "SPYD",
    "VWDRY",
    "BPMP",
    "FOX",
    "YYY",
    "SDIV",
    "DIV",
    "SHECY",
    "PALL",
}

DEFAULT_RETRIES = 2
DEFAULT_DELAY = 2
POLY_FREE_DELAY = 13
POLY_MAX_LIMIT = 1000
POLY_MAX_AGGS_LIMIT = 50000
FEW = 3
FEW_DAYS = str(FEW) + "d"
SCRIPT_FAILURE_THRESHOLD = 0.95

ALPACA_FREE_DELAY = 0.5

# Exchanges
BINANCE = "BINANCE"
KRAKEN = "KRAKEN"
PREF_EXCHANGE = os.environ.get("PREF_EXCHANGE") and os.environ["PREF_EXCHANGE"].upper()

# fee is 0.1%
BINANCE_FEE = 0.001
KRAKEN_SYMBOLS = {"BTC": "XXBT", "USD": "ZUSD"}
BINANCE_TEST_SPEND = 0.01
KRAKEN_TEST_SPEND = 0.005


class PathFinder:
    """Utility class for constructing file paths.

    Provides methods for generating paths to various data files
    including symbols, dividends, OHLC data, and more.
    """

    def make_path(self, path: str) -> None:
        """Create parent directories for a path if they don't exist.

        Args:
            path: File path whose parent directories should be created.
        """
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    def get_symbols_path(self) -> str:
        """Get the path for the symbols reference CSV.

        Returns:
            Path to the symbols CSV file.
        """
        return os.path.join(DATA_DIR, "symbols.csv")

    def get_dividends_path(self, symbol: str, provider: str = POLY_DIR) -> str:
        """Get the path to a symbol's dividends CSV.

        Args:
            symbol: Stock symbol.
            provider: Data provider directory name.

        Returns:
            Path to the dividends CSV file.
        """
        return os.path.join(
            DATA_DIR, DIV_DIR, folders[provider], f"{symbol.upper()}.csv"
        )

    def get_splits_path(self, symbol: str, provider: str = POLY_DIR) -> str:
        """Get the path to a symbol's stock splits CSV.

        Args:
            symbol: Stock symbol.
            provider: Data provider directory name.

        Returns:
            Path to the splits CSV file.
        """
        return os.path.join(
            DATA_DIR, SPLT_DIR, folders[provider], f"{symbol.upper()}.csv"
        )

    def get_ohlc_path(self, symbol: str, provider: str = POLY_DIR) -> str:
        """Get the path to a symbol's OHLC data CSV.

        Args:
            symbol: Stock symbol.
            provider: Data provider directory name.

        Returns:
            Path to the OHLC CSV file.
        """
        return os.path.join(
            DATA_DIR, OHLC_DIR, folders[provider], f"{symbol.upper()}.csv"
        )

    def get_intraday_path(
        self, symbol: str, date: str, provider: str = POLY_DIR
    ) -> str:
        """Get the path to a symbol's intraday OHLC data CSV.

        Args:
            symbol: Stock symbol.
            date: Date string for the intraday data.
            provider: Data provider directory name.

        Returns:
            Path to the intraday CSV file.
        """
        return os.path.join(
            DATA_DIR, INTRA_DIR, folders[provider], symbol.upper(), f"{date}.csv"
        )

    def get_unemployment_path(self) -> str:
        """Get the path to the unemployment data CSV.

        Returns:
            Path to the unemployment CSV file.
        """
        return os.path.join(DATA_DIR, "unemployment.csv")

    def get_s2f_path(self) -> str:
        """Get the path to the stock-to-flow data CSV.

        Returns:
            Path to the S2F CSV file.
        """
        return os.path.join(DATA_DIR, "s2f.csv")

    def get_diff_ribbon_path(self) -> str:
        """Get the path to the difficulty ribbon data CSV.

        Returns:
            Path to the difficulty ribbon CSV file.
        """
        return os.path.join(DATA_DIR, "diff_ribbon.csv")

    def get_sopr_path(self) -> str:
        """Get the path to the SOPR data CSV.

        Returns:
            Path to the SOPR CSV file.
        """
        return os.path.join(DATA_DIR, "sopr.csv")

    def get_signals_path(self) -> str:
        """Get the path to the trading signals CSV.

        Returns:
            Path to the signals CSV file.
        """
        return os.path.join(MODELS_DIR, "latest", "signals.csv")

    def get_orders_path(self) -> str:
        """Get the path to the orders CSV.

        Returns:
            Path to the orders CSV file.
        """
        return os.path.join(MODELS_DIR, "latest", "orders.csv")

    def get_new_orders_path(self, provider: str) -> str:
        """Get the path to new orders CSV for a provider.

        Args:
            provider: Data provider name.

        Returns:
            Path to the new orders CSV file.
        """
        return os.path.join(DATA_DIR, "orders", f"{provider}.csv")

    def get_api_path(self, endpoint: str) -> str:
        """Get the path to an API response JSON file.

        Args:
            endpoint: API endpoint name.

        Returns:
            Path to the API JSON file.
        """
        return os.path.join(
            DATA_DIR,
            API_DIR,
            f"{endpoint}.json",
        )

    def get_ndx_path(self) -> str:
        """Get the path to the NASDAQ index data CSV.

        Returns:
            Path to the NDX CSV file.
        """
        return os.path.join(DATA_DIR, IDX_DIR, "ndx.csv")

    def get_all_paths(self, path: str, truncate: bool = False) -> list[str]:
        """Get all file paths under a directory.

        Args:
            path: Root directory to search.
            truncate: If True, remove the root path prefix from results.

        Returns:
            List of file paths, excluding cache and temp files.
        """
        paths = []
        for root, _, files in os.walk(path):
            for file in files:
                curr_path = os.path.join(root, file)[len(path) + 1 if truncate else 0 :]
                to_skip = ["__pycache__/", ".pytest", ".git/", ".ipynb", ".env"]
                keep = [skip not in curr_path for skip in to_skip]
                # remove caches but keep workflows
                if all(keep) or ".github" in curr_path:
                    paths.append(curr_path)
        return paths
