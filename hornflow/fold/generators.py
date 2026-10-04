"""Fold generators: straight reference, J-fold, U-fold (+ declared families).

Each generator returns a *list* of fold candidates so a single acoustic master
yields several packaging options to compare.
"""

from __future__ import annotations

import numpy as np

from ..domain.geometry import Centreline
from . import paths
from .base import FoldCandidate, FoldGenerator
from .evaluate import build_fold_candidate


class StraightFold:
    family = "straight"

    def generate(self, master, limits: dict | None = None, n: int = 80, **kw):
        cl = Centreline.from_points(paths.straight_path(master.length, n))
        return [build_fold_candidate(self.family, master, cl, limits)]


def _radius_scan(L: float, theta: float, r_min: float, r_max_frac: float = 0.95):
    """Candidate bend radii whose arc length fits inside L."""
    arc_max = r_max_frac * L
    r_cap = arc_max / theta
    r_lo = max(r_min, 0.05, L * 0.02)
    if r_lo > r_cap:
        return [r_cap]           # one (likely infeasible) candidate to report
    return list(np.round(np.linspace(r_lo, r_cap, 4), 4))


class JFold:
    family = "j_fold"

    def generate(self, master, limits: dict | None = None, **kw):
        limits = dict(limits or {})
        r_min = float(limits.get("min_bend_radius_m", 0.0) or 0.0)
        out = []
        for R in _radius_scan(master.length, np.pi / 2.0, r_min):
            cl = Centreline.from_points(paths.jfold_path(master.length, float(R)))
            cand = build_fold_candidate(self.family, master, cl, limits)
            cand.metadata["requested_R_m"] = float(R)
            out.append(cand)
        return out


class UFold:
    family = "u_fold"

    def generate(self, master, limits: dict | None = None, **kw):
        limits = dict(limits or {})
        r_min = float(limits.get("min_bend_radius_m", 0.0) or 0.0)
        out = []
        for R in _radius_scan(master.length, np.pi, r_min):
            cl = Centreline.from_points(paths.ufold_path(master.length, float(R)))
            cand = build_fold_candidate(self.family, master, cl, limits)
            cand.metadata["requested_R_m"] = float(R)
            out.append(cand)
        return out


def generators() -> list:
    """Wired fold families.  Extension point: add spiral / 3-D folds here."""
    return [StraightFold(), JFold(), UFold()]
