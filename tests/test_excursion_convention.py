"""Excursion convention regression tests (schema/curves v1 -> v2).

These are the tests that must fail if rms and peak excursion are ever confused
again.  The bug they guard: ``curves.csv`` had a column called
``excursion_peak_mm`` that held **rms** displacement, so every "Xmax is reached
at N volts" figure was optimistic by sqrt(2) in voltage and 2x in power.

Run standalone:   python3 tests/test_excursion_convention.py
Run under pytest: python3 -m pytest tests/test_excursion_convention.py -q
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow import config, report, response  # noqa: E402
from hornflow.domain import excursion as ex  # noqa: E402
from hornflow.domain.state import SCHEMA_VERSION, load_state  # noqa: E402
from hornflow.physics.solvers.webster import WebsterSolver  # noqa: E402
from hornflow.workflow.gates import hard_gates  # noqa: E402

EXAMPLE = ROOT / "params" / "horn_jbl_1200b.yaml"

# curves.csv is written with fmt="%.6g", so any round-trip comparison through the
# file must allow one unit in the last place of a 6-significant-digit field
# (~2e-6 relative at these magnitudes).  This is the *file format's* precision,
# not a weakened numerical tolerance: the in-memory comparisons above use 1e-12.
CSV_RTOL = 1e-5


def _result():
    return response.simulate(config.load(EXAMPLE))


# --------------------------------------------------------------------------- #
#  1. the convention itself
# --------------------------------------------------------------------------- #
def test_solver_output_is_rms_not_peak():
    """Proof from the generating calculation, not from the label.

    ``response.simulate`` drives the network with ``sim.voltage`` in volts rms,
    so ``I_abs`` must equal ``V/|Ze|`` and the excursion column is therefore an
    rms displacement - i.e. peak/rms == sqrt(2) exactly.
    """
    p = config.load(EXAMPLE)
    r = _result()
    i_from_v = p.simulation.voltage / np.abs(r.Ze)
    assert np.allclose(np.abs(r.current), i_from_v, rtol=1e-12)
    assert not np.isclose(np.max(np.abs(r.excursion)), 0.0)


def test_peak_is_sqrt2_times_rms_for_the_simulated_array():
    r = _result()
    e = ex.summarize(np.abs(r.excursion), r.f, drive_voltage_vrms=2.83,
                     re_ohm=float(config.load(EXAMPLE).driver.Re))
    assert e.peak_max_m > e.rms_max_m
    assert math.isclose(e.peak_max_m / e.rms_max_m, ex.RMS_TO_PEAK, rel_tol=1e-12)
    assert math.isclose(e.peak_max_m - ex.RMS_TO_PEAK * e.rms_max_m, 0.0, abs_tol=1e-15)


def test_rms_peak_helpers_are_inverses():
    for value in (1e-5, 1e-3, 0.775, 11.35):
        assert math.isclose(ex.peak_to_rms(ex.rms_to_peak(value)), value, rel_tol=1e-15)
    assert math.isclose(ex.PEAK_TO_RMS, 1.0 / ex.RMS_TO_PEAK, rel_tol=1e-15)


# --------------------------------------------------------------------------- #
#  2. curves.csv v2
# --------------------------------------------------------------------------- #
def test_curves_header_is_v2_and_names_both_conventions(tmp_path):
    out = tmp_path / "curves.csv"
    report.write_csv(_result(), out)
    header = out.read_text(encoding="utf-8").splitlines()[0]
    assert header == report.CURVES_HEADER
    assert "excursion_rms_mm" in header and "excursion_peak_mm" in header
    # exactly one unambiguous pair - the old ambiguous name is gone
    assert header.count("excursion_peak_mm") == 1


def test_curves_peak_column_is_sqrt2_times_rms_column(tmp_path):
    out = tmp_path / "curves.csv"
    report.write_csv(_result(), out)
    t = report.read_csv(out)
    assert t.schema == report.CURVES_SCHEMA
    assert t.migrated_from is None
    rms = t.columns["excursion_rms_mm"]
    peak = t.columns["excursion_peak_mm"]
    assert np.allclose(peak, ex.RMS_TO_PEAK * rms, rtol=CSV_RTOL)
    assert np.all(peak >= rms)


def test_curves_still_has_one_row_per_frequency(tmp_path):
    r = _result()
    out = tmp_path / "curves.csv"
    report.write_csv(r, out)
    t = report.read_csv(out)
    assert len(t.columns["freq_hz"]) == len(r.f)
    assert np.allclose(t.columns["freq_hz"], r.f, rtol=CSV_RTOL)


def test_v2_roundtrip_preserves_the_baseline_numbers(tmp_path):
    out = tmp_path / "curves.csv"
    report.write_csv(_result(), out)
    t = report.read_csv(out)
    e = t.excursion_summary(drive_voltage_vrms=2.83, re_ohm=3.6)
    assert math.isclose(e.rms_max_m * 1e3, 0.54858, abs_tol=1e-4)
    assert math.isclose(e.peak_max_m * 1e3, 0.77581, abs_tol=1e-4)


# --------------------------------------------------------------------------- #
#  3. the legacy v1 file is migrated, never reinterpreted
# --------------------------------------------------------------------------- #
def _write_v1(path, r):
    """A byte-faithful v1 curves.csv: rms values under the old column name."""
    x_rms = np.abs(r.excursion) * 1e3
    data = np.column_stack([r.f, np.abs(r.Zt), r.Zt.real, r.Zt.imag, np.abs(r.Ze),
                            np.angle(r.Ze, deg=True), np.abs(r.current), x_rms,
                            np.abs(r.p_axis), r.spl, r.di])
    np.savetxt(path, data, delimiter=",", header=report.CURVES_HEADER_V1,
               comments="", fmt="%.6g")
    return path


def test_legacy_v1_file_is_detected_as_v1(tmp_path):
    p = _write_v1(tmp_path / "old.csv", _result())
    t = report.read_csv(p)
    assert t.schema == report.CURVES_SCHEMA_V1
    assert t.migrated_from == report.CURVES_SCHEMA_V1
    assert t.notes, "a v1 file must come with an explicit migration note"


def test_legacy_v1_values_are_not_reinterpreted(tmp_path):
    """The v1 column held rms: it must become the *rms* column, unchanged."""
    r = _result()
    t = report.read_csv(_write_v1(tmp_path / "old.csv", r))
    assert np.allclose(t.columns["excursion_rms_mm"], np.abs(r.excursion) * 1e3,
                       rtol=CSV_RTOL)
    # the peak column is derived, not copied
    assert np.allclose(t.columns["excursion_peak_mm"],
                       ex.RMS_TO_PEAK * t.columns["excursion_rms_mm"], rtol=CSV_RTOL)
    assert not np.allclose(t.columns["excursion_peak_mm"],
                           t.columns["excursion_rms_mm"], rtol=1e-3)


def test_v1_and_v2_agree_after_migration(tmp_path):
    r = _result()
    a = report.read_csv(_write_v1(tmp_path / "old.csv", r))
    b = report.read_csv(report.write_csv(r, tmp_path / "new.csv"))
    for col in ("freq_hz", "spl_db", "excursion_rms_mm", "excursion_peak_mm"):
        assert np.allclose(a.columns[col], b.columns[col], rtol=CSV_RTOL), col


def test_unrecognised_header_is_rejected(tmp_path):
    p = tmp_path / "junk.csv"
    p.write_text("alpha,beta\n1,2\n", encoding="utf-8")
    try:
        report.read_csv(p)
    except ValueError as exc:
        assert "unrecognised curves header" in str(exc)
    else:
        raise AssertionError("an unknown header must raise, never guess")


# --------------------------------------------------------------------------- #
#  4. Xmax convention
# --------------------------------------------------------------------------- #
def test_xmax_peak_to_peak_is_halved_to_one_way_peak():
    assert ex.xmax_one_way_peak(0.011, ex.ONE_WAY_PEAK) == 0.011
    assert ex.xmax_one_way_peak(0.011, ex.PEAK_TO_PEAK) == 0.0055
    assert math.isclose(ex.xmax_one_way_peak(22.7, ex.PEAK_TO_PEAK), 11.35, rel_tol=1e-12)


def test_xmax_convention_aliases_and_labels():
    for spelling in ("one-way", "one_way", "peak", "Xmax"):
        assert ex.normalize_convention(spelling) == ex.ONE_WAY_PEAK
    for spelling in ("peak-to-peak", "p-p", "P2P"):
        assert ex.normalize_convention(spelling) == ex.PEAK_TO_PEAK
    assert ex.normalize_convention(None) == ex.ONE_WAY_PEAK
    assert ex.convention_label(None) == "one-way peak"


def test_unknown_xmax_convention_raises_rather_than_guessing():
    for bad in ("one way", "half", "", "2-way"):
        try:
            ex.normalize_convention(bad)
        except ValueError:
            continue
        raise AssertionError(f"{bad!r} must raise, not silently default")


def test_driver_defaults_to_one_way_peak_and_validates():
    drv = config.load(EXAMPLE).driver
    assert drv.Xmax_convention == ex.ONE_WAY_PEAK
    assert math.isclose(drv.Xmax_one_way_peak, drv.Xmax, rel_tol=1e-12)
    assert math.isclose(drv.Xmax * 1e3, 11.35, abs_tol=1e-9)


# --------------------------------------------------------------------------- #
#  5. the gate must compare like with like
# --------------------------------------------------------------------------- #
def test_gate_is_like_for_like_peak_vs_one_way_peak():
    x_rms = np.array([0.54858e-3])
    ok, peak, limit, detail = ex.excursion_gate(x_rms, xmax_m=0.01135,
                                                xmax_convention=ex.ONE_WAY_PEAK)
    assert ok
    assert math.isclose(peak, 0.77581e-3, rel_tol=1e-6)
    assert math.isclose(limit, 0.01135, rel_tol=1e-12)
    assert "one-way peak" in detail and "sqrt" not in detail


def test_gate_tightens_when_xmax_is_declared_peak_to_peak():
    """The same driver quoted p-p has half the allowed one-way travel.

    3 mm rms -> 4.24 mm peak, which fits inside 6.75 mm but not inside the
    3.375 mm the same 6.75 mm figure means when it is a p-p number.
    """
    x_rms = np.array([3e-3])
    ok_a, peak_a, limit_a, _ = ex.excursion_gate(x_rms, xmax_m=6.75e-3,
                                                 xmax_convention=ex.ONE_WAY_PEAK)
    ok_b, peak_b, limit_b, _ = ex.excursion_gate(x_rms, xmax_m=6.75e-3,
                                                 xmax_convention=ex.PEAK_TO_PEAK)
    assert math.isclose(limit_a, 2.0 * limit_b, rel_tol=1e-12)
    assert math.isclose(peak_a, peak_b, rel_tol=1e-12)      # same physical travel
    assert ok_a and not ok_b                                # only the limit moved


def test_gate_fails_when_xmax_is_unknown():
    ok, _, _, detail = ex.excursion_gate(np.array([1e-3]), xmax_m=None)
    assert ok is False
    assert "safety-critical" in detail


def test_hard_gate_uses_peak_not_rms():
    """A driver just over the limit in peak terms must fail the hard gate."""
    p = config.load(EXAMPLE)
    run = WebsterSolver(p).solve()
    peak_mm = float(np.max(run.peak_excursion_m)) * 1e3
    rms_mm = float(np.max(run.excursion_rms_m)) * 1e3
    assert peak_mm > rms_mm

    class _Feas:
        rejected: list = []

    # Xmax set exactly between the rms and the peak value: rms would pass,
    # peak must fail.  This is the regression the whole change exists for.
    between = (rms_mm + peak_mm) / 2.0e3
    p.driver.Xmax = between
    g = {r.name: r for r in hard_gates(p, _Feas(), [run])}
    assert g["excursion<=Xmax"].passed is False
    assert "peak travel" in g["excursion<=Xmax"].detail

    p.driver.Xmax = peak_mm * 1.2e-3
    g2 = {r.name: r for r in hard_gates(p, _Feas(), [run])}
    assert g2["excursion<=Xmax"].passed is True


# --------------------------------------------------------------------------- #
#  6. the drive level at which Xmax is reached
# --------------------------------------------------------------------------- #
def test_voltage_at_xmax_uses_the_peak_limit_not_the_rms_one():
    r = _result()
    p = config.load(EXAMPLE)
    e = ex.summarize(np.abs(r.excursion), r.f,
                     drive_voltage_vrms=p.simulation.voltage,
                     re_ohm=float(p.driver.Re), xmax_m=p.driver.Xmax)
    # displacement scales with voltage: rms travel must equal Xmax/sqrt(2)
    v_at = e.voltage_vrms_at_xmax
    rms_travel_at_v_at = v_at * e.rms_max_m / p.simulation.voltage
    assert math.isclose(rms_travel_at_v_at, p.driver.Xmax / ex.RMS_TO_PEAK, rel_tol=1e-9)
    # the old, optimistic figure was sqrt(2) higher
    old_v = p.simulation.voltage * p.driver.Xmax / e.rms_max_m
    assert math.isclose(old_v / v_at, ex.RMS_TO_PEAK, rel_tol=1e-9)
    assert math.isclose(e.power_w_at_xmax, v_at ** 2 / p.driver.Re, rel_tol=1e-9)
    # and the power figure is therefore half of the old one
    assert e.power_w_at_xmax < 0.55 * (old_v ** 2 / p.driver.Re)


def test_summary_reports_both_conventions_and_a_margin():
    r = _result()
    p = config.load(EXAMPLE)
    e = ex.summarize(np.abs(r.excursion), r.f,
                     drive_voltage_vrms=p.simulation.voltage,
                     re_ohm=float(p.driver.Re), xmax_m=p.driver.Xmax)
    d = e.to_dict()
    for key in ("rms_max_m", "peak_max_m", "peak_used_pct", "rms_used_pct",
                "peak_margin_m", "peak_margin_db", "voltage_vrms_at_xmax",
                "power_w_at_xmax", "xmax_convention", "evidence"):
        assert key in d, key
    assert d["peak_used_pct"] > d["rms_used_pct"]
    assert e.evidence == "ANALYTICAL_ESTIMATE"


# --------------------------------------------------------------------------- #
#  7. the report states the convention
# --------------------------------------------------------------------------- #
def test_report_text_names_both_conventions(tmp_path):
    p = config.load(EXAMPLE)
    r = response.simulate(p)
    text = "\n".join(report.guidance_lines(p, r))
    assert "rms" in text and "one-way peak" in text
    assert "Xmax" in text
    assert "V rms" in text
    # the old misleading wording is gone
    assert "mm peak at" not in text
    assert "0.55 mm peak" not in text


def test_report_voltage_figure_matches_the_summary(tmp_path):
    p = config.load(EXAMPLE)
    r = response.simulate(p)
    e = ex.summarize(np.abs(r.excursion), r.f, drive_voltage_vrms=p.simulation.voltage,
                     re_ohm=float(p.driver.Re), xmax_m=p.driver.Xmax)
    text = "\n".join(report.guidance_lines(p, r))
    # the peak travel is what the voltage figure is derived from
    assert f"{e.peak_max_m * 1e3:.2f} mm one-way peak" in text
    assert f"{e.voltage_vrms_at_xmax:.0f} V rms" in text


# --------------------------------------------------------------------------- #
#  8. state schema 1.0 -> 1.1 migration
# --------------------------------------------------------------------------- #
def _state_v1():
    return {
        "schema_version": "1.0",
        "simulation_runs": [{"candidate_id": "c1", "excursion_m": [1e-3, 2e-3, 3e-3]}],
        "decision_log": [],
    }


def test_state_migration_renames_and_derives_peak():
    st = load_state(_state_v1())
    assert st.schema_version == SCHEMA_VERSION
    run = st.simulation_runs[0]
    assert run["excursion_rms_m"] == [1e-3, 2e-3, 3e-3]   # values untouched
    assert "excursion_m" not in run
    expected = [ex.RMS_TO_PEAK * v for v in (1e-3, 2e-3, 3e-3)]
    assert np.allclose(run["excursion_peak_m"], expected, rtol=1e-12)


def test_state_migration_is_recorded_not_silent():
    st = load_state(_state_v1())
    assert st.migrations, "an applied migration must be recorded in the state"
    rec = st.migrations[-1]
    assert rec["from_schema"] == "1.0" and rec["to_schema"] == "1.1"
    assert "rms" in rec["detail"] and "sqrt(2)" in rec["detail"]


def test_state_roundtrip_is_stable_after_migration():
    st = load_state(_state_v1())
    again = load_state(st.to_dict())
    assert again.schema_version == SCHEMA_VERSION
    assert again.simulation_runs == st.simulation_runs
    assert again.migrations == st.migrations


def test_unknown_state_version_still_raises():
    bad = {"schema_version": "0.9-alpha"}
    try:
        load_state(bad)
    except ValueError as exc:
        assert "migration" in str(exc)
    else:
        raise AssertionError("an unknown state version must fail loudly")


if __name__ == "__main__":
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(tmp) if fn.__code__.co_argcount else fn()
                print(f"  ok   {name}")
            except Exception as exc:  # noqa: BLE001
                print(f"  FAIL {name}: {exc}")
                raise
    print("test_excursion_convention: all checks passed")
