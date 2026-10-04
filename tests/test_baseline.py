"""Milestone 0 - baseline regression.

The validated JBL 1200B example must keep reproducing the numbers captured in
tests/fixtures/baseline/manifest.json.  This guards every later refactor: if the
acoustic core drifts, this file fails first.

Run standalone:   python3 tests/test_baseline.py
Run under pytest: python3 -m pytest tests/test_baseline.py -q
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow import config, report, response  # noqa: E402
from hornflow.domain.excursion import RMS_TO_PEAK  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "baseline"
MAN = json.loads((FIX / "manifest.json").read_text(encoding="utf-8"))
M = MAN["metrics"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result():
    return response.simulate(config.load(ROOT / MAN["example"]))


def test_input_files_are_frozen():
    """The example inputs must not change silently."""
    for rel, digest in MAN["checksums"].items():
        if rel.endswith(".yaml"):
            assert _sha256(ROOT / rel) == digest, f"{rel} changed since baseline"


def test_baseline_is_deterministic():
    a, b = _result(), _result()
    for key in ("spl", "Ze", "excursion", "Zt"):
        assert np.array_equal(getattr(a, key), getattr(b, key))


def test_metrics_match_baseline():
    r = _result()
    t = config.load(ROOT / MAN["example"]).target
    exc = np.abs(r.excursion)
    got = {
        "n_frequencies": int(len(r.f)),
        "spl_band_mean_db": r.band_spl(t.f_low, t.f_high),
        "spl_band_variation_db": r.variations_db(t.f_low, t.f_high),
        "ze_min_ohm": float(np.min(np.abs(r.Ze))),
        "ze_max_ohm": float(np.max(np.abs(r.Ze))),
        "excursion_rms_max_mm": float(np.max(exc)) * 1e3,
        "excursion_peak_max_mm": float(np.max(exc)) * RMS_TO_PEAK * 1e3,
        "di_min_db": float(np.min(r.di)),
        "di_max_db": float(np.max(r.di)),
        "k_rm_at_fc": float(r.derived["k_rm_at_fc"]),
        "f_1P_validity_hz": float(r.derived["f_1P_validity_hz"]),
    }
    for k, want in M.items():
        if k not in got:
            continue
        assert abs(got[k] - want) <= 1e-3, f"{k}: {got[k]} != baseline {want}"


def test_curves_csv_is_byte_identical(tmp_path):
    """The exported curve table is deterministic and matches the fixture."""
    r = _result()
    out = tmp_path / "curves.csv"
    report.write_csv(r, out)
    assert _sha256(out) == MAN["checksums"]["jbl_1200b_curves.csv"]
    assert _sha256(out) == _sha256(FIX / "jbl_1200b_curves.csv")


if __name__ == "__main__":
    try:
        import pytest
    except ImportError:  # pragma: no cover
        # minimal standalone fallback
        test_input_files_are_frozen()
        test_baseline_is_deterministic()
        test_metrics_match_baseline()
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            test_curves_csv_is_byte_identical(Path(d))
        print("test_baseline: all checks passed")
    else:
        raise SystemExit(pytest.main([__file__, "-q"]))
