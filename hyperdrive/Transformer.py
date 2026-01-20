"""JSON encoders for numpy data types."""

import json
from typing import Any

import numpy as np


class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder for numpy data types.

    Converts numpy types to native Python types for JSON serialization.
    Handles integers, floats, complex numbers, arrays, booleans, and void types.
    """

    def default(self, obj: Any) -> Any:
        """Convert numpy types to JSON-serializable Python types.

        Args:
            obj: Object to encode. If a numpy type, converts to Python equivalent.

        Returns:
            JSON-serializable Python object.
        """
        if isinstance(obj, np.integer):
            return int(obj)

        elif isinstance(obj, np.floating):
            return float(obj)

        elif isinstance(obj, np.complexfloating):
            return {"real": float(obj.real), "imag": float(obj.imag)}

        elif isinstance(obj, (np.ndarray,)):
            return obj.tolist()

        elif isinstance(obj, (np.bool_)):
            return bool(obj)

        elif isinstance(obj, (np.void)):
            return None

        return json.JSONEncoder.default(self, obj)
