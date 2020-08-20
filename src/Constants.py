import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()
# Environment
DEV = bool(os.environ.get('DEV'))

# File Paths
DATA_DIR = 'data'
DEV_DIR = 'dev'
DIV_DIR = 'dividends'
SPLT_DIR = 'splits'
FULL_DIV_DIR = os.path.join(DATA_DIR, DIV_DIR)

# Column Names
# Symbols / Generic
SYMBOL = 'Symbol'
NAME = 'Name'
DATE = 'Date'

# Dividends
DIV = 'Div'
EX = 'Ex'    # Ex Dividend Date
DEC = 'Dec'  # Declaration Date
PAY = 'Pay'  # Payment Date


class PathFinder:
    def make_path(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)

    def get_symbols_path(self):
        # return the path for the symbols reference csv
        return os.path.join(
            DATA_DIR,
            'symbols.csv'
        )

    def get_dividends_path(self, symbol):
        # given a symbol
        # return the path to its csv
        return os.path.join(
            DATA_DIR,
            DIV_DIR,
            f'{symbol.upper()}.csv'
        )

    def get_splits_path(self, symbol):
        # given a symbol
        # return the path to its stock splits
        return os.path.join(
            DATA_DIR,
            SPLT_DIR,
            f'{symbol.upper()}.csv'
        )

    def get_all_paths(self, path, truncate=False):
        # given a path, get all sub paths
        paths = []
        for root, _, files in os.walk(path):
            for file in files:
                curr_path = os.path.join(root, file)[
                    len(path) + 1 if truncate else 0:]
                to_skip = ['__pycache__/', '.pytest',
                           '.git/', '.ipynb', '.env']
                keep = [skip not in curr_path for skip in to_skip]
                # remove caches but keep workflows
                if all(keep) or '.github' in curr_path:
                    # print(curr_path)
                    paths.append(curr_path)
        return paths
