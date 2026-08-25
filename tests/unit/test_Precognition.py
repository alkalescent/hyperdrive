"""Unit tests for Precognition module with mocked S3."""

from collections.abc import Generator
from typing import Any
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

# ============================================================
# Fixtures
# ============================================================


@pytest.fixture
def mock_env_vars(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set up mock environment variables."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("S3_BUCKET", "test-bucket")
    monkeypatch.setenv("S3_DEV_BUCKET", "test-dev-bucket")
    monkeypatch.setenv("DEV", "true")


@pytest.fixture
def mock_file_ops(mock_env_vars: None) -> Generator[dict[str, MagicMock], None, None]:
    """Mock file operations (FileReader, FileWriter, Store)."""
    with (
        patch("hyperdrive.Precognition.FileWriter") as MockWriter,
        patch("hyperdrive.Precognition.FileReader") as MockReader,
    ):
        reader = MagicMock()
        writer = MagicMock()
        store = MagicMock()

        # Configure reader
        reader.load_csv.return_value = pd.DataFrame()
        reader.check_file_exists.return_value = True
        reader.load_json.return_value = {
            "features": ["f1", "f2", "f3", "f4", "f5"],
            "num_pca": 2,
        }
        reader.load_pickle.return_value = {}
        reader.store = store
        reader.store.download_dir = MagicMock()
        reader.store.download_file = MagicMock()

        # Configure store
        store.finder = MagicMock()
        store.finder.make_path = MagicMock()
        store.upload_file = MagicMock(return_value=True)
        store.download_dir = MagicMock()

        # Configure writer
        writer.save_pickle = MagicMock(return_value=True)
        writer.remove_files = MagicMock()
        writer.store = store

        MockReader.return_value = reader
        MockWriter.return_value = writer

        yield {"reader": reader, "writer": writer, "store": store}


@pytest.fixture
def oracle(mock_file_ops: dict[str, MagicMock]) -> Any:
    """Create Oracle instance with mocked dependencies."""
    from hyperdrive.Precognition import Oracle

    orc = Oracle()
    orc.reader = mock_file_ops["reader"]
    orc.writer = mock_file_ops["writer"]
    return orc


# ============================================================
# Tests
# ============================================================


class TestOracle:
    """Tests for the Oracle ML prediction class."""

    def test_init(self, oracle: Any) -> None:
        """Test Oracle initialization."""
        assert type(oracle).__name__ == "Oracle"
        assert hasattr(oracle, "writer")
        assert hasattr(oracle, "reader")
        assert hasattr(oracle, "calc")

    def test_filename(self, oracle: Any) -> None:
        """Test filename generation."""
        name = "dir/file"
        expected = f"models/latest/{name}.pkl"
        actual = oracle.get_filename(name)
        assert actual == expected

    def test_save_model_pickle(
        self, oracle: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test saving model pickle."""
        name = "test_model"
        mock_file_ops["writer"].save_pickle.return_value = True
        result = oracle.save_model_pickle(name, {"test": "data"})
        assert result is True

    def test_load_model_pickle(
        self, oracle: Any, mock_file_ops: dict[str, MagicMock]
    ) -> None:
        """Test loading model pickle."""
        name = "test_model"
        mock_file_ops["reader"].load_pickle.return_value = {"test": "data"}
        result = oracle.load_model_pickle(name)
        assert result == {"test": "data"}

    def test_predict(self, oracle: Any, mock_file_ops: dict[str, MagicMock]) -> None:
        """Test prediction with mocked model."""
        oracle.reader.store.download_dir = MagicMock()

        with (
            patch("hyperdrive.Precognition.TabularPredictor") as MockPredictor,
            patch("hyperdrive.Precognition.TabularDataset"),
            patch("hyperdrive.Precognition.isinstance", return_value=False),
        ):
            mock_model = MagicMock()
            mock_model.predict.return_value = pd.Series([True, False, True])
            MockPredictor.load.return_value = mock_model

            data = pd.DataFrame({"f1": [1, 2, 3], "f2": [4, 5, 6]})
            result = oracle.predict(data)

            assert len(result) == 3
            MockPredictor.load.assert_called_once()

    def test_visualize(self, oracle: Any, mock_file_ops: dict[str, MagicMock]) -> None:
        """Test visualization with mocked data."""
        X = np.random.rand(100, 5)
        y = np.random.choice([True, False], size=100)
        mock_file_ops["reader"].load_pickle.side_effect = [X, y]
        oracle.reader.store.download_dir = MagicMock()

        with (
            patch("hyperdrive.Precognition.TabularPredictor") as MockPredictor,
            patch("hyperdrive.Precognition.TabularDataset"),
            patch("hyperdrive.Precognition.isinstance", return_value=False),
        ):
            mock_model = MagicMock()
            mock_model.predict.return_value = pd.Series(np.zeros(16, dtype=int))
            MockPredictor.load.return_value = mock_model

            actual, centroid, radius, grid, preds = oracle.visualize(
                X=X, y=y, dimensions=2, refinement=4
            )

            assert len(actual) == 2
            assert len(centroid) == 2
            assert isinstance(radius, float)
            assert len(grid) == 2
