"""The -3 dB point and the sweep report must mean what they say (audit P3, P11).

The old cutoff was the first grid point below "band mean minus 3 dB", which is
almost always the lowest frequency in the grid: every sensitivity row reported
20 Hz.  These tests pin the real crossing and the mixed-axis report.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow.metrics import minus3db_cutoff                      # noqa: E402


def test_cutoff_of_a_highpass_is_inside_the_grid():
    f = np.geomspace(20, 500, 400)
    spl = 100 + 10 * np.log10(1 / (1 + (60 / f) ** 8))
    fc = minus3db_cutoff(f, spl, 80, 250)
    assert fc is not None and 55 < fc < 65


def test_cutoff_none_when_never_drops():
    f = np.geomspace(20, 500, 50)
    assert minus3db_cutoff(f, np.full_like(f, 90.0), 80, 250) is None


def test_cutoff_interpolates_in_log_frequency():
    f = np.array([10.0, 100.0, 1000.0])
    spl = np.array([80.0, 100.0, 100.0])
    fc = minus3db_cutoff(f, spl, 100, 1000)
    assert fc is not None and 60 < fc < 80


def test_band_metrics_reports_the_real_cutoff():
    from hornflow.architecture.box_models import band_metrics

    f = np.geomspace(20, 500, 400)
    spl = 100 + 10 * np.log10(1 / (1 + (60 / f) ** 8))
    m = band_metrics(f, spl, 80, 250)
    assert 55 < m["cutoff_minus3db_hz"] < 65


def test_a_mixed_axis_does_not_crash_the_effect_summary(tmp_path):
    """`auto` and a number on one axis must not raise (audit P11).

    The plan asked for a `write_report` call; a `SweepRow` that the report can
    summarise needs a full solver result, so this pins the fault line instead:
    the report called `_effect` for every axis, and `sorted` raised TypeError on
    the mixed values before anything was written.
    """
    from hornflow import sweep

    rows = [sweep.SweepRow(label="auto", overrides={"horn.length": "auto"}, ok=True,
                           metrics={"spl_variation_db": 3.0}),
            sweep.SweepRow(label="1200", overrides={"horn.length": 1200}, ok=True,
                           metrics={"spl_variation_db": 4.0})]
    assert isinstance(sweep._effect(rows, "horn.length"), str)
    # and a purely numeric axis still says which way it moves the variation
    numeric = [sweep.SweepRow(label="1200", overrides={"horn.length": 1200}, ok=True,
                              metrics={"spl_variation_db": 4.0}),
               sweep.SweepRow(label="1800", overrides={"horn.length": 1800}, ok=True,
                              metrics={"spl_variation_db": 3.0})]
    assert "length" in sweep._effect(numeric, "horn.length")

if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
