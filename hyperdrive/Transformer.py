"""JSON encoders for numpy data types."""

import json
from typing import Any

import numpy as np


class NumpyEncoder(json.JSONEncoder):
    """Custom JSON encoder for numpy data types.

    Converts numpy types to native Python types for JSON serialization.
    Handles integers, floats, complex numbers, arrays, booleans, and void types.
    """

    def default(self, o: Any) -> Any:
        """Convert numpy types to JSON-serializable Python types.

        Args:
            o: Object to encode. If a numpy type, converts to Python equivalent.

        Returns:
            JSON-serializable Python object.
        """
        if isinstance(o, np.integer):
            return int(o)

        elif isinstance(o, np.floating):
            return float(o)

        elif isinstance(o, np.complexfloating):
            return {"real": float(o.real), "imag": float(o.imag)}

        elif isinstance(o, (np.ndarray,)):
            return o.tolist()

        elif isinstance(o, (np.bool_)):
            return bool(o)

        elif isinstance(o, (np.void)):
            return None

        return json.JSONEncoder.default(self, o)
