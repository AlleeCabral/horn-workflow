"""Bend detection and bend-aware screening.

Geometric phase skew is a *screening* metric, not a substitute for field
simulation; it tells you which bends deserve a fold-aware / BEM check.
"""

from __future__ import annotations

import numpy as np

from .base import Bend


def analyze_bends(centreline, sections, f_passband_max: float, c: float = 343.0,
                  curvature_threshold: float = 0.05,
                  construction: str = "smooth") -> list:
    """Detect bends (arcs) on the centreline and screen each one.

    A "bend" is a run of samples whose discrete curvature exceeds
    ``curvature_threshold`` (1/m).
    """
    t = centreline.tangents
    s = centreline.s
    kappa = centreline.curvature()
    heights = np.array([sec.height for sec in sections], dtype=float)
    flags = kappa > curvature_threshold

    bends = []
    i = 0
    n = len(flags)
    while i < n:
        if not flags[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and flags[j + 1]:
            j += 1
        bends.append(_one_bend(i, j, t, s, heights, f_passband_max, c, construction))
        i = j + 1
    return bends


def _one_bend(i0, i1, t, s, heights, f_max, c, construction) -> Bend:
    # total turn
    angle = 0.0
    for k in range(i0, i1):
        d = float(np.clip(np.dot(t[k], t[k + 1]), -1.0, 1.0))
        angle += float(np.arccos(d))
    arc_len = float(s[i1 + 1] - s[i0]) if i1 + 1 < len(s) else float(s[i1] - s[i0])
    radius = arc_len / angle if angle > 1e-9 else float("inf")
    width = float(np.mean(heights[i0:i1 + 2])) if i1 + 2 <= len(heights) else float(np.mean(heights))
    path_diff = width * angle
    phase_skew = 360.0 * f_max * path_diff / c
    transverse = c / (2.0 * width) if width > 0 else float("inf")
    severity = width / (2.0 * radius) if radius > 0 else float("inf")

    risk = "low"
    if severity > 0.5 or phase_skew > 90.0:
        risk = "high"
    elif severity > 0.25 or phase_skew > 30.0:
        risk = "medium"
    if transverse < f_max:
        risk = "high" if risk == "high" else "medium"

    return Bend(
        i0=i0, i1=i1, s0=float(s[i0]), s1=float(s[i1 + 1] if i1 + 1 < len(s) else s[i1]),
        angle_rad=float(angle), radius_m=float(radius),
        inner_radius_m=float(radius - width / 2.0),
        outer_radius_m=float(radius + width / 2.0),
        duct_width_m=float(width), severity=float(severity),
        path_diff_m=float(path_diff), phase_skew_deg=float(phase_skew),
        transverse_mode_hz=float(transverse), reflection_risk=risk,
        construction=construction,
    )


def required_radius(centreline, sections, margin: float = 1.05) -> float:
    """Smallest bend radius that keeps the inner wall from self-intersecting.

    R_min = margin * max(in-plane duct height) / 2 over the region that will be
    bent (here: the whole path, as a conservative screen).
    """
    h = max((sec.height for sec in sections), default=0.0)
    return margin * h / 2.0
