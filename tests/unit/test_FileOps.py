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
import polars as pl
import pyarrow as pa
import pytest
from botocore.exceptions import ClientError
from moto import mock_aws

from hyperdrive import Constants as C
from hyperdrive.FileOps import FileReader, FileWriter
from hyperdrive.Storage import Store

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

# An orders file as pandas saved it, which polars reads back with float columns.
STORED_ORDERS = (
    "id,created_at,symbol,notional,qty,filled_qty,filled_avg_price,side,"
    "extended_hours\n"
    "a1,2026-08-07 14:18:30.123456+00:00,AAPL,100.0,,0.48,208.33,buy,False\n"
    "a2,2026-08-07 14:18:31.654321+00:00,MSFT,,1.5,1.5,410.2,sell,False\n"
)

# Filled orders as Alpaca returns them, with every number as a string.
NEW_ORDERS = [
    {
        "id": "b1",
        "created_at": "2026-11-03T20:06:01.123456Z",
        "symbol": "NVDA",
        "notional": "254.21",
        "qty": None,
        "filled_qty": "1.395",
        "filled_avg_price": "182.23",
        "side": "buy",
        "extended_hours": False,
    },
    {
        "id": "b2",
        "created_at": "2026-11-03T20:06:02.654321Z",
        "symbol": "AAPL",
        "notional": None,
        "qty": "0.48",
        "filled_qty": "0.48",
        "filled_avg_price": "271.4",
        "side": "sell",
        "extended_hours": False,
    },
]

# Frames shaped like those the other pandas callers of save_csv write: the
# MarketData save paths through update_csv, Broker.get_hists, and
# Broker.save_symbols.
CALLER_FRAMES = {
    "ohlc": pd.DataFrame(
        {
            C.TIME: ["2026-11-19", "2026-11-20"],
            C.OPEN: [270.5, 271.0],
            C.HIGH: [272.25, 273.5],
            C.LOW: [269.75, 270.0],
            C.CLOSE: [271.4, 272.9],
            C.VOL: [41000000, 39000000],
            C.AVG: [271.12, float("nan")],
            C.TRADES: [512000, 0],
        }
    ),
    "intraday": pd.DataFrame(
        {
            C.TIME: ["2026-11-20 09:30", "2026-11-20 09:31"],
            C.OPEN: [270.5, 270.61],
            C.HIGH: [270.9, 270.8],
            C.LOW: [270.4, 270.5],
            C.CLOSE: [270.6, 270.7],
            C.VOL: [120000, 95000],
            C.AVG: [270.63, 270.66],
            C.TRADES: [1500, 1200],
        }
    ),
    "dividends": pd.DataFrame(
        {
            C.EX: ["2026-08-11", "2026-11-10"],
            C.PAY: ["2026-08-14", None],
            C.DEC: ["2026-07-31", None],
            C.DIV: [0.26, 0.27],
        }
    ),
    "splits": pd.DataFrame({C.EX: ["2020-08-31", "2024-06-10"], C.RATIO: [0.25, 0.1]}),
    "unemployment": pd.DataFrame(
        {C.TIME: ["2026-09", "2026-10"], C.UN_RATE: [4.3, 4.4]}
    ),
    "s2f": pd.DataFrame(
        {
            C.TIME: ["2026-11-19", "2026-11-20"],
            C.HALVING: [512.0, 511.0],
            C.RATIO: [56.1, 56.2],
        }
    ),
    "diff_ribbon": pd.DataFrame(
        {C.TIME: ["2026-11-19", "2026-11-20"]} | {ma: [1.1e14, 1.2e14] for ma in C.MAs}
    ),
    "sopr": pd.DataFrame({C.TIME: ["2026-11-19", "2026-11-20"], C.SOPR: [1.01, 0.99]}),
    "ndx": pd.DataFrame(
        {
            C.TIME: ["2026-11-20", "2026-11-20"],
            C.SYMBOL: ["AAPL", "WBA"],
            C.DELTA: ["+", "-"],
        }
    ),
    "hists": pd.DataFrame(
        {
            "begins_at": pd.to_datetime(["2026-11-19", "2026-11-20"]),
            "open_price": ["270.500000", "271.000000"],
            "close_price": ["271.400000", "272.900000"],
            "high_price": ["272.250000", "273.500000"],
            "low_price": ["269.750000", "270.000000"],
            "volume": [41000000, 39000000],
            "session": ["reg", "reg"],
            "interpolated": [False, False],
            "symbol": ["AAPL", "AAPL"],
        }
    ),
    "symbols": pd.DataFrame(
        {C.SYMBOL: ["AAPL", "MSFT"], C.NAME: ["Apple", "Microsoft"]}
    ),
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

    def test_update_csv_saves_alpaca_order_strings(
        self, reader: FileReader, writer: FileWriter, tmp_path: Path
    ) -> None:
        """Test saving stored orders merged with the strings Alpaca returns.

        The merged price columns hold the stored floats beside new numeric
        strings, which polars cannot convert, so pandas writes the frame as it
        did before polars.
        """
        reader.store.download_file = MagicMock()
        writer.store.upload_file = MagicMock()
        path = tmp_path / "orders.csv"
        path.write_bytes(STORED_ORDERS.encode())

        orders = reader.update_df(str(path), pd.DataFrame(NEW_ORDERS), "created_at")
        with pytest.raises(
            pa.ArrowInvalid,
            match="Could not convert '254.21' with type str: tried to convert to double",
        ):
            pl.from_pandas(orders)
        writer.update_csv(str(path), orders)

        expected = orders.to_csv(index=False, lineterminator="\n")
        assert path.read_bytes() == expected.encode()
        writer.store.upload_file.assert_called_once_with(str(path))
        # The next run reads every number back as a float.
        nan = float("nan")
        saved = pd.DataFrame(
            {
                "id": ["a1", "a2", "b1", "b2"],
                "created_at": [
                    "2026-08-07 14:18:30.123456+00:00",
                    "2026-08-07 14:18:31.654321+00:00",
                    "2026-11-03 20:06:01.123456+00:00",
                    "2026-11-03 20:06:02.654321+00:00",
                ],
                "symbol": ["AAPL", "MSFT", "NVDA", "AAPL"],
                "notional": [100.0, nan, 254.21, nan],
                "qty": [nan, 1.5, nan, 0.48],
                "filled_qty": [0.48, 1.5, 1.395, 0.48],
                "filled_avg_price": [208.33, 410.2, 182.23, 271.4],
                "side": ["buy", "sell", "buy", "sell"],
                "extended_hours": [False, False, False, False],
            }
        )
        pd.testing.assert_frame_equal(reader.load_csv(str(path)), saved)

    @pytest.mark.parametrize("name", list(CALLER_FRAMES))
    def test_save_csv_keeps_polars_output(
        self, writer: FileWriter, tmp_path: Path, name: str
    ) -> None:
        """Test the frames the other callers save are still written by polars."""
        writer.store.upload_file = MagicMock()
        frame = CALLER_FRAMES[name]
        path = tmp_path / f"{name}.csv"

        assert writer.save_csv(str(path), frame) is True

        assert path.read_bytes() == pl.from_pandas(frame).write_csv().encode()
        writer.store.upload_file.assert_called_once_with(str(path))

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

    def test_load_csv_missing_key(
        self, reader: FileReader, s3_bucket: Any, tmp_path: Path
    ) -> None:
        """Test load_csv returns an empty DataFrame for a key S3 does not store."""
        reader.store.bucket_name = s3_bucket.name
        path = tmp_path / "missing.csv"

        result = reader.load_csv(str(path))

        assert result.empty
        assert not path.exists()

    @pytest.mark.parametrize(
        ("code", "status"), [("SlowDown", 503), ("AccessDenied", 403)]
    )
    def test_update_csv_download_error_keeps_history(
        self,
        reader: FileReader,
        writer: FileWriter,
        s3_bucket: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        code: str,
        status: int,
    ) -> None:
        """Test a failed S3 read stops the merge before the save."""
        key = str(tmp_path / "history.csv")
        rows = "".join(f"2026-01-{day:02d},1.0\n" for day in range(1, 31))
        s3_bucket.put_object(Key=key, Body=f"date,open\n{rows}".encode())
        # Only reads fail; an upload still reaches the bucket, so a save over
        # the history would show in the stored object.
        failing = MagicMock(wraps=s3_bucket)
        failing.download_fileobj.side_effect = ClientError(
            {
                "Error": {"Code": code, "Message": "test"},
                "ResponseMetadata": {"HTTPStatusCode": status},
            },
            "GetObject",
        )
        # update_csv reads through a FileReader of its own, so every Store
        # gets the failing bucket.
        monkeypatch.setattr(Store, "get_bucket", MagicMock(return_value=failing))
        new = pd.DataFrame({"date": ["2026-11-20", "2026-11-21"], "open": [2.0, 2.0]})

        with pytest.raises(ClientError):
            reader.update_df(key, new, "date")
        with pytest.raises(ClientError):
            writer.update_csv(key, new)

        stored = s3_bucket.Object(key).get()["Body"].read().decode()
        assert len(stored.splitlines()) == 31

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

    def test_update_df_without_new_orders_keeps_stored_orders(
        self, reader: FileReader, writer: FileWriter, tmp_path: Path
    ) -> None:
        """Test a run that places no orders saves the stored orders unchanged."""
        reader.store.download_file = MagicMock()
        writer.store.upload_file = MagicMock()
        path = tmp_path / "orders.csv"
        path.write_bytes(STORED_ORDERS.encode())
        stored = reader.load_csv(str(path))

        # A frame built from no orders has neither rows nor columns.
        orders = reader.update_df(str(path), pd.DataFrame([]), "created_at")
        writer.update_csv(str(path), orders)

        pd.testing.assert_frame_equal(orders, stored)
        pd.testing.assert_frame_equal(reader.load_csv(str(path)), stored)
        writer.store.upload_file.assert_called_once_with(str(path))

    def test_update_df_without_new_orders_or_stored_orders(
        self,
        reader: FileReader,
        writer: FileWriter,
        s3_bucket: Any,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test a run that places no orders before any are stored saves nothing."""
        # update_csv reads through a FileReader of its own, so every Store
        # gets the mocked bucket, which stores no orders file.
        monkeypatch.setattr(Store, "get_bucket_name", lambda self: s3_bucket.name)
        reader.store.bucket_name = s3_bucket.name
        writer.store.upload_file = MagicMock()
        path = tmp_path / "orders.csv"

        orders = reader.update_df(str(path), pd.DataFrame([]), "created_at")
        writer.update_csv(str(path), orders)

        assert orders.empty
        assert not path.exists()
        writer.store.upload_file.assert_not_called()

    def test_update_df_empty_fetch_raises(
        self, reader: FileReader, tmp_path: Path
    ) -> None:
        """Test an empty fetch still raises when the caller requires the column."""
        reader.store.download_file = MagicMock()
        path = tmp_path / "AAPL.csv"
        path.write_text(f"{C.TIME},{C.CLOSE}\n2026-11-20,272.9\n")

        with pytest.raises(KeyError, match=C.TIME):
            reader.update_df(
                str(path), pd.DataFrame(), C.TIME, C.DATE_FMT, missing_ok=False
            )

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

    def test_load_csv_binary_data(self, reader: FileReader, tmp_path: Path) -> None:
        """Test load_csv raises ValueError when polars panics on binary data."""
        reader.store.download_file = MagicMock()

        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_bytes(b"\x00\x01\x02\x03")  # Binary data

        with pytest.raises(ValueError, match="could not be read"):
            reader.load_csv(str(bad_csv))

    @pytest.mark.parametrize(
        "content",
        [b"date,open\n2026-01-01,1.0,2.0\n", b"date,open\n\xff\xfe,1.0\n"],
        ids=["extra-field", "invalid-utf8"],
    )
    def test_load_csv_polars_error(
        self,
        reader: FileReader,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        content: bytes,
    ) -> None:
        """Test load_csv raises ValueError when polars refuses a malformed file."""
        monkeypatch.setattr(reader.store, "download_file", MagicMock())

        bad_csv = tmp_path / "bad.csv"
        bad_csv.write_bytes(content)

        with pytest.raises(ValueError, match="could not be read") as raised:
            reader.load_csv(str(bad_csv))

        assert isinstance(raised.value.__cause__, pl.exceptions.PolarsError)

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
