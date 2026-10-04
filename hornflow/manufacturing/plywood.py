"""Plywood transformer: a faceted, buildable variant of the acoustic master.

Replaces the smooth centreline with straight chords (facets) and reports the
resulting area-law deviation and centreline-length error.  Facets are chosen by
the allowed acoustic error and construction constraints - this is a *distinct*
optimisation, not "sharpen the printed design".
"""

from __future__ import annotations

import numpy as np

from ..domain.geometry import rect_dims
from ..domain.ids import stable_id
from .base import ManufacturingVariant

PLY_DENSITY = 600.0     # kg/m^3 (birch ply / MDF typical)


class PlywoodTransformer:
    method = "plywood"

    def transform(self, candidate, cfg: dict) -> ManufacturingVariant:
        cfg = dict(cfg or {})
        master = cfg.get("master")
        facet_len_mm = float(cfg.get("facet_len_mm", 200.0))
        tol = float(cfg.get("area_rms_tol", 0.05))
        len_tol = float(cfg.get("length_tol", 0.02))
        wall_mm = float(cfg.get("wall_mm", 18.0))

        L = candidate.centreline.length
        m = max(3, int(np.ceil(L / (facet_len_mm * 1e-3))) + 1)
        s_nodes = np.linspace(0.0, L, m)
        faceted = candidate.centreline.resample(m)

        length_err = (faceted.length - L) / L if L > 0 else 0.0
        err = _facet_area_error(master.area_law, s_nodes, n_sub=16)

        aspect = master.aspect if master is not None else 1.6
        panels = []
        for i in range(m - 1):
            a0 = float(master.area_law.evaluate(s_nodes[i]))
            a1 = float(master.area_law.evaluate(s_nodes[i + 1]))
            w0, h0 = rect_dims(a0, aspect)
            w1, h1 = rect_dims(a1, aspect)
            panels.append({
                "facet": i + 1, "s0_m": round(float(s_nodes[i]), 4),
                "s1_m": round(float(s_nodes[i + 1]), 4),
                "inlet_w_mm": round(w0 * 1e3, 1), "inlet_h_mm": round(h0 * 1e3, 1),
                "outlet_w_mm": round(w1 * 1e3, 1), "outlet_h_mm": round(h1 * 1e3, 1),
            })

        wall_vol = candidate.packaging.get("surface_area_m2", 0.0) * (wall_mm * 1e-3)
        mass = wall_vol * PLY_DENSITY + 8.0
        mitre = 180.0 / max(m - 1, 1)

        warnings = []
        if err.rms > tol:
            warnings.append(f"area-law RMS {err.rms:.3f} exceeds plywood tolerance {tol}")
        if abs(length_err) > len_tol:
            warnings.append(f"centreline length error {length_err*100:.1f}% exceeds {len_tol*100:.0f}%")

        valid = (err.rms <= tol and abs(length_err) <= len_tol and candidate.valid)
        metrics = {
            "n_panels": m - 1,
            "facet_len_mm": facet_len_mm,
            "length_m": L,
            "length_error_pct": round(length_err * 100.0, 3),
            "area_law_rms": round(err.rms, 5),
            "area_law_max_contraction": round(err.max_contraction, 5),
            "mass_kg": float(mass),
            "wall_volume_m3": float(wall_vol),
            "nominal_mitre_deg": round(mitre, 2),
        }
        vid = stable_id("mfg", {"method": self.method, "fold": candidate.fold_id,
                                "facet_len_mm": facet_len_mm})
        return ManufacturingVariant(
            variant_id=vid, method=self.method, candidate_id=candidate.master_id,
            fold_id=candidate.fold_id, valid=valid, metrics=metrics,
            deviations={"area_law_rms": err.rms, "length_error_pct": length_err * 100.0},
            panels=panels, warnings=warnings, artifacts={}, deferred=["step", "dxf_full"],
        )

    def exports(self, variant: ManufacturingVariant) -> dict:
        return dict(variant.artifacts)


def _facet_area_error(law, s_nodes, n_sub: int = 16):
    """RMS error of linear-per-facet area vs the true target along the path."""
    from ..domain.geometry import AreaLaw, AreaLawReport
    ds = np.diff(s_nodes)
    # densified smooth target
    s_all = []
    for i in range(len(s_nodes) - 1):
        s_all.append(np.linspace(s_nodes[i], s_nodes[i + 1], n_sub, endpoint=False))
    s_all = np.concatenate(s_all + [s_nodes[-1:]])
    true = law.evaluate(s_all)
    # linear-per-facet approximation
    approx = np.interp(s_all, s_nodes, law.evaluate(s_nodes))
    rel = (approx - true) / true
    rms = float(np.sqrt(np.mean(rel ** 2)))
    iw = int(np.argmax(np.abs(rel)))
    return AreaLawReport(rms=rms, max_positive=float(np.max(rel)),
                         max_negative=float(np.min(rel)),
                         max_contraction=float(max(0.0, -np.min(rel))),
                         max_expansion=float(max(0.0, np.max(rel))),
                         worst_s=float(s_all[iw]), derivative_jumps=0)
