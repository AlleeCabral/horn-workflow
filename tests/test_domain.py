"""Unit tests: domain layer (ids, geometry, state) and unit conversion.

Run standalone:  python3 tests/test_domain.py
Under pytest:    python3 -m pytest tests/test_domain.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow import config                                               # noqa: E402
from hornflow.domain.geometry import (AcousticMaster, AreaLaw, Centreline,  # noqa: E402
                                      rotation_minimizing_frames)
from hornflow.domain.ids import canonical_json, stable_id                 # noqa: E402
from hornflow.domain.state import DesignState, load_state, SCHEMA_VERSION  # noqa: E402

EXAMPLE = ROOT / "params" / "horn_jbl_1200b.yaml"


# ---------------------------------------------------------------- ids
def test_stable_id_is_deterministic_and_noise_free():
    a = stable_id("cand", {"x": 0.1 + 0.2, "y": [1.0, 2.0]})
    b = stable_id("cand", {"y": [1.0, 2.0], "x": 0.3})
    assert a == b
    assert a.startswith("cand_")
    assert canonical_json({"b": 1, "a": 2}) == '{"a":2,"b":1}'


def test_stable_id_changes_with_input():
    assert stable_id("c", {"a": 1}) != stable_id("c", {"a": 2})


# ---------------------------------------------------------------- area law
def test_area_law_rejects_invalid():
    import pytest
    with pytest.raises(ValueError):
        AreaLaw(np.array([0.0, 1.0]), np.array([1.0, -2.0]))
    with pytest.raises(ValueError):
        AreaLaw(np.array([0.0, 0.0]), np.array([1.0, 2.0]))


def test_area_law_error_zero_when_exact():
    s = np.linspace(0, 1.0, 21)
    law = AreaLaw(s, np.linspace(0.05, 1.5, 21))
    rep = law.error_vs(s, law.evaluate(s))
    assert rep.rms < 1e-12
    assert rep.max_contraction < 1e-12


def test_area_law_detects_contraction():
    s = np.linspace(0, 1.0, 41)
    law = AreaLaw(s, np.linspace(0.05, 1.5, 41))
    actual = law.evaluate(s).copy()
    actual[20] *= 0.5
    rep = law.error_vs(s, actual)
    assert rep.rms > 0.05
    assert rep.max_contraction > 0.4


# ---------------------------------------------------------------- centreline
def test_centreline_straight_length():
    pts = np.column_stack([np.zeros(11), np.zeros(11), np.linspace(0, 1.5, 11)])
    cl = Centreline(pts)
    assert abs(cl.length - 1.5) < 1e-9
    assert np.allclose(np.abs(cl.tangents[:, 2]), 1.0)


def test_rmf_is_orthonormal_and_finite_on_straight():
    pts = np.column_stack([np.zeros(20), np.zeros(20), np.linspace(0, 1, 20)])
    t, n, b = rotation_minimizing_frames(pts)
    for i in range(len(pts)):
        assert abs(np.dot(t[i], n[i])) < 1e-9
        assert abs(np.dot(t[i], b[i])) < 1e-9
        assert abs(np.linalg.norm(n[i]) - 1.0) < 1e-9


# ---------------------------------------------------------------- state
def test_state_roundtrip_and_stage_status():
    st = DesignState()
    st.set_stage("INPUT_AUDIT", "passed")
    st.log("INPUT_AUDIT", "loaded", file="x.yaml")
    st2 = load_state(st.to_dict())
    assert st2.schema_version == SCHEMA_VERSION
    assert st2.stage_status("INPUT_AUDIT") == "passed"
    assert st2.decision_log[0]["event"] == "loaded"


def test_state_rejects_unknown_schema_version():
    import pytest
    bad = DesignState().to_dict()
    bad["schema_version"] = "0.9-alpha"
    with pytest.raises(ValueError):
        load_state(bad)


# ---------------------------------------------------------------- config units
def test_config_unit_conversion():
    p = config.load(EXAMPLE)
    assert abs(p.horn.length - 1.499) < 1e-9         # 1499 mm
    assert abs(p.horn.mouth_area - 1.6) < 1e-9       # 16000 cm^2
    assert abs(p.driver.rear_volume - 0.028) < 1e-12  # 28000 cm^3
    assert abs(p.driver.Xmax - 0.01135) < 1e-12       # 11.35 mm


def test_acoustic_master_from_design_matches_length():
    from hornflow import theory
    p = config.load(EXAMPLE)
    design = theory.solve_design(p.horn, p.target,
                                 c=p.simulation.c, rho=p.simulation.rho)
    m = AcousticMaster.from_design(design, "cand_x", "front_loaded_horn")
    assert abs(m.length - design.length) < 1e-9
    assert abs(m.throat_area - design.St) < 1e-9
    assert abs(m.mouth_area - design.Sm) < 1e-6
    lat = m.sample_sections(9)
    assert all(sec.area > 0 for sec in lat)


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
