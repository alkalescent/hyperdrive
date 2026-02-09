"""Mathematical and geometric calculation utilities."""

import math
from collections.abc import Sequence
from itertools import permutations
from typing import Any

import numpy as np
import pandas as pd
from icosphere import icosphere
from numpy.linalg import norm
from scipy.signal import savgol_filter

# Type alias for 3D point coordinates (can be tuple, list, or array-like)
Point3D = Sequence[float] | np.ndarray


class Calculator:
    """Mathematical utility class for various calculations.

    Provides methods for statistics, derivatives, geometry,
    and 3D shape operations.
    """

    def avg(self, xs: list[float] | np.ndarray) -> float:
        """Calculate the mean of a collection of numbers.

        Args:
            xs: Collection of numbers.

        Returns:
            The arithmetic mean.
        """
        return np.mean(xs)

    def find_centroid(self, points: np.ndarray, method: str = "mean") -> list[float]:
        """Find the centroid of a set of points.

        Args:
            points: Array of points with shape (n_points, n_dimensions).
            method: 'mean' for average, 'extrema' for midpoint of bounds.

        Returns:
            List of coordinates for the centroid.
        """
        components = points.T
        if method != "mean":
            components = [[min(component), max(component)] for component in components]
        return [self.avg(component) for component in components]

    def delta(self, series: pd.Series, window: int = 1) -> pd.Series:
        """Calculate percentage change over a rolling window.

        Args:
            series: Input time series.
            window: Lag period for comparison.

        Returns:
            Series of percentage changes.
        """
        return series / series.shift(window) - 1

    def roll(self, series: pd.Series, window: int) -> pd.Series:
        """Calculate rolling mean of a series.

        Args:
            series: Input time series.
            window: Rolling window size.

        Returns:
            Rolling mean series.
        """
        return series.rolling(window).mean()

    def smooth(self, series: pd.Series, window: int, order: int) -> np.ndarray:
        """Smooth a series using Savitzky-Golay filter.

        Args:
            series: Input time series.
            window: Filter window size (will be adjusted to odd number).
            order: Polynomial order for fitting.

        Returns:
            Smoothed array.
        """
        return savgol_filter(
            series, window + 1 if window % 2 == 0 else window + 2, order
        )

    def get_difference(self, old: set[Any], new: set[Any]) -> tuple[set[Any], set[Any]]:
        """Find elements removed and added between two sets.

        Args:
            old: Original set.
            new: New set.

        Returns:
            Tuple of (removed elements, added elements).
        """
        minus = old.difference(new)
        plus = new.difference(old)
        return minus, plus

    def derive(
        self, y: np.ndarray | pd.Series, x: np.ndarray | pd.Series | None = None
    ) -> np.ndarray:
        """Compute the numerical derivative of y with respect to x.

        Args:
            y: Dependent variable array.
            x: Independent variable array. Defaults to [0, 1] for unit spacing.

        Returns:
            Array of derivative values.
        """
        if x is None:
            x = np.array([0, 1])
        if isinstance(x, pd.Series):
            x = x.to_numpy()
        x = x.astype("float64")
        x_delta = x[1] - x[0]
        return np.gradient(y, x_delta)

    def cv(self, x: pd.Series | np.ndarray, ddof: int = 0) -> float | np.ndarray:
        """Calculate coefficient of variation.

        Args:
            x: Input data (Series or 2D array).
            ddof: Delta degrees of freedom for std calculation.

        Returns:
            Coefficient of variation (std/mean).
        """
        if isinstance(x, pd.Series):
            axis = 0
        else:
            axis = 1
        return x.std(axis=axis, ddof=ddof) / x.mean(axis=axis)

    def fib(self, n: int) -> list[int]:
        """Generate Fibonacci sequence up to n terms.

        Args:
            n: Number of terms to generate.

        Returns:
            List of Fibonacci numbers.
        """
        if n <= 1:
            return [0]
        elif n == 2:
            return [0, 1]
        else:
            lst = self.fib(n - 1)
            return self.fib(n - 1) + [lst[-1] + lst[-2]]

    def find_plane(
        self,
        pt1: Point3D,
        pt2: Point3D,
        pt3: Point3D,
    ) -> tuple[float, float, float, float]:
        """Find plane equation coefficients from three points.

        Args:
            pt1: First point on the plane.
            pt2: Second point on the plane.
            pt3: Third point on the plane.

        Returns:
            Tuple (a, b, c, d) for plane equation ax + by + cz + d = 0.
        """
        pt1_arr, pt2_arr, pt3_arr = [np.array(pt) for pt in [pt1, pt2, pt3]]
        u = pt2_arr - pt1_arr
        v = pt3_arr - pt1_arr

        point = np.array(pt1_arr)
        normal = np.cross(u, v)
        a, b, c = normal
        d = -point.dot(normal)

        return a, b, c, d

    def eval_plane(
        self, pt: Point3D, coeffs: tuple[float, float, float, float]
    ) -> float:
        """Evaluate a point against a plane equation.

        Args:
            pt: Point coordinates (x, y, z).
            coeffs: Plane coefficients (a, b, c, d).

        Returns:
            Value of ax + by + cz + d (0 if on plane).
        """
        x, y, z = pt[0], pt[1], pt[2]
        a, b, c, d = coeffs
        return a * x + b * y + c * z + d

    def find_shortest_dist(
        self, points: Sequence[np.ndarray | tuple[float, ...]]
    ) -> float:
        """Find the shortest distance from first point to any other.

        Args:
            points: List of point coordinates.

        Returns:
            Minimum distance from points[0] to any other point.
        """
        point1 = points[0]
        dists = [math.dist(point1, point) for point in points[1:]]
        return min(dists)

    def same_plane_side(
        self,
        pt1: Point3D,
        pt2: Point3D,
        plane: tuple[float, float, float, float],
    ) -> bool:
        """Check if two points are on the same side of a plane.

        Args:
            pt1: First point coordinates.
            pt2: Second point coordinates.
            plane: Plane coefficients (a, b, c, d).

        Returns:
            True if both points are on the same side.
        """
        pt1_side = self.eval_plane(pt1, plane)
        pt2_side = self.eval_plane(pt2, plane)
        plane_side = (pt1_side == abs(pt1_side)) == (pt2_side == abs(pt2_side))
        return plane_side

    def get_plane_pts(
        self, points: Sequence[np.ndarray | tuple[float, ...]]
    ) -> list[tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]]:
        """Find sets of three equidistant points forming plane faces.

        Args:
            points: List of point coordinates.

        Returns:
            List of point triplets that define planar faces.
        """
        tuple_points: list[tuple[float, ...]] = [tuple(point) for point in points]
        shortest_dist = self.find_shortest_dist(list(points))
        plane_sets: set[tuple[tuple[float, ...], tuple[float, ...], tuple[float, ...]]] = set()
        for i, pt1 in enumerate(tuple_points):
            for j, pt2 in enumerate(tuple_points):
                for k, pt3 in enumerate(tuple_points):
                    # further optimizations by making sure k >= j and j >= i
                    if i == j or j == k or i == k or k < j or j < i:
                        continue
                    A_2_B = math.dist(pt1, pt2)
                    B_2_C = math.dist(pt2, pt3)
                    C_2_A = math.dist(pt3, pt1)

                    is_planar_set = (
                        np.isclose(A_2_B, B_2_C)
                        and np.isclose(B_2_C, C_2_A)
                        and np.isclose(A_2_B, C_2_A)
                        and np.isclose(A_2_B, shortest_dist)
                    )
                    if is_planar_set:
                        plane_set = (pt1, pt2, pt3)
                        perms = permutations(plane_set)
                        if any(perm in plane_sets for perm in perms):
                            continue
                        plane_sets.add(plane_set)

        return list(plane_sets)

    def check_pt_in_shape(
        self, point: tuple[float, float, float], vertices: np.ndarray
    ) -> bool:
        """Check if a point is inside a shape defined by vertices.

        Only works with triangular faces.

        Args:
            point: Point to test.
            vertices: Array of shape vertices.

        Returns:
            True if point is inside the shape.
        """
        centroid = self.find_centroid(vertices)
        vertices_list: list[np.ndarray] = list(vertices)
        plane_pts = self.get_plane_pts(vertices_list)
        planes = [self.find_plane(*pts) for pts in plane_pts]
        for plane in planes:
            if not self.same_plane_side(centroid, point, plane):
                return False
        return True

    def generate_icosphere(
        self, radius: float, center: Point3D, refinement: int
    ) -> tuple[np.ndarray, np.ndarray]:
        """Generate an icosphere mesh.

        Args:
            radius: Radius of the sphere.
            center: Center point coordinates.
            refinement: Subdivision level for mesh refinement.

        Returns:
            Tuple of (vertices, faces) arrays.
        """
        vertices, faces = icosphere(refinement)
        length = norm(vertices, axis=1).reshape((-1, 1))
        vertices = vertices / length * radius + center
        return vertices, faces

    def generate_octahedron(self, radius: float, center: Point3D) -> np.ndarray:
        """Generate octahedron vertices.

        Args:
            radius: Distance from center to vertices.
            center: Center point coordinates.

        Returns:
            Array of 6 vertex coordinates.
        """
        vertices = np.array(
            [(0, 0, -1), (0, +1, 0), (0, 0, +1), (0, -1, 0), (-1, 0, 0), (+1, 0, 0)]
        ).astype(float)
        vertices *= radius
        vertices += center
        return vertices

    def get_3D_circle(
        self,
        center: np.ndarray,
        pt1: np.ndarray,
        pt2: np.ndarray,
        refinement: int = 360,
    ) -> np.ndarray:
        """Generate points on a 3D circle in an arbitrary plane.

        Args:
            center: Center of the circle.
            pt1: First point on the circle.
            pt2: Second point to define the plane.
            refinement: Number of points on the circle.

        Returns:
            Array of circle coordinates with shape (3, refinement).
        """
        plane = self.find_plane(center, pt1, pt2)
        normal = np.array(plane[0:3])
        unit_normal = normal / norm(normal)

        q1 = pt1 / norm(pt1)
        q2 = center + np.cross(q1, unit_normal)
        # 0 -> 360 degrees in radians
        angles = np.linspace(0, 2 * math.pi, refinement)

        radius = math.dist(center, pt1)

        q1 /= norm(q1)
        q2 = center + np.cross(q1, unit_normal)

        def convert_to_xyz(theta: float, idx: int) -> float:
            return (
                center[idx]
                + radius * math.cos(theta) * q1[idx]
                + radius * math.sin(theta) * q2[idx]
            )

        circle = np.array(
            [[convert_to_xyz(theta, idx) for theta in angles] for idx in [0, 1, 2]]
        )
        return circle
