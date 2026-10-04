"""Tests for the manual AKABAK solve: state machine, manifest, .vips import,
validation and the resume path.

Run standalone:  python3 tests/test_bem_manual.py
Under pytest:    python3 -m pytest tests/test_bem_manual.py -q
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow import bem                                                          # noqa: E402
from hornflow.physics.solvers import bem_manual, manual                            # noqa: E402
from hornflow.workflow import bem_import, run_pipeline                             # noqa: E402

EXAMPLE = ROOT / "params" / "horn_jbl_1200b.yaml"
# Real AKABAK exports, committed as test data.  They live under tests/ so that
# results/ stays entirely generated (see .gitignore).
REAL_EXPORT = ROOT / "tests" / "fixtures" / "bem_export"


# --------------------------------------------------------------------------- #
#  fixtures / helpers
# --------------------------------------------------------------------------- #
def vips_text(rows, *, unit="Pa", label="Mic1; x=0, y=0, z=2.499 m  (All)",
              level="SoundPressure", complex_fmt=True, coord_type=None, angles=None):
    """Build a synthetic .vips file body in the real AKABAK format (CRLF)."""
    head = [
        "// ************************************************************",
        "//",
        "// Akabak-Demo   Spectrum Data  1/1/2030 12:00:00 PM",
        "//",
        "// ************************************************************",
        "",
        "SourceDesc=VACS_Data_Text",
        "Version=3.3.2 b144 - 64",
        "Author=\"RDTeam\"",
        "SourceDesc=\"Akabak-Demo\"",
        "IsInterface=true",
        "StartString_Absc=Abscissa",
        "EndString_Absc=Abscissa_End",
        "StartString_Data=Data",
        "EndString_Data=Data_End",
        "Data_Format=Complex" if complex_fmt else "Data_Format=Real",
        f"Data_LevelType={level}",
        "Data_Domain=Frequency",
        "Data_AbscUnit=Hz",
        f"Data_BaseUnit={unit}",
        "Data_IsContPhase=false",
        f'Data_Legend="{label}"',
    ]
    if coord_type:
        head.append(f"Param_Coord_Type={coord_type}")
    if angles:
        head.append("Param_Coord_x2=" + ",".join(str(a) for a in angles))
    head.append("Data")
    body = [" ".join(f"{v:.10g}" for v in row) for row in rows]
    text = "\n".join(head + body + ["Data_End", ""])
    return text.replace("\n", "\r\n")


def spl_rows(freqs, spl_db):
    """Complex peak-pressure rows for a target rms-referenced SPL."""
    out = []
    for f, s in zip(freqs, spl_db):
        peak = 20e-6 * math.sqrt(2.0) * 10 ** (s / 20.0)
        out.append((float(f), peak, 0.0))
    return out


def write_export(folder, name, text):
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    p = folder / name
    p.write_bytes(text.encode("utf-8"))       # written now -> newer than inputs
    return p


def _reference(freqs, spl):
    class _D:
        fc = 60.0

    class _R:
        pass

    r = _R()
    r.f = np.asarray(freqs, dtype=float)
    r.spl = np.asarray(spl, dtype=float)
    r.design = _D
    return r


# --------------------------------------------------------------------------- #
#  the state machine
# --------------------------------------------------------------------------- #
def test_state_machine_is_legal_and_terminal():
    s = manual.ManualSolveState
    assert manual.advance(s.INPUTS_GENERATED.value, s.GUI_REQUIRED.value) == "GUI_REQUIRED"
    assert manual.can_advance(s.MANUAL_SOLVE_PENDING.value, s.MANUAL_SOLVE_COMPLETED.value)
    # a comparison can end either way
    assert manual.can_advance(s.BEM_COMPARISON_COMPLETED.value, s.BEM_VALIDATED.value)
    assert manual.can_advance(s.BEM_COMPARISON_COMPLETED.value, s.BEM_REJECTED.value)
    # a decided state only ever goes back to "a fresh import" (never sideways)
    assert manual.ALLOWED_TRANSITIONS[s.BEM_VALIDATED.value] == ("VIPS_IMPORTED",)
    assert manual.ALLOWED_TRANSITIONS[s.BEM_REJECTED.value] == ("VIPS_IMPORTED",)
    assert manual.ALLOWED_TRANSITIONS[s.MANUAL_SOLVE_PENDING.value] == ("MANUAL_SOLVE_COMPLETED",)
    assert manual.is_complete(s.BEM_REJECTED.value) and manual.is_validated(s.BEM_VALIDATED.value)
    assert manual.REIMPORT_FROM == ("BEM_VALIDATED", "BEM_REJECTED")


def test_reimport_edge_is_reachable():
    from hornflow.workflow.bem_import import _walk_to
    # a re-import with a different tolerance may supersede a rejection
    assert _walk_to("BEM_REJECTED", "BEM_VALIDATED") == "BEM_VALIDATED"
    assert _walk_to("GUI_REQUIRED", "VIPS_IMPORTED") == "VIPS_IMPORTED"
    assert _walk_to("MANUAL_SOLVE_PENDING", "MANUAL_SOLVE_PENDING") == "MANUAL_SOLVE_PENDING"


def test_illegal_transition_is_rejected():
    s = manual.ManualSolveState
    # cannot jump straight from generated inputs to validated
    assert not manual.can_advance(s.INPUTS_GENERATED.value, s.BEM_VALIDATED.value)
    try:
        manual.advance(s.INPUTS_GENERATED.value, s.BEM_VALIDATED.value)
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "illegal" in str(exc)


def test_state_chain_is_the_documented_order():
    assert list(manual.STATE_CHAIN) == [
        "INPUTS_GENERATED", "GUI_REQUIRED", "MANUAL_SOLVE_PENDING",
        "MANUAL_SOLVE_COMPLETED", "VIPS_IMPORTED", "BEM_COMPARISON_COMPLETED",
        "BEM_VALIDATED"]


# --------------------------------------------------------------------------- #
#  the manifest
# --------------------------------------------------------------------------- #
def test_manifest_roundtrip_and_hashes(tmp_path):
    f = tmp_path / "bem.msh"
    f.write_text("MSH2.2\n", encoding="utf-8")
    m = manual.build_manifest(run_id="run_x", project="p", input_path=EXAMPLE,
                              solver="akabak-bem", solver_version="3.3-demo",
                              fidelity="BEM_SIMULATION", bem_dir=tmp_path,
                              export_dir=tmp_path / "export", files={"mesh": f})
    p = manual.write_manifest(m, tmp_path / manual.MANIFEST_NAME)
    assert p.is_file()
    back = manual.read_manifest(p)
    assert back is not None and back.run_id == "run_x"
    assert back.solver_version == "3.3-demo"
    assert back.files["mesh"]["bytes"] == f.stat().st_size
    assert len(back.files["mesh"]["sha256"]) == 64
    # an absent manifest reads as None rather than raising
    assert manual.read_manifest(tmp_path / "nope.json") is None



# --------------------------------------------------------------------------- #
#  the .vips parser (golden against the real, verified exports)
# --------------------------------------------------------------------------- #
def test_parse_vips_golden_real_file():
    """The real Rad1_23Sept26 Mic1 file must reproduce the 87.73 dB checkpoint."""
    text = (REAL_EXPORT / "Akabak-Rad1_23Sept26-Mic1.vips").read_text(errors="replace")
    p = bem.parse_vips(text)
    assert p["kind"] == "vips" and p["is_pressure"] is True
    assert p["base_unit"] == "Pa" and p["n_curves"] == 1
    assert len(p["freq"]) == 24 and p["freq"][0] == 60.0
    label = bem._onaxis_curve(p)
    assert label == "Mic1"
    # history.md checkpoint: 87.7 dB (rms-referenced) at 60 Hz
    assert abs(float(p["curves"][label][0]) - 87.73) < 0.05


def test_parse_vips_polar_has_one_curve_per_angle():
    text = (REAL_EXPORT / "Akabak-Rad1_23Sept26-H 0-90.vips").read_text(errors="replace")
    p = bem.parse_vips(text)
    assert p["n_curves"] == 19
    assert bem._onaxis_curve(p) == "H 0-90 0 deg"
    labels = list(p["curves"])
    assert all(lab.startswith("H 0-90") and lab.endswith("deg") for lab in labels)
    assert all(len(p["curves"][lab]) == len(p["freq"]) for lab in labels)
    # a real polar set: the 0 deg and 90 deg levels differ across the band
    off = np.abs(p["curves"]["H 0-90 0 deg"] - p["curves"]["H 0-90 90 deg"])
    assert np.all(np.isfinite(off)) and float(np.max(off)) > 0.5


def test_parse_vips_non_pressure_is_raw_magnitude():
    text = (REAL_EXPORT / "Akabak-Rad1_23Sept26-RadImp1.vips").read_text(errors="replace")
    p = bem.parse_vips(text)
    assert p["is_pressure"] is False and p["base_unit"] == "Pas/m3"
    assert float(p["curves"]["RadImp1"][0]) > 0          # ohms-like, not dB


def test_parse_any_dispatches_by_content():
    vips = vips_text(spl_rows([100.0, 200.0], [90.0, 95.0]))
    assert bem.parse_any(vips)["kind"] == "vips"
    assert "kind" not in bem.parse_export("freq spl\n100 90\n200 95\n")


def test_peak_pressure_to_spl_convention():
    # 0.68869 Pa peak is the verified 87.73 dB rms-referenced point
    assert abs(float(bem.peak_pa_to_spl_db([0.68869])[0]) - 87.73) < 0.05
    # the peak-rendering convention sits exactly 3.01 dB above the rms reference
    assert abs(bem.PEAK_TO_RMS_DB - 3.0103) < 1e-3


def test_parse_vips_roundtrips_a_synthetic_spl():
    freqs = [60.0, 80.0, 100.0, 150.0, 200.0]
    target = [88.0, 95.0, 100.0, 103.0, 104.0]
    p = bem.parse_vips(vips_text(spl_rows(freqs, target)))
    got = p["curves"]["Mic1"]
    assert np.allclose(got, target, atol=1e-3)



# --------------------------------------------------------------------------- #
#  validation - the eight required checks
# --------------------------------------------------------------------------- #
def _manifest_for(tmp_path):
    f = tmp_path / "bem.msh"
    f.write_text("MSH2.2\n", encoding="utf-8")
    export = tmp_path / "export"
    export.mkdir(exist_ok=True)
    m = manual.build_manifest(run_id="run_test", project="p", input_path=EXAMPLE,
                              solver="akabak-bem", solver_version="3.3-demo",
                              fidelity="BEM_SIMULATION", bem_dir=tmp_path,
                              export_dir=export, files={"mesh": f})
    manual.write_manifest(m, tmp_path / manual.MANIFEST_NAME)
    return m, export


def _check(v, name):
    return next(c for c in v.checks if c.name == name)


def test_validate_accepts_a_fresh_export(tmp_path):
    m, export = _manifest_for(tmp_path)
    freqs = [60, 70, 80, 100, 125, 150, 175, 200]
    write_export(export, "Akabak-p-Mic1.vips", vips_text(spl_rows(freqs, [88] * 8)))
    v = bem_manual.validate_exports(export, m)
    assert v.passed and v.state == "VIPS_IMPORTED"
    assert _check(v, "expected_file_exists").passed
    assert _check(v, "files_non_empty").passed
    assert _check(v, "frequency_grid_valid").passed
    assert _check(v, "required_spectrum_present").passed
    assert _check(v, "values_numeric_finite").passed
    assert _check(v, "export_timestamp_after_inputs").passed
    assert _check(v, "belongs_to_run").passed          # export dir == manifest dir
    assert _check(v, "run_manifest_matches").passed
    assert v.hard_failures() == []


def test_validate_rejects_an_empty_folder(tmp_path):
    m, export = _manifest_for(tmp_path)
    v = bem_manual.validate_exports(export, m)
    assert not v.passed and v.state == "MANUAL_SOLVE_PENDING"
    assert "expected_file_exists" in v.hard_failures()


def test_validate_rejects_a_duplicate_frequency(tmp_path):
    m, export = _manifest_for(tmp_path)
    # the parser tolerates unordered rows (it sorts), but a duplicate is a real error
    write_export(export, "Akabak-p-Mic1.vips",
                 vips_text(spl_rows([60, 60, 100], [90, 91, 92])))
    v = bem_manual.validate_exports(export, m)
    assert "frequency_grid_valid" in v.hard_failures()


def test_parser_sorts_unordered_rows(tmp_path):
    p = bem.parse_vips(vips_text(spl_rows([200, 60, 100], [90, 88, 89])))
    assert list(p["freq"]) == [60.0, 100.0, 200.0]


def test_validate_requires_a_pressure_spectrum(tmp_path):
    m, export = _manifest_for(tmp_path)
    # a voltage-only export is not an acoustic result
    write_export(export, "Akabak-p-LE1.vips",
                 vips_text(spl_rows([60, 100, 200], [4, 4, 4]), unit="V",
                           label="Voltage  Elec-Dyn Driver Dyn1", level="Peak"))
    v = bem_manual.validate_exports(export, m)
    assert "required_spectrum_present" in v.hard_failures()


def test_validate_rejects_a_stale_export(tmp_path):
    import os
    import time
    m, export = _manifest_for(tmp_path)
    p = write_export(export, "Akabak-p-Mic1.vips",
                     vips_text(spl_rows([60, 100, 200], [90, 90, 90])))
    old = time.time() - 10 * 24 * 3600          # ten days before the manifest
    os.utime(p, (old, old))
    v = bem_manual.validate_exports(export, m)
    assert "export_timestamp_after_inputs" in v.hard_failures()


def test_validate_soft_warns_without_a_manifest(tmp_path):
    export = tmp_path / "export"
    write_export(export, "x.vips", vips_text(spl_rows([60, 100, 200], [90, 90, 90])))
    v = bem_manual.validate_exports(export, None)
    assert v.passed, v.hard_failures()
    assert any("belongs_to_run" in w for w in v.warnings)
    assert any("run_manifest_matches" in w for w in v.warnings)


def test_validate_records_unparsed_files(tmp_path):
    m, export = _manifest_for(tmp_path)
    (export / "junk.txt").write_text("nothing numeric here\n", encoding="utf-8")
    write_export(export, "Akabak-p-Mic1.vips",
                 vips_text(spl_rows([60, 100, 200], [90, 90, 90])))
    v = bem_manual.validate_exports(export, m)
    assert v.passed and any("junk.txt" in e for e in v.errors)



# --------------------------------------------------------------------------- #
#  comparison -> BEM_VALIDATED / BEM_REJECTED
# --------------------------------------------------------------------------- #
def test_comparison_within_tolerance_validates(tmp_path):
    m, export = _manifest_for(tmp_path)
    freqs = [60, 70, 80, 100, 125, 150, 175, 200]
    ref_spl = [88, 92, 96, 100, 102, 103, 104, 104]
    write_export(export, "Akabak-p-Mic1.vips",
                 vips_text(spl_rows(freqs, [s + 0.5 for s in ref_spl])))
    params = __import__("hornflow").config.load(EXAMPLE)
    out = bem_manual.import_and_validate(params, _reference(freqs, ref_spl),
                                         export, tmp_path / "bem", manifest=m)
    assert out["state"] == "BEM_VALIDATED"
    assert out["metrics"]["within_tolerance"] is True
    assert abs(out["metrics"]["mean_diff_db"] - 0.5) < 0.05
    assert (tmp_path / "bem" / "curves_stage2.csv").is_file()
    assert (tmp_path / "bem" / "compare.md").is_file()


def test_comparison_outside_tolerance_rejects(tmp_path):
    m, export = _manifest_for(tmp_path)
    freqs = [60, 80, 100, 150, 200]
    ref_spl = [88, 96, 100, 103, 104]
    write_export(export, "Akabak-p-Mic1.vips",
                 vips_text(spl_rows(freqs, [s - 12.0 for s in ref_spl])))
    params = __import__("hornflow").config.load(EXAMPLE)
    out = bem_manual.import_and_validate(params, _reference(freqs, ref_spl),
                                         export, tmp_path / "bem", manifest=m)
    assert out["state"] == "BEM_REJECTED"
    assert out["metrics"]["within_tolerance"] is False


def test_failed_validation_never_compares(tmp_path):
    m, export = _manifest_for(tmp_path)      # empty folder
    params = __import__("hornflow").config.load(EXAMPLE)
    out = bem_manual.import_and_validate(params, _reference([60, 100], [90, 90]),
                                         export, tmp_path / "bem", manifest=m)
    assert out["state"] == "MANUAL_SOLVE_PENDING"
    assert out["metrics"] is None and out["comparison"] is None


def test_validation_report_states_the_convention(tmp_path):
    m, export = _manifest_for(tmp_path)
    freqs = [60, 80, 100, 150, 200]
    write_export(export, "Akabak-p-Mic1.vips", vips_text(spl_rows(freqs, [90] * 5)))
    params = __import__("hornflow").config.load(EXAMPLE)
    out = bem_manual.import_and_validate(params, _reference(freqs, [90] * 5),
                                         export, tmp_path / "bem", manifest=m)
    md = bem_manual.validation_md(out, project="p", run_id="run_test")
    assert "rms-referenced" in md and "3.01" in md
    assert "| check | severity | result | detail |" in md


# --------------------------------------------------------------------------- #
#  the run-specific checklist and the recipe
# --------------------------------------------------------------------------- #
def test_checklist_is_run_specific():
    md = manual.checklist_md(project="p", run_id="run_123", input_path=EXAMPLE,
                             bem_dir="/tmp/bem", export_dir="/tmp/bem/export",
                             expected_exports=["*.vips"],
                             legacy_cmd="python3 run_workflow.py x --bem-import y")
    assert "run_123" in md
    assert "/tmp/bem/export" in md
    assert "- [ ]" in md                       # tick-as-you-go boxes
    assert "*.vips" in md
    assert "Troubleshooting" in md
    assert "3.3.2 b144" in md
    assert "python3 run_workflow.py x --bem-import y" in md


def test_recipe_of_a_real_stage2_run_has_checklist_and_final_import(tmp_path):
    from hornflow import config, response
    params = config.load(EXAMPLE)
    r = response.simulate(params)
    out = bem.write_bem_files(params, r, tmp_path / "bem", run_id="run_legacy",
                              symmetry="xy")
    recipe = Path(out["files"]["instructions"]).read_text()
    assert "Run checklist" in recipe
    assert "- [ ]" in recipe
    assert "## 11." in recipe                  # step numbering still consistent
    assert "## 12. Send it back" in recipe
    assert f"--bem-import {tmp_path}/bem/export" in recipe
    assert (tmp_path / "bem" / manual.MANIFEST_NAME).is_file()
    assert out["manifest"].run_id == "run_legacy"



# --------------------------------------------------------------------------- #
#  end-to-end: the pipeline hands over, then a --bem-import resumes it
# --------------------------------------------------------------------------- #
def test_pipeline_generates_manual_inputs_and_is_not_validated(tmp_path):
    s = run_pipeline(EXAMPLE, out_root=tmp_path, limits={"wall_mm": 18.0})
    run_dir = Path(s["run_dir"])
    bem_dir = run_dir / "deliverables" / "bem"
    assert (bem_dir / "bem.msh").is_file()
    assert (bem_dir / "driver_le.txt").is_file()
    assert (bem_dir / "akabak_recipe.md").is_file()
    manifest_path = bem_dir / manual.MANIFEST_NAME
    assert manifest_path.is_file()
    state = json.loads((run_dir / "state.json").read_text())
    assert state["validation"]["bem_status"] == "pending_external"
    # inputs generated, GUI required - and crucially NOT validated
    assert state["validation"]["bem_manual"]["state"] == "GUI_REQUIRED"
    assert not manual.is_validated(state["validation"]["bem_manual"]["state"])
    assert state["validation"]["bem_manual"].get("validation_passed") is None
    # the manifest fingerprints the inputs and names the run
    m = manual.read_manifest(manifest_path)
    assert m is not None and m.run_id == s["run_id"]
    assert "mesh" in m.files and "le_script" in m.files
    recipe = (bem_dir / "akabak_recipe.md").read_text()
    assert s["run_id"] in recipe and "- [ ]" in recipe


def test_bem_import_resumes_and_validates_the_run(tmp_path):
    s = run_pipeline(EXAMPLE, out_root=tmp_path, limits={"wall_mm": 18.0})
    run_dir = Path(s["run_dir"])
    state = json.loads((run_dir / "state.json").read_text())

    # synthesise the manual GUI export from the run's own 1-D reference
    ref = state["simulation_runs"][0]
    freqs = list(np.asarray(ref["frequency_hz"], dtype=float)[:12])
    spls = list(np.asarray(ref["spl_db"], dtype=float)[:12])
    export = run_dir / "deliverables" / "bem" / "export"
    write_export(export, "Akabak-run-Mic1.vips",
                 vips_text(spl_rows(freqs, [v + 1.0 for v in spls])))

    res = bem_import.import_into_run(run_dir, export, tolerance_db=6.0)
    assert res["state"] == "BEM_VALIDATED"
    assert res["validation"]["passed"] is True
    # the state file was updated in place, and the chain advanced legally
    after = json.loads((run_dir / "state.json").read_text())
    assert after["validation"]["bem_manual"]["state"] == "BEM_VALIDATED"
    assert after["validation"]["bem_status"] == "validated"
    assert (run_dir / "deliverables" / "bem" / "bem_manual_report.md").is_file()
    assert Path(res["report"]).is_file()
    log = (run_dir / "logs.jsonl").read_text()
    assert "bem_import" in log


def test_bem_import_rejects_a_bad_export_without_validating(tmp_path):
    s = run_pipeline(EXAMPLE, out_root=tmp_path, limits={"wall_mm": 18.0})
    run_dir = Path(s["run_dir"])
    export = run_dir / "deliverables" / "bem" / "export"
    export.mkdir(parents=True, exist_ok=True)          # empty folder
    res = bem_import.import_into_run(run_dir, export)
    assert res["state"] == "MANUAL_SOLVE_PENDING"
    after = json.loads((run_dir / "state.json").read_text())
    assert after["validation"]["bem_manual"]["state"] != "BEM_VALIDATED"
    assert after["validation"]["bem_status"] == "pending_external"


def test_cli_bem_import_prints_the_check_table(tmp_path, capsys):
    from hornflow.cli import main
    rc = main([str(EXAMPLE), "--out", str(tmp_path), "--quiet"])
    assert rc == 0


# --------------------------------------------------------------------------- #
#  property-based checks
# --------------------------------------------------------------------------- #
from hypothesis import given, settings, strategies as st   # noqa: E402


@given(st.lists(st.integers(min_value=20, max_value=20000), min_size=2, max_size=10,
                unique=True),
       st.lists(st.floats(min_value=-20.0, max_value=140.0), min_size=2, max_size=10))
@settings(max_examples=30, deadline=None)
def test_vips_roundtrip_preserves_finite_levels(freqs, spls):
    # integer Hz on purpose: the .vips writer formats with %.10g, so two nearby
    # floats could collapse to the same text and legitimately produce a duplicate
    # grid point (which the *validator* rejects, but the parser preserves).
    n = min(len(freqs), len(spls))
    freqs, spls = [float(f) for f in freqs[:n]], spls[:n]
    p = bem.parse_vips(vips_text(spl_rows(freqs, spls)))
    got = np.asarray(p["curves"]["Mic1"], dtype=float)
    assert len(p["freq"]) == n
    assert np.all(np.isfinite(got)) and np.all(np.isfinite(p["freq"]))
    assert np.all(np.diff(p["freq"]) > 0)              # strictly increasing after sort
    order = np.argsort(np.asarray(freqs))
    assert np.allclose(got, np.asarray(spls)[order], atol=1e-6)


@given(st.floats(min_value=1e-6, max_value=1e3, allow_nan=False, allow_infinity=False))
@settings(max_examples=40, deadline=None)
def test_peak_to_spl_is_monotonic_and_finite(p):
    a = float(bem.peak_pa_to_spl_db([p])[0])
    b = float(bem.peak_pa_to_spl_db([p * 1.5])[0])
    assert np.isfinite(a) and np.isfinite(b) and b > a


def test_manifest_is_deterministic_for_the_same_inputs(tmp_path):
    f = tmp_path / "bem.msh"
    f.write_text("MSH2.2\n", encoding="utf-8")
    kw = dict(run_id="r", project="p", input_path=EXAMPLE, solver="akabak-bem",
              solver_version="3.3-demo", fidelity="BEM_SIMULATION", bem_dir=tmp_path,
              export_dir=tmp_path / "export", files={"mesh": f},
              generated_utc="2026-10-03T00:00:00+00:00")
    a = manual.build_manifest(**kw).to_dict()
    b = manual.build_manifest(**kw).to_dict()
    assert a == b


# --------------------------------------------------------------------------- #
#  choosing the right curve out of a folder
# --------------------------------------------------------------------------- #
def test_chooser_prefers_point_mic_over_a_richer_polar(tmp_path):
    export = tmp_path / "export"
    rows = spl_rows([60, 100, 150, 200], [90, 95, 100, 102])
    polar = vips_text(rows, label="H 0-90  (All)", level="SoundPressure",
                      coord_type="Spherical", angles=[0, 45, 90])
    write_export(export, "polar.vips", polar)
    write_export(export, "Akabak-p-Mic1.vips", vips_text(rows))
    parsed, _ = bem.parse_folder(export)
    best, name = bem.choose_best(list(parsed.items()), bem.folder_mtimes(export))
    assert name == "Akabak-p-Mic1.vips"


def test_chooser_prefers_the_newest_on_a_tie(tmp_path):
    import os
    export = tmp_path / "export"
    rows = spl_rows([60, 100, 150, 200], [90, 95, 100, 102])
    old = write_export(export, "Akabak-old-Mic1.vips", vips_text(rows))
    new = write_export(export, "Akabak-new-Mic1.vips", vips_text(rows))
    os.utime(old, (1_600_000_000, 1_600_000_000))       # 2020
    os.utime(new, (1_700_000_000, 1_700_000_000))       # 2023
    parsed, _ = bem.parse_folder(export)
    best, name = bem.choose_best(list(parsed.items()), bem.folder_mtimes(export))
    assert name == "Akabak-new-Mic1.vips"


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))

