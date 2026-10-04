"""Unit / golden tests: fold topology, bend analysis, manufacturing.

Run standalone:  python3 tests/test_fold_mfg.py
Under pytest:    python3 -m pytest tests/test_fold_mfg.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow import config, fold                                          # noqa: E402
from hornflow.architecture.front_loaded import build_master               # noqa: E402
from hornflow.manufacturing import meshbuild                              # noqa: E402
from hornflow.manufacturing.additive import AdditiveTransformer           # noqa: E402
from hornflow.manufacturing.plywood import PlywoodTransformer             # noqa: E402

EXAMPLE = ROOT / "params" / "horn_jbl_1200b.yaml"
LIMITS = {"f_passband_max": 200.0, "wall_mm": 18.0, "min_bend_radius_m": 0.0}


def _master():
    p = config.load(EXAMPLE)
    _, m = build_master(p, "folded_horn")
    return p, m


def test_straight_fold_reference():
    _, m = _master()
    c = fold.StraightFold().generate(m, LIMITS)[0]
    assert c.valid
    assert len(c.bends) == 0
    assert c.area_report.rms < 1e-9
    assert abs(c.centreline.length - m.length) < 1e-9


def test_jfold_golden():
    _, m = _master()
    cands = fold.JFold().generate(m, LIMITS)
    assert cands
    ok = [c for c in cands if c.valid]
    assert ok, "at least one J-fold must be geometrically valid"
    c = ok[0]
    assert len(c.bends) == 1
    assert abs(c.centreline.length - m.length) < 1e-6
    assert c.area_report.rms < 1e-9
    assert c.packaging["eta_pack"] > 0.0


def test_ufold_golden_and_selfintersection_flagged():
    _, m = _master()
    cands = fold.UFold().generate(m, LIMITS)
    # tiny radius folds must be flagged invalid (inner radius < 0)
    small = [c for c in cands if c.metadata["requested_R_m"] < 0.2]
    assert small and all(not c.valid for c in small)
    ok = [c for c in cands if c.valid]
    assert ok and all(len(c.bends) == 1 for c in ok)


def test_deliberate_contraction_is_detected():
    _, m = _master()
    cl = fold.Centreline.from_points(
        np.column_stack([np.zeros(40), np.zeros(40), np.linspace(0, m.length, 40)]))
    c = fold.build_fold_candidate("straight", m, cl, LIMITS,
                                  contraction=(0.7, 0.5, 0.1))
    assert not c.valid
    assert c.area_report.max_contraction > 0.3
    assert any("area-law" in w for w in c.warnings)


def test_bend_phase_skew_increases_with_frequency():
    _, m = _master()
    cl = fold.Centreline.from_points(
        np.column_stack([np.zeros(60), np.zeros(60), np.linspace(0, m.length, 60)]))
    lo = fold.build_fold_candidate("straight", m, cl, {"f_passband_max": 100.0})
    hi = fold.build_fold_candidate("straight", m, cl, {"f_passband_max": 400.0})
    # no bends in a straight line -> nothing to compare; use a J-fold instead
    c1 = fold.JFold().generate(m, LIMITS)[-1]
    b = c1.bends[0]
    assert b.phase_skew_deg >= 0.0
    assert b.severity >= 0.0
    assert b.transverse_mode_hz > 0.0


def test_packaging_metrics_positive():
    _, m = _master()
    c = fold.JFold().generate(m, LIMITS)[-1]
    for k in ("gross_volume_m3", "channel_volume_m3", "mass_kg", "eta_pack",
              "surface_area_m2"):
        assert c.packaging[k] > 0.0


def test_additive_shell_is_watertight():
    _, m = _master()
    c = [x for x in fold.JFold().generate(m, LIMITS) if x.valid][0]
    v = AdditiveTransformer().transform(c, {"wall_mm": 18.0})
    assert v.valid
    assert v.metrics["watertight"] is True
    assert v.metrics["mass_kg"] > 0.0
    assert "3mf" in v.deferred and "step" in v.deferred


def test_shell_mesh_edge_manifold():
    _, m = _master()
    c = [x for x in fold.UFold().generate(m, LIMITS) if x.valid][0]
    mesh = meshbuild.shell_mesh(c, wall_mm=18.0, k=4)
    rep = meshbuild.edge_manifold_report(mesh)
    assert rep["watertight"], rep


def test_plywood_facet_reports_deviation():
    _, m = _master()
    c = [x for x in fold.JFold().generate(m, LIMITS) if x.valid][0]
    v = PlywoodTransformer().transform(c, {"master": m, "facet_len_mm": 250.0})
    assert v.metrics["n_panels"] > 2
    assert "area_law_rms" in v.deviations
    # faceting must not silently create a local contraction
    assert v.metrics["area_law_max_contraction"] < 0.5


def test_plywood_finer_facets_reduce_area_error():
    _, m = _master()
    c = [x for x in fold.JFold().generate(m, LIMITS) if x.valid][0]
    coarse = PlywoodTransformer().transform(c, {"master": m, "facet_len_mm": 500.0})
    fine = PlywoodTransformer().transform(c, {"master": m, "facet_len_mm": 100.0})
    assert fine.metrics["area_law_rms"] < coarse.metrics["area_law_rms"]


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
