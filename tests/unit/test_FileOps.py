"""Unit tests for FileOps module with mocked S3 Store.

This test file uses moto to mock S3 operations, allowing tests
to run without real AWS credentials or network access.
"""

import json
import os
import pickle
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import boto3
import pandas as pd
import pytest
from moto import mock_aws

from hyperdrive.FileOps import FileReader, FileWriter

# ============================================================
# Test Data
# ============================================================

SAMPLE_DATA = [
    {"symbol": "AMZN", "open": 2400.85, "volume": 402265, "date": "2020-12-25"},
    {"symbol": "AAPL", "open": 300.90, "volume": 502265, "date": "2015-01-15"},
]

SAMPLE_SNIPPET = {
    "symbol": "NVDA",
    "open": 445.00,
    "volume": 102265,
    "date": "2015-01-15",
}


# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def aws_credentials() -> None:
    """Mock AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["S3_BUCKET"] = "test-bucket"
    os.environ["S3_DEV_BUCKET"] = "test-dev-bucket"
    os.environ["DEV"] = "true"


@pytest.fixture
def s3_bucket(aws_credentials: None) -> Any:
    """Create mock S3 bucket with test data."""
    with mock_aws():
        conn = boto3.resource("s3", region_name="us-east-1")
        bucket_name = "test-dev-bucket"
        conn.create_bucket(Bucket=bucket_name)

        bucket = conn.Bucket(bucket_name)
        # Add symbols file
        bucket.put_object(Key="data/symbols.csv", Body=b"Symbol,Name\nAAPL,Apple")

        yield bucket


@pytest.fixture
def reader(s3_bucket: Any) -> FileReader:
    """Create FileReader with mocked S3."""
    return FileReader()


@pytest.fixture
def writer(s3_bucket: Any) -> FileWriter:
    """Create FileWriter with mocked S3."""
    return FileWriter()


@pytest.fixture
def temp_files(tmp_path: Path) -> dict[str, str]:
    """Create temporary file paths."""
    return {
        "json1": str(tmp_path / "test1.json"),
        "json2": str(tmp_path / "test2.json"),
        "csv1": str(tmp_path / "test1.csv"),
        "csv2": str(tmp_path / "test2.csv"),
    }


@pytest.fixture
def test_dataframes() -> dict[str, pd.DataFrame]:
    """Create test DataFrames."""
    data_with_snippet = SAMPLE_DATA.copy()
    data_with_snippet.append(SAMPLE_SNIPPET)

    return {
        "test_df": pd.DataFrame(SAMPLE_DATA),
        "big_df": pd.DataFrame(data_with_snippet),
        "small_df": pd.DataFrame([SAMPLE_SNIPPET]),
        "empty_df": pd.DataFrame(),
    }


# ============================================================
# Test Classes
# ============================================================


class TestFileWriter:
    """Unit tests for FileWriter class."""

    def test_init(self, writer: FileWriter) -> None:
        """Test FileWriter initialization."""
        assert type(writer).__name__ == "FileWriter"
        assert hasattr(writer, "store")

    def test_save_json_empty(
        self, writer: FileWriter, temp_files: dict[str, str]
    ) -> None:
        """Test saving empty JSON object."""
        writer.store.upload_file = MagicMock()

        result = writer.save_json(temp_files["json1"], {})

        assert result is True
        assert os.path.exists(temp_files["json1"])

        with open(temp_files["json1"]) as f:
            content = json.load(f)
        assert content == {}

    def test_save_json_with_data(
        self, writer: FileWriter, temp_files: dict[str, str]
    ) -> None:
        """Test saving JSON with data."""
        writer.store.upload_file = MagicMock()

        result = writer.save_json(temp_files["json2"], SAMPLE_DATA)

        assert result is True
        assert os.path.exists(temp_files["json2"])

        with open(temp_files["json2"]) as f:
            content = json.load(f)
        assert content == SAMPLE_DATA

    def test_save_csv_empty(
        self,
        writer: FileWriter,
        temp_files: dict[str, str],
        test_dataframes: dict[str, pd.DataFrame],
    ) -> None:
        """Test saving empty DataFrame returns False."""
        result = writer.save_csv(temp_files["csv1"], test_dataframes["empty_df"])
        assert result is False
        assert not os.path.exists(temp_files["csv1"])

    def test_save_csv_with_data(
        self,
        writer: FileWriter,
        temp_files: dict[str, str],
        test_dataframes: dict[str, pd.DataFrame],
    ) -> None:
        """Test saving DataFrame to CSV."""
        writer.store.upload_file = MagicMock()

        result = writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        assert result is True
        assert os.path.exists(temp_files["csv2"])

    def test_update_csv_no_change(
        self,
        writer: FileWriter,
        reader: FileReader,
        temp_files: dict[str, str],
        test_dataframes: dict[str, pd.DataFrame],
    ) -> None:
        """Test update_csv doesn't overwrite with smaller data."""
        writer.store.upload_file = MagicMock()

        # First save
        writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        # Try to update with smaller df - should not change
        writer.update_csv(temp_files["csv2"], test_dataframes["small_df"])

        # Verify original data preserved
        df = pd.read_csv(temp_files["csv2"])
        assert len(df) == len(test_dataframes["test_df"])

    def test_update_csv_larger_data(
        self,
        writer: FileWriter,
        temp_files: dict[str, str],
        test_dataframes: dict[str, pd.DataFrame],
    ) -> None:
        """Test update_csv overwrites with larger data."""
        writer.store.upload_file = MagicMock()

        # First save
        writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        # Update with larger df
        writer.update_csv(temp_files["csv2"], test_dataframes["big_df"])

        # Verify new data
        df = pd.read_csv(temp_files["csv2"])
        assert len(df) == len(test_dataframes["big_df"])

    def test_remove_files(self, writer: FileWriter, tmp_path: Path) -> None:
        """Test removing files."""
        mock_delete = MagicMock()
        writer.store.delete_objects = mock_delete

        # Create test file
        test_file = tmp_path / "to_remove.txt"
        test_file.write_text("test")
        assert test_file.exists()

        # Remove it
        writer.remove_files([str(test_file)])

        assert not test_file.exists()
        mock_delete.assert_called_once()

    def test_rename_file(self, writer: FileWriter, tmp_path: Path) -> None:
        """Test renaming files."""
        mock_rename = MagicMock()
        writer.store.rename_key = mock_rename

        # Create test file
        src = tmp_path / "source.txt"
        dst = tmp_path / "dest.txt"
        src.write_text("test")

        # Rename it
        writer.rename_file(str(src), str(dst))

        assert not src.exists()
        assert dst.exists()
        mock_rename.assert_called_once()


class TestFileReader:
    """Unit tests for FileReader class."""

    def test_init(self, reader: FileReader) -> None:
        """Test FileReader initialization."""
        assert type(reader).__name__ == "FileReader"
        assert hasattr(reader, "store")
        assert hasattr(reader, "traveller")

    def test_load_json(
        self,
        reader: FileReader,
        writer: FileWriter,
        temp_files: dict[str, str],
    ) -> None:
        """Test loading JSON file."""
        reader.store.download_file = MagicMock()
        writer.store.upload_file = MagicMock()

        # Save first
        writer.save_json(temp_files["json1"], SAMPLE_DATA)

        # Load it
        result = reader.load_json(temp_files["json1"])

        assert result == SAMPLE_DATA

    def test_load_csv(
        self,
        reader: FileReader,
        writer: FileWriter,
        temp_files: dict[str, str],
        test_dataframes: dict[str, pd.DataFrame],
    ) -> None:
        """Test loading CSV file."""
        reader.store.download_file = MagicMock()
        writer.store.upload_file = MagicMock()

        # Save first
        writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        # Load it
        result = reader.load_csv(temp_files["csv2"])

        assert len(result) == len(test_dataframes["test_df"])
        assert "symbol" in result.columns

    def test_check_update_same_size(
        self,
        reader: FileReader,
        writer: FileWriter,
        temp_files: dict[str, str],
        test_dataframes: dict[str, pd.DataFrame],
    ) -> None:
        """Test check_update with same size DataFrame."""
        writer.store.upload_file = MagicMock()
        reader.store.download_file = MagicMock()

        writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        result = reader.check_update(temp_files["csv2"], test_dataframes["test_df"])
        assert result is True

    def test_check_update_smaller(
        self,
        reader: FileReader,
        writer: FileWriter,
        temp_files: dict[str, str],
        test_dataframes: dict[str, pd.DataFrame],
    ) -> None:
        """Test check_update with smaller DataFrame returns False."""
        writer.store.upload_file = MagicMock()
        reader.store.download_file = MagicMock()

        writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        result = reader.check_update(temp_files["csv2"], test_dataframes["small_df"])
        assert result is False

    def test_check_update_larger(
        self,
        reader: FileReader,
        writer: FileWriter,
        temp_files: dict[str, str],
        test_dataframes: dict[str, pd.DataFrame],
    ) -> None:
        """Test check_update with larger DataFrame returns True."""
        writer.store.upload_file = MagicMock()
        reader.store.download_file = MagicMock()

        writer.save_csv(temp_files["csv2"], test_dataframes["test_df"])

        result = reader.check_update(temp_files["csv2"], test_dataframes["big_df"])
        assert result is True

    def test_check_file_exists_false(self, reader: FileReader) -> None:
        """Test check_file_exists returns False for non-existent file."""
        reader.store.key_exists = MagicMock(return_value=False)

        result = reader.check_file_exists("nonexistent.txt")
        assert result is False

    def test_check_file_exists_true(self, reader: FileReader, tmp_path: Path) -> None:
        """Test check_file_exists returns True for existing file."""
        reader.store.key_exists = MagicMock(return_value=True)

        test_file = tmp_path / "exists.txt"
        test_file.write_text("test")

        result = reader.check_file_exists(str(test_file))
        assert result is True

    def test_should_be_updated_new_file(self, reader: FileReader) -> None:
        """Test should_be_updated returns True for non-existent file."""
        result = reader.should_be_updated("nonexistent.txt")
        assert result is True

    def test_should_be_updated_old_file(
        self, reader: FileReader, tmp_path: Path
    ) -> None:
        """Test should_be_updated returns True for old file."""
        test_file = tmp_path / "old.txt"
        test_file.write_text("test")

        # Set modification time to 2 days ago
        old_time = datetime.now().timestamp() - (2 * 24 * 60 * 60)
        os.utime(str(test_file), (old_time, old_time))

        result = reader.should_be_updated(str(test_file))
        assert result is True

    def test_should_be_updated_recent_file(
        self, reader: FileReader, tmp_path: Path
    ) -> None:
        """Test should_be_updated returns False for recent file."""
        test_file = tmp_path / "recent.txt"
        test_file.write_text("test")

        result = reader.should_be_updated(str(test_file))
        assert result is False

    def test_load_csv_empty_data_error(
        self, reader: FileReader, tmp_path: Path
    ) -> None:
        """Test load_csv raises EmptyDataError for empty CSV."""
        reader.store.download_file = MagicMock()

        # Create an empty CSV file
        empty_csv = tmp_path / "empty.csv"
        empty_csv.write_text("")

        with pytest.raises(pd.errors.EmptyDataError):
            reader.load_csv(str(empty_csv))

    def test_load_csv_file_not_found(self, reader: FileReader) -> None:
        """Test load_csv raises FileNotFoundError for missing file."""
        reader.store.download_file = MagicMock()

        with pytest.raises(FileNotFoundError):
            reader.load_csv("nonexistent_file.csv")

    def test_update_df(
        self,
        reader: FileReader,
        writer: FileWriter,
        tmp_path: Path,
        test_dataframes: dict[str, pd.DataFrame],
    ) -> None:
        """Test update_df merges new data with existing."""
        writer.store.upload_file = MagicMock()
        reader.store.download_file = MagicMock()

        # Save initial data
        csv_path = str(tmp_path / "update_test.csv")
        writer.save_csv(csv_path, test_dataframes["test_df"])

        # Create new data with date column
        new_data = pd.DataFrame(
            [
                {
                    "symbol": "GOOG",
                    "open": 1500.00,
                    "volume": 300000,
                    "date": "2021-01-01",
                },
            ]
        )

        # Update - should merge old and new
        result = reader.update_df(csv_path, new_data, "date")

        # Should contain data from both old and new
        assert len(result) >= len(new_data)

    def test_update_df_empty_old(
        self, reader: FileReader, writer: FileWriter, tmp_path: Path
    ) -> None:
        """Test update_df with empty existing data returns new data."""
        reader.store.download_file = MagicMock()

        # Create CSV with just headers
        csv_path = str(tmp_path / "empty_update.csv")
        empty_df = pd.DataFrame(columns=pd.Index(["symbol", "open", "volume", "date"]))
        empty_df.to_csv(csv_path, index=False)

        new_data = pd.DataFrame(
            [
                {
                    "symbol": "GOOG",
                    "open": 1500.00,
                    "volume": 300000,
                    "date": "2021-01-01",
                },
            ]
        )

        result = reader.update_df(csv_path, new_data, "date")
        assert len(result) >= 1

    def test_data_in_timeframe(self, reader: FileReader) -> None:
        """Test data_in_timeframe filters data correctly."""
        # Create test data with dates
        df = pd.DataFrame(
            {
                "date": pd.date_range("2020-01-01", periods=365, freq="D"),
                "value": range(365),
            }
        )

        # Filter to last 30 days (1m)
        result = reader.data_in_timeframe(df, "date", "1m")

        # Should have fewer rows than original
        assert len(result) <= 31
        assert "date" in result.columns

    def test_data_in_timeframe_no_column(self, reader: FileReader) -> None:
        """Test data_in_timeframe returns unchanged df when column doesn't exist."""
        df = pd.DataFrame(
            {
                "value": [1, 2, 3],
            }
        )

        result = reader.data_in_timeframe(df, "nonexistent_col", "1m")

        # Should return unchanged since column doesn't exist
        pd.testing.assert_frame_equal(result, df)

    def test_data_in_timeframe_max(self, reader: FileReader) -> None:
        """Test data_in_timeframe with max timeframe."""
        df = pd.DataFrame(
            {
                "date": pd.date_range("2020-01-01", periods=30, freq="D"),
                "value": range(30),
            }
        )

        result = reader.data_in_timeframe(df, "date", "max")
        assert len(result) == 30

    def test_load_pickle(
        self, reader: FileReader, writer: FileWriter, tmp_path: Path
    ) -> None:
        """Test loading pickle file."""
        reader.store.download_file = MagicMock()
        writer.store.upload_file = MagicMock()

        pickle_path = str(tmp_path / "test.pkl")
        test_data = {"key": "value", "list": [1, 2, 3]}

        # Save first
        writer.save_pickle(pickle_path, test_data)

        # Load it
        result = reader.load_pickle(pickle_path)

        assert result == test_data

    def test_save_pickle(self, writer: FileWriter, tmp_path: Path) -> None:
        """Test saving pickle file."""
        writer.store.upload_file = MagicMock()

        pickle_path = str(tmp_path / "test_save.pkl")
        test_data = {"key": "value", "list": [1, 2, 3]}

        result = writer.save_pickle(pickle_path, test_data)

        assert result is True
        assert os.path.exists(pickle_path)

    def test_load_csv_general_exception(
        self, reader: FileReader, tmp_path: Path
    ) -> None:
        """Test load_csv with general exception (lines 52-53)."""
        reader.store.download_file = MagicMock()

        # Create a malformed CSV that will cause a general exception during read
        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_bytes(b"\x00\x01\x02\x03")  # Binary data

        result = reader.load_csv(str(bad_csv))
        # Should return empty DataFrame on general exception
        assert result.empty

    def test_update_df_with_save_fmt(
        self, reader: FileReader, writer: FileWriter, tmp_path: Path
    ) -> None:
        """Test update_df with save_fmt parameter (line 70)."""
        reader.store.download_file = MagicMock()
        writer.store.upload_file = MagicMock()

        # Create initial CSV
        csv_path = str(tmp_path / "test_fmt.csv")
        old_df = pd.DataFrame(
            {
                "date": ["2024-01-01"],
                "value": [100],
            }
        )
        old_df.to_csv(csv_path, index=False)

        new_df = pd.DataFrame(
            {
                "date": ["2024-01-02"],
                "value": [200],
            }
        )

        result = reader.update_df(csv_path, new_df, "date", save_fmt="%Y-%m-%d")
        assert len(result) >= 1
        # Check that date is formatted as string
        assert isinstance(result["date"].iloc[0], str)

    def test_save_csv_polars(self, writer: FileWriter, tmp_path: Path) -> None:
        """Test save_csv with polars DataFrame (lines 246-251)."""
        import polars as pl

        mock_upload = MagicMock()
        writer.store.upload_file = mock_upload

        csv_path = str(tmp_path / "test_polars.csv")
        df_pl = pl.DataFrame({"a": [1, 2, 3], "b": ["x", "y", "z"]})

        result = writer.save_csv(csv_path, df_pl)

        assert result is True
        assert os.path.exists(csv_path)
        mock_upload.assert_called_once()

    def test_save_csv_polars_empty(self, writer: FileWriter, tmp_path: Path) -> None:
        """Test save_csv with empty polars DataFrame returns False."""
        import polars as pl

        mock_upload = MagicMock()
        writer.store.upload_file = mock_upload

        csv_path = str(tmp_path / "test_empty_polars.csv")
        df_pl = pl.DataFrame({"a": [], "b": []})

        result = writer.save_csv(csv_path, df_pl)

        assert result is False
        mock_upload.assert_not_called()

    def test_load_json_needs_update(self, reader: FileReader, tmp_path: Path) -> None:
        """Test load_json when file needs to be updated from S3 (line 63)."""
        json_path = str(tmp_path / "needs_update.json")

        # Create a valid JSON file locally
        with open(json_path, "w") as f:
            json.dump({"key": "value"}, f)

        # Mock should_be_updated to return True
        mock_download = MagicMock()
        reader.should_be_updated = MagicMock(return_value=True)
        reader.store.download_file = mock_download

        result = reader.load_json(json_path)

        mock_download.assert_called_once_with(json_path)
        assert result == {"key": "value"}

    def test_load_pickle_needs_update(self, reader: FileReader, tmp_path: Path) -> None:
        """Test load_pickle when file needs to be updated from S3 (line 197)."""
        pickle_path = str(tmp_path / "needs_update.pkl")

        # Create a valid pickle file locally
        test_data = {"key": "value"}
        with open(pickle_path, "wb") as f:
            pickle.dump(test_data, f)

        # Mock should_be_updated to return True
        mock_download = MagicMock()
        reader.should_be_updated = MagicMock(return_value=True)
        reader.store.download_file = mock_download

        result = reader.load_pickle(pickle_path)

        mock_download.assert_called_once_with(pickle_path)
        assert result == {"key": "value"}

    def test_load_csv_pandas_empty_data_error(
        self, reader: FileReader, tmp_path: Path
    ) -> None:
        """Test load_csv re-raises pd.errors.EmptyDataError from pandas (line 101)."""
        from unittest.mock import patch as mock_patch

        reader.store.download_file = MagicMock()

        # Create a valid CSV so polars doesn't fail
        csv_path = str(tmp_path / "test_pandas_empty.csv")
        Path(csv_path).write_text("a,b\n1,2\n")

        # Mock polars read_csv to succeed, but mock to_pandas to raise EmptyDataError
        with mock_patch("hyperdrive.FileOps.pl.read_csv") as mock_read:
            mock_df = MagicMock()
            mock_df.to_pandas.side_effect = pd.errors.EmptyDataError("empty")
            mock_read.return_value = mock_df

            with pytest.raises(pd.errors.EmptyDataError):
                reader.load_csv(csv_path)
