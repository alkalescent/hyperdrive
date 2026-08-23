"""Generate 2D and 3D decision boundary artifacts from the latest model."""

from hyperdrive.Precognition import Oracle


def main() -> int:
    """Build and store the 2D and 3D visualization artifacts."""
    oracle = Oracle()

    X = oracle.load_model_pickle("X")
    y = oracle.load_model_pickle("y")

    # 2D
    (
        actual_2D,
        centroid_2D,
        radius_2D,
        grid_2D,
        preds_2D,
    ) = oracle.visualize(X=X, y=y, dimensions=2, refinement=10)

    oracle.save_model_pickle("2D/actual", actual_2D)
    oracle.save_model_pickle("2D/centroid", centroid_2D)
    oracle.save_model_pickle("2D/radius", radius_2D)
    oracle.save_model_pickle("2D/grid", grid_2D)
    oracle.save_model_pickle("2D/preds", preds_2D)

    # 3D
    (
        actual_3D,
        centroid_3D,
        radius_3D,
        grid_3D,
        preds_3D,
    ) = oracle.visualize(X=X, y=y, dimensions=3, refinement=4)

    oracle.save_model_pickle("3D/actual", actual_3D)
    oracle.save_model_pickle("3D/centroid", centroid_3D)
    oracle.save_model_pickle("3D/radius", radius_3D)
    oracle.save_model_pickle("3D/grid", grid_3D)
    oracle.save_model_pickle("3D/preds", preds_3D)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


# Don't actually need to save the radius =>
# just need to use it to modify points that plot will use ultimately
# Need to save final data plot will use after deciding shapes and processing


# and then get 2d and 3d correct from visualize_plotly.ipynb
# make 2d square?
# use contour for 2d?
# have options for rect prism, cube, sphere, icosphere, or octahedron
# as param for 3d
# have option for go.Volume / Isosurface vs small points (from notebook)
# - may be js
# have param for refinement / num of points in linspace
