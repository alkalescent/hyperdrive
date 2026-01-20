"""Machine learning prediction utilities using AutoGluon."""

from typing import Any

import numpy as np
import pandas as pd
from autogluon.tabular import TabularDataset, TabularPredictor
from sklearn.decomposition import PCA

from . import Constants as C
from .Calculus import Calculator
from .FileOps import FileReader, FileWriter


class Oracle:
    """Machine learning prediction and visualization engine.

    Provides methods for loading models, making predictions,
    and visualizing decision boundaries using PCA.

    Attributes:
        reader: FileReader instance for loading files.
        writer: FileWriter instance for saving files.
        calc: Calculator instance for mathematical operations.
    """

    def __init__(self) -> None:
        """Initialize the Oracle with file handlers and calculator."""
        self.reader = FileReader()
        self.writer = FileWriter()
        self.calc = Calculator()

    def get_filename(self, name: str, ext: str = "pkl") -> str:
        """Generate a model file path.

        Args:
            name: Base name of the model file.
            ext: File extension.

        Returns:
            Full path to the model file.
        """
        return f"models/latest/{name}.{ext}"

    def load_metadata(self) -> dict[str, Any]:
        """Load model metadata from JSON.

        Returns:
            Dictionary containing model metadata.
        """
        filename = self.get_filename("metadata", "json")
        return self.reader.load_json(filename)

    def load_model_pickle(self, name: str) -> Any:
        """Load a pickled model.

        Args:
            name: Name of the model file (without extension).

        Returns:
            The unpickled model object.
        """
        filename = self.get_filename(name)
        return self.reader.load_pickle(filename)

    def save_model_pickle(self, name: str, data: Any) -> None:
        """Save a model as pickle.

        Args:
            name: Name of the model file (without extension).
            data: Model object to save.
        """
        filename = self.get_filename(name)
        return self.writer.save_pickle(filename, data)

    def predict(self, data: pd.DataFrame | TabularDataset) -> pd.Series:
        """Make predictions using the AutoGluon model.

        Args:
            data: Input data for prediction.

        Returns:
            Series of predictions.
        """
        model_path = "models/latest/autogluon"
        self.reader.store.download_dir(model_path)
        model = TabularPredictor.load(model_path)
        if isinstance(model, TabularPredictor) and not isinstance(data, TabularDataset):
            data = TabularDataset(data)
        return model.predict(data)

    def visualize(
        self,
        X: np.ndarray,
        y: np.ndarray,
        dimensions: int,
        refinement: int,
        increase_percent: float = 0,
    ) -> tuple[
        list[dict[str, list[Any]]], np.ndarray, float, list[np.ndarray], np.ndarray
    ]:
        """Visualize decision boundaries using PCA reduction.

        Args:
            X: Feature matrix.
            y: Target labels.
            dimensions: Number of PCA dimensions (recommended 2-3).
            refinement: Grid resolution (recommended 4-100).
            increase_percent: Percentage to expand the visualization bounds.

        Returns:
            Tuple containing:
                - actual: List of dicts with buy/sell coordinates per component
                - centroid: Center point of the data
                - radius: Radius of the visualization space
                - flattened: Grid coordinates for prediction
                - preds: Predicted labels for grid points
        """
        # recommended in the range [4, 100]
        num_points = refinement
        reducer = PCA(n_components=dimensions)
        X_transformed = reducer.fit_transform(X)
        components = X_transformed.T
        all_coords = np.concatenate(X_transformed)
        # or method='mean'
        centroid = self.calc.find_centroid(X_transformed, method="extrema")
        super_min = min(all_coords)
        super_min -= abs(super_min) * increase_percent
        super_max = max(all_coords)
        super_max += abs(super_max) * increase_percent
        radius = (super_max - super_min) / 2
        lins = [
            np.linspace(
                component - radius if dimensions > 2 else min(components[idx]),
                component + radius if dimensions > 2 else max(components[idx]),
                num_points,
            )
            for idx, component in enumerate(centroid)
        ]
        unflattened = np.meshgrid(*lins)
        flattened = [arr.flatten() for arr in unflattened]
        reduced = np.array(flattened).T
        unreduced = reducer.inverse_transform(reduced)
        metadata = self.load_metadata()
        features = metadata["features"]
        data = pd.DataFrame(unreduced, columns=features[: unreduced.shape[1]])
        preds = self.predict(data).astype(int).to_numpy()
        actual = [
            {
                C.BUY: [datum for idx, datum in enumerate(component) if y[idx]],
                C.SELL: [datum for idx, datum in enumerate(component) if not y[idx]],
            }
            for component in components
        ]
        return actual, centroid, radius, flattened, preds
