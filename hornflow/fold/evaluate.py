"""Fold evaluation: area law, bends, packaging -> a FoldCandidate."""

from __future__ import annotations

import numpy as np

from ..domain.ids import stable_id
from ..domain.geometry import AcousticMaster, Centreline
from .base import FoldCandidate, sections_along
from .bends import analyze_bends
from .packaging import package_report


def build_fold_candidate(family: str, master: AcousticMaster, centreline: Centreline,
                         limits: dict | None = None, *,
                         contraction: tuple | None = None) -> FoldCandidate:
    """Evaluate a centreline against the master area law.

    ``contraction`` = (s_centre, factor, half_width) optionally scales the actual
    area down near a station, so the area-law error is exercised (used by tests
    and to model an accidental packaging squeeze).
    """
    limits = dict(limits or {})
    f_max = float(limits.get("f_passband_max", 200.0))
    c = float(limits.get("c", 343.0))
    wall_mm = float(limits.get("wall_mm", 18.0))
    density = float(limits.get("material_density", 700.0))
    driver_mass = float(limits.get("driver_mass_kg", 8.0))

    s, S, sections = sections_along(centreline, master)

    if contraction is not None:
        sc, factor, hw = contraction
        m = np.abs(s - sc) <= hw
        S = np.where(m, S * factor, S)
        for sec, si in zip(sections, s):
            if abs(si - sc) <= hw:
                sec.area *= factor
                from ..domain.geometry import rect_dims
                sec.width, sec.height = rect_dims(sec.area, sec.aspect)

    area_report = master.area_law.error_vs(s, S)
    bends = analyze_bends(centreline, sections, f_max, c,
                          construction=str(limits.get("construction", "smooth")))
    packaging = package_report(master, centreline, sections, bends, wall_mm=wall_mm,
                               material_density=density, driver_mass_kg=driver_mass)

    fold_id = stable_id("fold", {
        "family": family, "master": master.candidate_id,
        "length_m": round(float(centreline.length), 9),
        "n_stations": int(len(s)),
        "contraction": contraction,
    })

    warnings = []
    valid = True
    min_radius = float(limits.get("min_bend_radius_m", 0.0) or 0.0)
    max_folds = int(limits.get("max_fold_count", 99))
    for b in bends:
        if b.inner_radius_m < 0.0:
            valid = False
            warnings.append(f"bend at s={b.s0:.3f} m self-intersects "
                            f"(inner radius {b.inner_radius_m:.3f} m < 0)")
        if min_radius and b.radius_m < min_radius - 1e-9:
            valid = False
            warnings.append(f"bend at s={b.s0:.3f} m radius {b.radius_m:.3f} m "
                            f"< limit {min_radius:.3f} m")
    if len(bends) > max_folds:
        valid = False
        warnings.append(f"fold count {len(bends)} exceeds limit {max_folds}")
    if area_report.rms > float(limits.get("area_rms_tol", 0.15)):
        valid = False
        warnings.append(f"area-law RMS error {area_report.rms:.3f} exceeds tolerance")

    return FoldCandidate(
        fold_id=fold_id, architecture_id=master.architecture_id, family=family,
        master_id=master.candidate_id, centreline=centreline, s=s, S_actual=S,
        sections=sections, area_report=area_report, bends=bends,
        packaging=packaging, valid=valid, warnings=warnings,
        metadata={"n_stations": int(len(s))},
    )
