"""Packaging metrics for a folded candidate.

eta_pack is defined as (acoustic channel + chamber volume) / gross bounding-box
volume.  Structural requirements are *not* traded away to inflate it.
"""

from __future__ import annotations

import numpy as np


def duct_corners(centreline, sections) -> np.ndarray:
    """Four corners of each rectangular section, in 3-D."""
    pts = centreline.points
    nrm = centreline.normals
    bin_ = centreline.binormals
    corners = []
    for p, nv, bv, sec in zip(pts, nrm, bin_, sections):
        hw, hh = sec.width / 2.0, sec.height / 2.0
        corners.append([
            p - hw * bv - hh * nv,
            p + hw * bv - hh * nv,
            p + hw * bv + hh * nv,
            p - hw * bv + hh * nv,
        ])
    return np.asarray(corners)     # (n, 4, 3)


try:
    _trapz = np.trapezoid          # numpy >= 2.0
except AttributeError:             # pragma: no cover - older numpy
    _trapz = np.trapz


def package_report(master, centreline, sections, bends, *, wall_mm: float = 18.0,
                   material_density: float = 700.0, driver_mass_kg: float = 8.0,
                   service_access: bool = True) -> dict:
    wall = wall_mm * 1e-3
    corners = duct_corners(centreline, sections)
    flat = corners.reshape(-1, 3)
    lo = flat.min(axis=0) - wall
    hi = flat.max(axis=0) + wall
    dims = hi - lo

    s = centreline.s
    area = np.array([sec.area for sec in sections], dtype=float)
    perimeter = np.array([2.0 * (sec.width + sec.height) for sec in sections], dtype=float)

    channel_vol = float(_trapz(area, s)) if len(s) > 1 else 0.0
    surface_area = float(_trapz(perimeter, s)) if len(s) > 1 else 0.0
    wall_vol = surface_area * wall
    gross_vol = float(np.prod(np.maximum(dims, 1e-9)))
    chamber = float(master.rear_volume)

    mass = wall_vol * material_density + driver_mass_kg
    eta = (channel_vol + chamber) / gross_vol if gross_vol > 0 else 0.0

    return {
        "bbox_w_m": float(dims[0]),
        "bbox_h_m": float(dims[1]),
        "bbox_d_m": float(dims[2]),
        "gross_volume_m3": gross_vol,
        "channel_volume_m3": channel_vol,
        "chamber_volume_m3": chamber,
        "wall_volume_m3": wall_vol,
        "void_volume_m3": max(0.0, gross_vol - channel_vol - chamber - wall_vol),
        "eta_pack": eta,
        "mass_kg": float(mass),
        "fold_count": len(bends),
        "surface_area_m2": surface_area,
        "unique_panel_count": int(4 + 2 * len(bends)),
        "service_access": bool(service_access),
        "wall_mm": wall_mm,
    }
