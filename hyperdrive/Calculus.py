import math
from itertools import permutations

import numpy as np
import pandas as pd
from icosphere import icosphere
from numpy.linalg import norm
from scipy.signal import savgol_filter


class Calculator:
    def avg(self, xs):
        return np.mean(xs)

    def find_centroid(self, points, method="mean"):
        components = points.T
        if method != "mean":
            components = [[min(component), max(component)] for component in components]
        return [self.avg(component) for component in components]

    def delta(self, series, window=1):
        return series / series.shift(window) - 1

    def roll(self, series, window):
        return series.rolling(window).mean()

    def smooth(self, series, window, order):
        return savgol_filter(
            series, window + 1 if window % 2 == 0 else window + 2, order
        )

    def get_difference(self, old: set, new: set) -> tuple[set, set]:
        minus = old.difference(new)
        plus = new.difference(old)
        return minus, plus

    def derive(self, y, x=None):
        if x is None:
            x = np.array([0, 1])
        if isinstance(x, pd.Series):
            x = x.to_numpy()
        x = x.astype("float64")
        x_delta = x[1] - x[0]
        return np.gradient(y, x_delta)

    def cv(self, x, ddof=0):
        if isinstance(x, pd.Series):
            axis = 0
        else:
            axis = 1
        return x.std(axis=axis, ddof=ddof) / x.mean(axis=axis)

    def fib(self, n):
        if n <= 1:
            return [0]
        elif n == 2:
            return [0, 1]
        else:
            lst = self.fib(n - 1)
            return self.fib(n - 1) + [lst[-1] + lst[-2]]

    def find_plane(self, pt1, pt2, pt3):
        pt1, pt2, pt3 = [np.array(pt) for pt in [pt1, pt2, pt3]]
        u = pt2 - pt1
        v = pt3 - pt1

        point = np.array(pt1)
        normal = np.cross(u, v)
        a, b, c = normal
        d = -point.dot(normal)

        return a, b, c, d

    def eval_plane(self, pt, coeffs):
        x, y, z = pt
        a, b, c, d = coeffs
        return a * x + b * y + c * z + d

    def find_shortest_dist(self, points):
        point1 = points[0]
        dists = [math.dist(point1, point) for point in points[1:]]
        return min(dists)

    def same_plane_side(self, pt1, pt2, plane):
        pt1_side = self.eval_plane(pt1, plane)
        pt2_side = self.eval_plane(pt2, plane)
        plane_side = (pt1_side == abs(pt1_side)) == (pt2_side == abs(pt2_side))
        return plane_side

    def get_plane_pts(self, points):
        points = [tuple(point) for point in points]
        shortest_dist = self.find_shortest_dist(points)
        plane_sets = set()
        for i, pt1 in enumerate(points):
            for j, pt2 in enumerate(points):
                for k, pt3 in enumerate(points):
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

    def check_pt_in_shape(self, point, vertices):
        # only works with triangular faces
        centroid = self.find_centroid(vertices)
        plane_pts = self.get_plane_pts(vertices)
        planes = [self.find_plane(*pts) for pts in plane_pts]
        for plane in planes:
            if not self.same_plane_side(centroid, point, plane):
                return False
        return True

    def generate_icosphere(self, radius, center, refinement):
        vertices, faces = icosphere(refinement)
        length = norm(vertices, axis=1).reshape((-1, 1))
        vertices = vertices / length * radius + center
        return vertices, faces

    def generate_octahedron(self, radius, center):
        vertices = np.array(
            [(0, 0, -1), (0, +1, 0), (0, 0, +1), (0, -1, 0), (-1, 0, 0), (+1, 0, 0)]
        ).astype(float)
        vertices *= radius
        vertices += center
        return vertices

    # 4 more!

    def get_3D_circle(self, center, pt1, pt2, refinement=360):
        # method 1: https://math.stackexchange.com/a/2375120
        # method 2: https://math.stackexchange.com/a/73242 - CHOSEN

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

        def convert_to_xyz(theta, idx):
            return (
                center[idx]
                + radius * math.cos(theta) * q1[idx]
                + radius * math.sin(theta) * q2[idx]
            )

        circle = np.array(
            [[convert_to_xyz(theta, idx) for theta in angles] for idx in [0, 1, 2]]
        )
        return circle
