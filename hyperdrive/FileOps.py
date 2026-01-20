"""File read and write operations for CSV, JSON, and pickle files."""

import json
import os
import pickle
import time
from datetime import datetime
from typing import Any

import pandas as pd
import polars as pl

from .Constants import TZ
from .Storage import Store
from .TimeMachine import TimeTraveller


class FileReader:
    """File reading operations with S3 synchronization.

    Handles reading CSV, JSON, and pickle files with automatic
    download from S3 when local files are stale.

    Attributes:
        store: Store instance for S3 operations.
        traveller: TimeTraveller instance for date calculations.
    """

    def __init__(self) -> None:
        """Initialize the FileReader with storage and time utilities."""
        self.store = Store()
        self.traveller = TimeTraveller()

    def should_be_updated(self, filename: str) -> bool:
        """Check if a file should be updated from S3.

        Args:
            filename: Path to the file to check.

        Returns:
            True if file doesn't exist or is older than one day.
        """
        one_day = 60 * 60 * 24
        now = datetime.fromtimestamp(time.time())
        file_exists = os.path.exists(filename)

        if file_exists:
            then = datetime.fromtimestamp(os.path.getmtime(filename))
            delta = now - then
            last_modified = delta.total_seconds()
        return not file_exists or last_modified > one_day

    def load_json(self, filename: str) -> dict[str, Any]:
        """Load a JSON file as a dictionary.

        Args:
            filename: Path to the JSON file.

        Returns:
            Dictionary containing the JSON data.
        """
        if self.should_be_updated(filename):
            self.store.download_file(filename)
        with open(filename) as file:
            return json.load(file)

    def load_csv(self, filename: str) -> pd.DataFrame:
        """Load a CSV file as a DataFrame.

        Uses polars internally for faster I/O, returns pandas
        for backward compatibility.

        Args:
            filename: Path to the CSV file.

        Returns:
            DataFrame containing the CSV data.

        Raises:
            pd.errors.EmptyDataError: If the CSV file is empty.
            FileNotFoundError: If the file doesn't exist.
        """
        try:
            if self.should_be_updated(filename):
                self.store.download_file(filename)
            # Use polars for fast CSV reading, convert to pandas for compatibility
            df_pl = pl.read_csv(filename)
            df = df_pl.to_pandas()
            # Round numeric columns to avoid floating point precision issues
            numeric_cols = df.select_dtypes(include=["float64", "float32"]).columns
            df[numeric_cols] = df[numeric_cols].round(10)
        except pl.exceptions.NoDataError:
            print(f"{filename} is an empty csv file.")
            raise pd.errors.EmptyDataError(
                f"{filename} is an empty csv file."
            ) from None
        except FileNotFoundError:
            print(f"{filename} does not exist locally.")
            raise
        except pd.errors.EmptyDataError:
            raise
        except BaseException:
            df = pd.DataFrame()
        return df

    def load_csv_polars(self, filename: str) -> pl.DataFrame:
        """Load a CSV file as a Polars DataFrame.

        For internal use where polars DataFrames are preferred.

        Args:
            filename: Path to the CSV file.

        Returns:
            Polars DataFrame containing the CSV data.
        """
        if self.should_be_updated(filename):
            self.store.download_file(filename)
        return pl.read_csv(filename)

    def check_update(self, filename: str, df: pd.DataFrame) -> bool:
        """Check if a CSV file needs to be updated with new data.

        Args:
            filename: Path to the CSV file.
            df: New DataFrame to compare against.

        Returns:
            True if the new DataFrame has at least as many rows as the file.
        """
        return len(df) >= len(self.load_csv(filename))

    def update_df(
        self,
        filename: str,
        new: pd.DataFrame,
        column: str,
        save_fmt: str | None = None,
    ) -> pd.DataFrame:
        """Merge new data with existing CSV data.

        Uses polars internally for faster concat/dedup operations.

        Args:
            filename: Path to the CSV file.
            new: New DataFrame to merge.
            column: Column name to use for deduplication.
            save_fmt: Optional date format for saving.

        Returns:
            Merged DataFrame with new entries taking precedence.
        """
        old = self.load_csv(filename)
        if not old.empty:
            old[column] = pd.to_datetime(old[column])
            new[column] = pd.to_datetime(new[column])
            # preference to new entries over old
            old = old[~old[column].isin(new[column])]
            new = pd.concat([old, new], ignore_index=True)
        if save_fmt:
            new[column] = pd.to_datetime(new[column]).dt.strftime(save_fmt)
        return new

    def check_file_exists(self, filename: str) -> bool:
        """Check if a file exists both locally and in S3.

        Args:
            filename: Path to the file.

        Returns:
            True if the file exists in both locations.
        """
        return os.path.exists(filename) and self.store.key_exists(filename)

    def data_in_timeframe(
        self, df: pd.DataFrame, col: str, timeframe: str = "max"
    ) -> pd.DataFrame:
        """Filter DataFrame to data within a timeframe.

        Uses polars internally for faster filtering.

        Args:
            df: DataFrame to filter.
            col: Date column name.
            timeframe: Timeframe string (e.g., '1y', '30d', 'max').

        Returns:
            Filtered DataFrame with dates within the timeframe.
        """
        if col not in df:
            return df
        delta = self.traveller.convert_delta(timeframe)
        df[col] = pd.to_datetime(df[col]).dt.tz_localize(TZ)
        today = datetime.now(TZ)
        filtered = df[
            df[col].apply(lambda date: date.strftime("%Y-%m-%d"))
            >= pd.to_datetime(today - delta).strftime("%Y-%m-%d")
        ].copy(deep=True)
        filtered[col] = filtered[col].dt.tz_localize(None)
        return filtered

    def load_pickle(self, filename: str) -> Any:
        """Load a pickled object from file.

        Args:
            filename: Path to the pickle file.

        Returns:
            The unpickled object.
        """
        if self.should_be_updated(filename):
            self.store.download_file(filename)
        with open(filename, "rb") as file:
            return pickle.load(file)


class FileWriter:
    """File writing operations with S3 synchronization.

    Handles writing CSV, JSON, and pickle files with automatic
    upload to S3.

    Attributes:
        store: Store instance for S3 operations.
    """

    def __init__(self) -> None:
        """Initialize the FileWriter with storage utilities."""
        self.store = Store()

    def save_json(self, filename: str, data: dict[str, Any]) -> bool:
        """Save data as a JSON file and upload to S3.

        Args:
            filename: Path to save the JSON file.
            data: Dictionary data to save.

        Returns:
            True on success.
        """
        self.store.finder.make_path(filename)
        with open(filename, "w") as file:
            json.dump(data, file, indent=4)
        self.store.upload_file(filename)
        return True

    def save_csv(self, filename: str, data: pd.DataFrame | pl.DataFrame) -> bool:
        """Save a DataFrame as a CSV file and upload to S3.

        Accepts both pandas and polars DataFrames.

        Args:
            filename: Path to save the CSV file.
            data: DataFrame to save (pandas or polars).

        Returns:
            True on success, False if DataFrame is empty.
        """
        # Handle polars DataFrame
        if isinstance(data, pl.DataFrame):
            if data.is_empty():
                return False
            self.store.finder.make_path(filename)
            data.write_csv(filename)
            self.store.upload_file(filename)
            return True

        # Handle pandas DataFrame
        if data.empty:
            return False
        self.store.finder.make_path(filename)
        # Convert to polars for faster CSV writing
        df_pl = pl.from_pandas(data)
        df_pl.write_csv(filename)
        self.store.upload_file(filename)
        return True

    def update_csv(self, filename: str, df: pd.DataFrame) -> None:
        """Update a CSV file if the new data has more rows.

        Args:
            filename: Path to the CSV file.
            df: New DataFrame to save.
        """
        if FileReader().check_update(filename, df):
            self.save_csv(filename, df)

    def remove_files(self, filenames: list[str]) -> None:
        """Remove files locally and from S3.

        Args:
            filenames: List of file paths to remove.
        """
        for file in filenames:
            os.remove(file)
        self.store.delete_objects(filenames)

    def rename_file(self, old_name: str, new_name: str) -> None:
        """Rename a file locally and in S3.

        Args:
            old_name: Current file path.
            new_name: New file path.
        """
        os.rename(old_name, new_name)
        self.store.rename_key(old_name, new_name)

    def save_pickle(self, filename: str, data: Any) -> bool:
        """Save an object as a pickle file and upload to S3.

        Args:
            filename: Path to save the pickle file.
            data: Object to pickle and save.

        Returns:
            True on success.
        """
        self.store.finder.make_path(filename)
        with open(filename, "wb") as file:
            pickle.dump(data, file)
        self.store.upload_file(filename)
        return True
