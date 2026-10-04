"""Fold topology contract and the fold-candidate representation.

A fold turns the ideal unfolded ``AcousticMaster`` into a physical centreline
C(s) whose cross-sections carry the target area law S_target(s).  The fold may
not silently change the master: it is evaluated against it and any deviation is
reported.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Protocol, runtime_checkable

import numpy as np

from ..domain.geometry import AcousticMaster, AreaLaw, Centreline, Section


@dataclass
class Bend:
    """One detected bend in a centreline."""

    i0: int                 # start sample index
    i1: int                 # end sample index
    s0: float               # start arc length [m]
    s1: float               # end arc length [m]
    angle_rad: float        # total turn angle
    radius_m: float         # mean centreline radius of curvature
    inner_radius_m: float
    outer_radius_m: float
    duct_width_m: float     # in the bend plane
    severity: float         # width / (2 R)
    path_diff_m: float      # inner vs outer path difference = width * angle
    phase_skew_deg: float   # screening phase skew at the passband maximum
    transverse_mode_hz: float
    reflection_risk: str = "low"     # low | medium | high
    construction: str = "smooth"     # smooth | faceted

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FoldCandidate:
    fold_id: str
    architecture_id: str
    family: str
    master_id: str
    centreline: Centreline
    s: np.ndarray
    S_actual: np.ndarray
    sections: list = field(default_factory=list)      # [Section]
    area_report: object = None                        # AreaLawReport
    bends: list = field(default_factory=list)         # [Bend]
    packaging: dict = field(default_factory=dict)
    valid: bool = True
    warnings: list = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "fold_id": self.fold_id,
            "architecture_id": self.architecture_id,
            "family": self.family,
            "master_id": self.master_id,
            "length_m": float(self.centreline.length),
            "area_report": self.area_report.to_dict() if self.area_report else None,
            "bends": [b.to_dict() for b in self.bends],
            "packaging": self.packaging,
            "valid": self.valid,
            "warnings": list(self.warnings),
            "metadata": self.metadata,
            "centreline_length_m": float(self.centreline.length),
            "n_stations": int(len(self.s)),
        }


def sections_along(centreline: Centreline, master: AcousticMaster,
                   aspect: float | None = None) -> tuple:
    """Map the master area law onto a centreline; return (s, S_actual, sections).

    The cross-section at arc length s uses the target area exactly, so the
    continuous fold preserves the area law by construction; the residual is
    discretization.  The width runs along the local (rotation-minimizing)
    binormal and the height along the normal.
    """
    aspect = float(aspect if aspect is not None else master.aspect)
    s = np.asarray(centreline.s, dtype=float)
    S = master.area_law.evaluate(s)
    secs = []
    for si, ai in zip(s, S):
        secs.append(Section.from_area(float(si), float(ai), aspect))
    return s, S, secs


@runtime_checkable
class FoldGenerator(Protocol):
    family: str

    def generate(self, master: AcousticMaster, limits: dict, **kw) -> list:
        ...


@runtime_checkable
class FoldEvaluator(Protocol):
    def evaluate(self, cand: FoldCandidate, master: AcousticMaster,
                 f_passband_max: float, c: float = 343.0) -> FoldCandidate:
        ...
