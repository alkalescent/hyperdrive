import sys
import numpy as np
import pandas as pd
sys.path.append('hyperdrive')
from Precognition import Oracle  # noqa autopep8
from Utils import SwissArmyKnife  # noqa autopep8


knife = SwissArmyKnife()
oracle = Oracle()
oracle = knife.use_dev(oracle)
name = 'dir/file'
actual = oracle.get_filename(name)


class TestOracle:
    def test_init(self):
        assert type(oracle).__name__ == 'Oracle'
        assert hasattr(oracle, 'writer')
        assert hasattr(oracle, 'reader')
        assert hasattr(oracle, 'calc')

    def test_filename(self):
        expected = f'models/latest/{name}.pkl'
        assert actual == expected

    def test_save_model_pickle(self):
        assert oracle.save_model_pickle(name, {})
        assert oracle.reader.check_file_exists(actual)

    def test_load_model_pickle(self):
        assert oracle.load_model_pickle(name) == {}
        oracle.writer.remove_files([actual])

    def test_predict(self):
        metadata = oracle.reader.load_json('models/latest/metadata.json')
        features = metadata['features']
        num_features = metadata['num_pca'] or len(features)
        data = np.full((1, num_features), 1)
        features = metadata['features']
        ds = pd.DataFrame(data, columns=features[:num_features])
        pred = oracle.predict(ds)
        assert pred.dtype == np.dtype(bool)

    def test_visualize(self):
        X = oracle.load_model_pickle('X')
        y = oracle.load_model_pickle('y')

        # 2D
        (
            actual_2D,
            centroid_2D,
            radius_2D,
            grid_2D,
            preds_2D
        ) = oracle.visualize(X=X, y=y, dimensions=2, refinement=4)
        assert len(actual_2D) == len(centroid_2D) == len(grid_2D) == 2
        assert isinstance(radius_2D, float)
        assert preds_2D.dtype == np.dtype(int)

        # 3D
        (
            actual_3D,
            centroid_3D,
            radius_3D,
            grid_3D,
            preds_3D
        ) = oracle.visualize(X=X, y=y, dimensions=3, refinement=4)
        assert len(actual_3D) == len(centroid_3D) == len(grid_3D) == 3
        assert isinstance(radius_3D, float)
        assert preds_3D.dtype == np.dtype(int)
