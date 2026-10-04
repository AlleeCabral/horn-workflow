"""Property-based tests (Hypothesis).

Invariants that must hold for ANY geometry, not just the JBL example.

Run:  python3 -m pytest tests/test_properties.py -q
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from hypothesis import given, settings, strategies as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow import fold                                                   # noqa: E402
from hornflow.domain.geometry import AreaLaw, Centreline                    # noqa: E402
from hornflow.domain.ids import stable_id                                  # noqa: E402
from hornflow.manufacturing import meshbuild                               # noqa: E402


@given(x=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False),
       y=st.floats(min_value=-1e6, max_value=1e6, allow_nan=False))
@settings(max_examples=50)
def test_ids_deterministic_under_reorder(x, y):
    assert stable_id("c", {"a": x, "b": y}) == stable_id("c", {"b": y, "a": x})


@given(L=st.floats(min_value=0.2, max_value=8.0, allow_nan=False))
@settings(max_examples=40)
def test_straight_fold_preserves_length(L):
    pts = np.column_stack([np.zeros(30), np.zeros(30), np.linspace(0, L, 30)])
    cl = Centreline(pts)
    assert abs(cl.length - L) < 1e-9 * max(1.0, L)


@given(scale=st.floats(min_value=0.1, max_value=4.0, allow_nan=False))
@settings(max_examples=30)
def test_area_law_never_negative(scale):
    s = np.linspace(0, 3.0, 25)
    base = np.exp(np.linspace(0, 2.0, 25)) * scale
    law = AreaLaw(s, base)
    assert np.all(law.evaluate(s) > 0)


def _tiny_master(L=1.2):
    from hornflow.domain.geometry import AcousticMaster
    s = np.linspace(0, L, 60)
    law = AreaLaw(s, np.exp(np.linspace(np.log(0.05), np.log(1.2), 60)))
    return AcousticMaster(candidate_id="cand_t", architecture_id="folded_horn",
                          profile="exponential", throat_area=0.05, mouth_area=1.2,
                          length=L, area_law=law, aspect=1.6)


@given(R=st.floats(min_value=0.05, max_value=0.9, allow_nan=False))
@settings(max_examples=25, deadline=None)
def test_area_law_preserved_by_fold_mapping(R):
    m = _tiny_master()
    L = m.length
    if np.pi * R / 2.0 >= L:
        return
    pts = fold.paths.jfold_path(L, R)
    cl = Centreline(pts)
    s, S, _secs = fold.sections_along(cl, m)
    rep = m.area_law.error_vs(s, S)
    assert rep.rms < 1e-6       # mapping uses the target area exactly at stations
    assert rep.max_contraction < 1e-6


@given(R=st.floats(min_value=0.05, max_value=0.5, allow_nan=False))
@settings(max_examples=15, deadline=None)
def test_shell_mesh_watertight_for_any_radius(R):
    m = _tiny_master()
    if np.pi * R >= m.length:
        return
    c = fold.build_fold_candidate("u_fold", m,
                                  Centreline(fold.paths.ufold_path(m.length, R)),
                                  {"f_passband_max": 200.0})
    rep = meshbuild.edge_manifold_report(meshbuild.shell_mesh(c, wall_mm=15.0, k=3))
    assert rep["watertight"], rep
