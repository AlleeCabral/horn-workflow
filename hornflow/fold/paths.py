"""Centreline path builders (2-D folds in the x-z plane).

Every builder returns an ``(n, 3)`` array of points whose polyline length is
close to the requested centreline length L.  Folds are built from straight legs
and circular arcs only, so their geometry - and therefore their bend radii - is
exact and testable.
"""

from __future__ import annotations

import numpy as np


def _arc(p0, d, radius, theta, n, sign=1.0):
    """Circular arc from p0 with initial direction d, turning by theta.

    Returns (points, end_point, end_direction).  2-D; y is added later.
    """
    d = np.asarray(d, float)
    d = d / np.linalg.norm(d)
    left = np.array([-d[1], d[0]]) * sign
    center = np.asarray(p0, float) + radius * left
    v0 = np.asarray(p0, float) - center
    ts = np.linspace(0.0, theta, max(2, n))
    pts = []
    c, s = np.cos(ts), np.sin(ts) * sign
    for ci, si in zip(c, s):
        # rotate v0 by the arc angle about the axis out of the plane
        rot = np.array([[ci, -si], [si, ci]])
        pts.append(center + rot @ v0)
    pts = np.array(pts)
    end_dir = d.copy()
    rot_end = np.array([[np.cos(theta), -np.sin(theta) * sign],
                        [np.sin(theta) * sign, np.cos(theta)]])
    end_dir = rot_end @ d
    return pts, pts[-1], end_dir


def _to3d(pts2d) -> np.ndarray:
    pts2d = np.asarray(pts2d, float)
    return np.column_stack([pts2d[:, 0], np.zeros(len(pts2d)), pts2d[:, 1]])


def straight_path(length: float, n: int = 60) -> np.ndarray:
    z = np.linspace(0.0, float(length), int(n))
    return np.column_stack([np.zeros_like(z), np.zeros_like(z), z])


def _polyline_len(pts) -> float:
    pts = np.asarray(pts, float)
    return float(np.sum(np.linalg.norm(np.diff(pts, axis=0), axis=1)))


def _fold(L: float, R: float, theta: float, leg1_frac: float = 0.5,
          n: int = 120, n_arc: int = 40):
    """A single fold: leg1, arc(theta, R), leg2.  Polyline length == L exactly.

    The arc is sampled into chords, so we size the legs from the *polyline*
    length of the arc (not the ideal R*theta) - that keeps the realised
    centreline length equal to L, not merely close to it.
    """
    d0 = np.array([0.0, 1.0])
    arc0, _, _ = _arc(np.array([0.0, 0.0]), d0, R, theta, n_arc)
    arc_poly = _polyline_len(arc0)
    rem = L - arc_poly
    if rem < 0.0:
        raise ValueError(f"fold does not fit: arc {arc_poly:.4f} m > length {L:.4f} m")
    a1 = leg1_frac * rem
    a2 = rem - a1
    pts = [np.array([0.0, 0.0]), np.array([0.0, a1])]
    arc_pts, p, d = _arc(np.array([0.0, a1]), d0, R, theta, n_arc)
    pts.extend(arc_pts[1:])
    pts.append(p + d * a2)
    return np.array(pts)


def jfold_path(length: float, R: float, leg1_frac: float = 0.5, n: int = 120) -> np.ndarray:
    """90-degree J-fold."""
    return _to3d(_fold(length, R, np.pi / 2.0, leg1_frac, n))


def ufold_path(length: float, R: float, leg1_frac: float = 0.5, n: int = 120) -> np.ndarray:
    """180-degree U-fold."""
    return _to3d(_fold(length, R, np.pi, leg1_frac, n))


def serpentine_path(length: float, R: float, n: int = 200) -> np.ndarray:
    """S-fold: +z, 90 deg, -z-continuation via two opposite arcs."""
    seg = length / 3.0
    pts = _fold(seg * 2.0, R, np.pi / 2.0, 0.5, n)
    p, d = pts[-1], np.array([1.0, 0.0])
    arc_pts, p, d = _arc(p, d, R, -np.pi / 2.0, 30)
    pts = np.vstack([pts, arc_pts[1:]])
    return _to3d(pts)
