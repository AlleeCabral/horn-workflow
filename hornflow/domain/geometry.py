"""Acoustic geometry domain objects.

These are the *ideal, unfolded* acoustic reference and the first-class
representations the fold/validation layers consume.  Nothing here knows about
fold topology, files or solvers.

Central ideas
-------------
* ``AreaLaw``        - the target cross-sectional area S_target(s) as a function
                       of centreline arc length, sampled and interpolatable.
* ``Centreline``     - a 3-D curve C(s) with tangents and a rotation-minimizing
                       (parallel-transport) frame; stable at zero curvature.
* ``Section``        - one rectangle at a station (width x height = area).
* ``AcousticMaster`` - the manufacturing- and fold-independent master geometry:
                       throat, mouth, length, boundary and the area law.

A folded horn may only *change* these values through an explicit new candidate
that records the change; the master itself is never mutated by folding.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any

import numpy as np


# --------------------------------------------------------------------------- #
#  cross sections
# --------------------------------------------------------------------------- #
def rect_dims(area: float, aspect: float) -> tuple[float, float]:
    """Width x height [m] of a rectangle of given area and w/h aspect."""
    aspect = max(aspect, 1e-6)
    return float(np.sqrt(area * aspect)), float(np.sqrt(area / aspect))


@dataclass
class Section:
    s: float          # centreline arc length [m]
    area: float       # actual cross-sectional area [m^2]
    width: float      # [m] - across the bend plane
    height: float     # [m] - in the bend plane
    aspect: float = 1.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_area(cls, s: float, area: float, aspect: float) -> "Section":
        w, h = rect_dims(area, aspect)
        return cls(s=s, area=area, width=w, height=h, aspect=aspect)


# --------------------------------------------------------------------------- #
#  area law
# --------------------------------------------------------------------------- #
@dataclass
class AreaLawReport:
    rms: float                 # RMS of (S_actual - S_target)/S_target
    max_positive: float        # worst over-expansion (signed rel.)
    max_negative: float        # worst over-contraction (signed rel.)
    max_contraction: float     # |most negative| as a positive number
    max_expansion: float
    worst_s: float             # station of the worst error
    derivative_jumps: int      # count of |dS/ds| discontinuities above tol

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AreaLaw:
    """Target cross-sectional area as a function of arc length s."""

    s: np.ndarray
    S: np.ndarray

    def __post_init__(self) -> None:
        self.s = np.asarray(self.s, dtype=float)
        self.S = np.asarray(self.S, dtype=float)
        if self.s.shape != self.S.shape:
            raise ValueError("AreaLaw: s and S must have the same shape")
        if np.any(self.S <= 0.0):
            raise ValueError("AreaLaw: areas must be strictly positive")
        if np.any(np.diff(self.s) <= 0.0):
            raise ValueError("AreaLaw: s must be strictly increasing")

    @property
    def length(self) -> float:
        return float(self.s[-1] - self.s[0])

    def evaluate(self, s: Any) -> np.ndarray:
        return np.interp(np.asarray(s, dtype=float), self.s, self.S)

    def stations(self, n: int) -> "AreaLaw":
        s = np.linspace(self.s[0], self.s[-1], int(n))
        return AreaLaw(s, self.evaluate(s))

    def error_vs(self, s: np.ndarray, S_actual: np.ndarray,
                 jump_tol: float = 0.05) -> AreaLawReport:
        """Compare an actual sampled area profile against this target."""
        s = np.asarray(s, dtype=float)
        S_actual = np.asarray(S_actual, dtype=float)
        target = self.evaluate(s)
        rel = (S_actual - target) / target
        rms = float(np.sqrt(np.mean(rel ** 2)))
        i_worst = int(np.argmax(np.abs(rel)))
        d2 = np.diff(target) / np.diff(s)
        jumps = 0
        if len(d2) > 1:
            rate = np.abs(np.diff(d2))
            scale = max(float(np.mean(np.abs(d2))) * jump_tol, 1e-9)
            jumps = int(np.sum(rate > scale))
        return AreaLawReport(
            rms=rms,
            max_positive=float(np.max(rel)),
            max_negative=float(np.min(rel)),
            max_contraction=float(max(0.0, -np.min(rel))),
            max_expansion=float(max(0.0, np.max(rel))),
            worst_s=float(s[i_worst]),
            derivative_jumps=jumps,
        )

    def to_dict(self) -> dict:
        return {"s_m": self.s.tolist(), "S_m2": self.S.tolist()}

    @classmethod
    def from_dict(cls, d: dict) -> "AreaLaw":
        return cls(np.asarray(d["s_m"], dtype=float), np.asarray(d["S_m2"], dtype=float))

    @classmethod
    def from_radius_fn(cls, radius_fn, length: float, n: int = 241) -> "AreaLaw":
        s = np.linspace(0.0, float(length), int(n))
        r = np.asarray(radius_fn(s), dtype=float)
        return cls(s, np.pi * r ** 2)


# --------------------------------------------------------------------------- #
#  centreline + rotation-minimizing frame
# --------------------------------------------------------------------------- #
def _tangents(points: np.ndarray) -> np.ndarray:
    n = len(points)
    t = np.zeros_like(points)
    if n < 2:
        raise ValueError("centreline needs at least two points")
    t[1:-1] = points[2:] - points[:-2]
    t[0] = points[1] - points[0]
    t[-1] = points[-1] - points[-2]
    norms = np.linalg.norm(t, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    return t / norms


def rotation_minimizing_frames(points: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Double-reflection rotation-minimizing frame (Wang et al. 2008).

    Returns (tangent, normal, binormal) arrays of shape (n, 3).  Stable through
    zero-curvature transitions and straight runs (unlike a naive Frenet frame).
    """
    n = len(points)
    t = _tangents(points)
    r = np.zeros_like(points)
    a = np.array([0.0, 0.0, 1.0])
    if abs(float(np.dot(a, t[0]))) > 0.9:
        a = np.array([1.0, 0.0, 0.0])
    r[0] = a - np.dot(a, t[0]) * t[0]
    nrm = np.linalg.norm(r[0])
    r[0] = r[0] / nrm if nrm > 0 else np.array([1.0, 0.0, 0.0])
    for i in range(n - 1):
        v1 = points[i + 1] - points[i]
        if float(np.dot(v1, v1)) < 1e-30:
            r[i + 1] = r[i]
            continue
        c1 = 2.0 / float(np.dot(v1, v1))
        r_l = r[i] - c1 * float(np.dot(v1, r[i])) * v1
        t_l = t[i] - c1 * float(np.dot(v1, t[i])) * v1
        v2 = t[i + 1] - t_l
        if float(np.dot(v2, v2)) < 1e-30:
            r[i + 1] = r_l
        else:
            c2 = 2.0 / float(np.dot(v2, v2))
            r[i + 1] = r_l - c2 * float(np.dot(v2, r_l)) * v2
        r[i + 1] /= max(np.linalg.norm(r[i + 1]), 1e-30)
    b = np.cross(t, r)
    return t, r, b


@dataclass
class Centreline:
    """A sampled centreline C(s) with a rotation-minimizing frame."""

    points: np.ndarray
    tangents: np.ndarray = field(repr=False, default=None)   # type: ignore[assignment]
    normals: np.ndarray = field(repr=False, default=None)    # type: ignore[assignment]
    binormals: np.ndarray = field(repr=False, default=None)  # type: ignore[assignment]
    s: np.ndarray = field(repr=False, default=None)          # type: ignore[assignment]

    def __post_init__(self) -> None:
        self.points = np.asarray(self.points, dtype=float)
        if self.points.ndim != 2 or self.points.shape[1] != 3:
            raise ValueError("Centreline.points must be (n, 3)")
        t, r, b = rotation_minimizing_frames(self.points)
        self.tangents, self.normals, self.binormals = t, r, b
        seg = np.linalg.norm(np.diff(self.points, axis=0), axis=1)
        self.s = np.concatenate([[0.0], np.cumsum(seg)])

    @property
    def length(self) -> float:
        return float(self.s[-1])

    def curvature(self) -> np.ndarray:
        dt = np.linalg.norm(np.diff(self.tangents, axis=0), axis=1)
        ds = np.diff(self.s)
        ds[ds == 0.0] = 1e-30
        k = dt / ds
        return np.concatenate([k, k[-1:]])

    def resample(self, n: int) -> "Centreline":
        s_new = np.linspace(0.0, self.length, int(n))
        pts = np.column_stack([np.interp(s_new, self.s, self.points[:, i]) for i in range(3)])
        return Centreline(pts)

    def to_dict(self) -> dict:
        return {"points_m": self.points.tolist(), "length_m": self.length}

    @classmethod
    def from_points(cls, pts) -> "Centreline":
        return cls(np.asarray(pts, dtype=float))


# --------------------------------------------------------------------------- #
#  acoustic master (the unfolded ideal reference)
# --------------------------------------------------------------------------- #
@dataclass
class AcousticMaster:
    """Manufacturing- and fold-independent master geometry."""

    candidate_id: str
    architecture_id: str
    profile: str                       # flare family name
    throat_area: float                 # [m^2]
    mouth_area: float                  # [m^2]
    length: float                      # centreline path length L [m]
    area_law: AreaLaw
    aspect: float = 1.6
    boundary: str = "free"             # free | piston_infinite_baffle | corner
    rear_volume: float = 0.0           # [m^3]
    compression_ratio: float = 1.0     # Sd / St
    params_snapshot: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)

    @property
    def area_ratio(self) -> float:
        return self.mouth_area / self.throat_area

    def section_at(self, s: float, aspect: float | None = None) -> Section:
        a = float(self.area_law.evaluate(s))
        return Section.from_area(s, a, aspect if aspect is not None else self.aspect)

    def sample_sections(self, n: int, aspect: float | None = None) -> list:
        s = np.linspace(0.0, self.length, int(n))
        return [self.section_at(float(x), aspect) for x in s]

    def to_dict(self) -> dict:
        return {
            "candidate_id": self.candidate_id,
            "architecture_id": self.architecture_id,
            "profile": self.profile,
            "throat_area_m2": self.throat_area,
            "mouth_area_m2": self.mouth_area,
            "length_m": self.length,
            "area_ratio": self.area_ratio,
            "aspect": self.aspect,
            "boundary": self.boundary,
            "rear_volume_m3": self.rear_volume,
            "compression_ratio": self.compression_ratio,
            "area_law": self.area_law.to_dict(),
            "notes": list(self.notes),
        }

    @classmethod
    def from_design(cls, design, candidate_id: str, architecture_id: str,
                    aspect: float = 1.6, boundary: str = "free",
                    rear_volume: float = 0.0, params_snapshot: dict | None = None,
                    n: int = 241) -> "AcousticMaster":
        """Build a master from an existing validated ``theory.Design``.

        This is the single bridge between the mature Webster core and the new
        domain layer - the acoustic numbers are not recomputed here.
        """
        law = AreaLaw.from_radius_fn(design.radius, design.length, n=n)
        return cls(
            candidate_id=candidate_id,
            architecture_id=architecture_id,
            profile=design.profile,
            throat_area=float(design.St),
            mouth_area=float(design.Sm),
            length=float(design.length),
            area_law=law,
            aspect=float(aspect),
            boundary=boundary,
            rear_volume=float(rear_volume),
            params_snapshot=dict(params_snapshot or {}),
        )
