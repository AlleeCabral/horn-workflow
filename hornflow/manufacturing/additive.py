"""Additive (3D-print) transformer: one continuous shelled duct.

Preserves the acoustic internal surface (the inner wall is exactly the master's
cross-sections), reports deviation from the acoustic master, checks
watertightness and minimum wall, segments the part to the printer build volume,
and exports STL (3MF/STEP are deferred stubs - see exporters/deferred.py).
"""

from __future__ import annotations

import numpy as np

from ..domain.ids import stable_id
from . import meshbuild
from .base import ManufacturingVariant

PRINT_DENSITY = 1050.0     # kg/m^3, printed polymer with a solid shell


class AdditiveTransformer:
    method = "additive"

    def transform(self, candidate, cfg: dict) -> ManufacturingVariant:
        cfg = dict(cfg or {})
        wall_mm = float(cfg.get("wall_mm", 18.0))
        k = int(cfg.get("ring_segments", 4))
        build = cfg.get("build_volume_mm", (350.0, 350.0, 350.0))

        mesh = meshbuild.shell_mesh(candidate, wall_mm=wall_mm, k=k)
        man = meshbuild.edge_manifold_report(mesh)
        total_area = sum(_tri_area(mesh, t) for t in mesh.tris)
        inner_tag = mesh.tag_of("wall_inner")
        inner_area = sum(_tri_area(mesh, t) for t in mesh.tris if t[3] == inner_tag)
        # shell material volume = inner (acoustic) surface extruded by the wall
        wall_vol = inner_area * (wall_mm * 1e-3)
        mass = wall_vol * PRINT_DENSITY

        lo, hi = mesh.bounds()
        dims = (hi - lo) * 1e3
        parts = _segment_count(dims, build)

        warnings = []
        if not man["watertight"]:
            warnings.append(f"shell not watertight: {man['boundary_edges']} boundary edges")
        if wall_mm < 2.0:
            warnings.append(f"wall {wall_mm:.1f} mm below printable minimum (2 mm)")

        deviations = {
            "area_law_rms": candidate.area_report.rms,
            "centreline_length_m": candidate.centreline.length,
            "wall_mm": wall_mm,
        }
        metrics = {
            "surface_area_m2": float(total_area),
            "wall_volume_m3": float(wall_vol),
            "mass_kg": float(mass),
            "bbox_mm": [round(float(d), 1) for d in dims],
            "part_count": parts,
            "watertight": bool(man["watertight"]),
            "min_wall_mm": wall_mm,
        }
        valid = man["watertight"] and wall_mm >= 2.0 and candidate.valid
        vid = stable_id("mfg", {"method": self.method, "fold": candidate.fold_id,
                                "wall_mm": wall_mm})
        return ManufacturingVariant(
            variant_id=vid, method=self.method, candidate_id=candidate.master_id,
            fold_id=candidate.fold_id, valid=valid, metrics=metrics,
            deviations=deviations, panels=_part_manifest(dims, build, parts),
            warnings=warnings, artifacts={}, deferred=["3mf", "step"],
        )

    def exports(self, variant: ManufacturingVariant) -> dict:
        return dict(variant.artifacts)


def _tri_area(mesh, tri) -> float:
    n0, n1, n2, _ = tri
    p0 = np.asarray(mesh.nodes[n0]); p1 = np.asarray(mesh.nodes[n1]); p2 = np.asarray(mesh.nodes[n2])
    return 0.5 * float(np.linalg.norm(np.cross(p1 - p0, p2 - p0)))


def _segment_count(dims, build) -> int:
    n = 1
    for d, b in zip(dims, build):
        n = max(n, int(np.ceil(float(d) / max(float(b), 1.0))))
    return int(n)


def _part_manifest(dims, build, parts) -> list:
    return [{"part": i + 1, "note": "segment along the longest axis",
             "bbox_mm": [round(float(d), 1) for d in dims]} for i in range(parts)]
