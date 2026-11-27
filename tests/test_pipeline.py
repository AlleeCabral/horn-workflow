"""Integration tests: the full gated pipeline and its artifacts.

Run:  python3 -m pytest tests/test_pipeline.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow.workflow import run_pipeline, Stage                          # noqa: E402
from hornflow.workflow.stages import STAGE_ORDER, ready                    # noqa: E402
from hornflow.domain.state import SCHEMA_VERSION                           # noqa: E402
from hornflow.io.state_store import load_state_file                        # noqa: E402

EXAMPLE = ROOT / "params" / "horn_jbl_1200b.yaml"


def _run(tmp_path, limits=None):
    return run_pipeline(EXAMPLE, out_root=tmp_path, limits=limits or {"wall_mm": 18.0})


def test_pipeline_runs_and_writes_artifacts(tmp_path):
    s = _run(tmp_path)
    d = Path(s["deliverables"])
    assert (d / "report.md").is_file()
    assert Path(s["run_dir"], "state.json").is_file()
    assert Path(s["run_dir"], "logs.jsonl").is_file()
    assert (d / "viewer" / "viewer.html").is_file()
    assert (d / "viewer" / "scene.glb").is_file()
    assert (d / "printed.stl").is_file()
    assert (d / "step.DEFERRED.txt").is_file()


def test_all_core_stages_passed(tmp_path):
    s = _run(tmp_path)
    core = [Stage.INPUT_AUDIT, Stage.PHYSICAL_FEASIBILITY,
            Stage.ARCHITECTURE_SCREENING, Stage.FOLD_TOPOLOGY_GENERATION,
            Stage.FOLD_GEOMETRY_VALIDATION, Stage.ONE_DIMENSIONAL_SIMULATION,
            Stage.MANUFACTURING_TRANSFORMATION, Stage.CONSTRAINT_SENSITIVITY,
            Stage.INDEPENDENT_CRITIQUE, Stage.FINAL_COMPARISON, Stage.REPORT_AND_EXPORT]
    for st in core:
        assert s["stages"][st.value]["status"] == "passed", (st.value, s["stages"])


def test_best_folded_and_best_overall_reported(tmp_path):
    s = _run(tmp_path)
    assert s["best_folded"] in ("straight", "j_fold", "u_fold")
    assert s["best_overall"] is not None
    state = json.loads(Path(s["run_dir"], "state.json").read_text())
    fr = state["final_recommendations"]
    assert "best_folded_horn" in fr and "best_overall" in fr


def test_state_is_valid_and_reloadable(tmp_path):
    s = _run(tmp_path)
    from hornflow.io.state_store import load_state_file
    st = load_state_file(Path(s["run_dir"], "state.json"))
    assert st.schema_version == SCHEMA_VERSION
    assert st.stage_status("REPORT_AND_EXPORT") == "passed"
    # a finished run says so, so an interrupted one cannot look the same
    assert st.run["status"] == "completed"
    assert len(st.fold_candidates) >= 3
    assert st.simulation_runs
    # the normalized run schema carries both excursion conventions
    assert "excursion_rms_m" in st.simulation_runs[0]
    assert "excursion_peak_m" in st.simulation_runs[0]


def test_hard_gate_blocks_when_volume_limit_tight(tmp_path):
    # an absurdly small volume limit must surface as a failed gate (not an exception)
    s = _run(tmp_path, limits={"wall_mm": 18.0, "max_external_volume_m3": 0.001})
    state = json.loads(Path(s["run_dir"], "state.json").read_text())
    gate_names = [f["check"] for f in state["critic_findings"]]
    assert "hard_constraints" in gate_names


def test_rerun_is_independent_and_does_not_overwrite(tmp_path):
    a = _run(tmp_path)
    b = _run(tmp_path)
    assert a["run_id"] != b["run_id"]
    assert Path(a["run_dir"]).is_dir() and Path(b["run_dir"]).is_dir()


def test_stage_dag_is_respected():
    # a fresh state cannot run a downstream stage
    assert not ready(Stage.REPORT_AND_EXPORT, {})
    assert ready(Stage.INPUT_AUDIT, {})
    assert not ready(Stage.FOLD_TOPOLOGY_GENERATION,
                     {Stage.IDEAL_ACOUSTIC_OPTIMIZATION.value: {"status": "pending"}})


# ------------------------------------------------------ failures and interrupts
def test_zero_valid_folds_is_data_not_a_crash(tmp_path, monkeypatch):
    """No valid fold is an engineering answer, not a TypeError (audit S5).

    The plan forced this with ``max_fold_count: 0``, but a straight fold has no
    bends, so it stays valid and the failure path is never reached.  Returning
    no candidates at all is the same case, one step earlier.
    """
    from hornflow import fold

    monkeypatch.setattr(fold, "generators", lambda: [])
    s = _run(tmp_path, limits={"wall_mm": 18.0})
    st = load_state_file(Path(s["run_dir"]) / "state.json")
    rec = st.stages["FOLD_GEOMETRY_VALIDATION"]
    assert rec["status"] == "failed"
    assert rec["failure"]["recoverable"] is False
    assert rec["failure"]["category"] == "GEOMETRY"


def test_interrupted_run_is_listed(tmp_path, monkeypatch):
    from hornflow.workflow import orchestrator as o

    def boom(self):
        raise KeyboardInterrupt

    monkeypatch.setattr(o.Pipeline, "stage_architecture", boom)
    with pytest.raises(KeyboardInterrupt):
        run_pipeline(EXAMPLE, out_root=tmp_path)
    (run_dir,) = tmp_path.iterdir()
    st = load_state_file(run_dir / "state.json")
    assert st.run["status"] == "interrupted"
    # every stage that finished before the interrupt is already on disk
    assert st.stages["PHYSICAL_FEASIBILITY"]["status"] == "passed"


def test_a_stage_exception_is_recorded_and_reraised(tmp_path, monkeypatch):
    from hornflow.workflow import orchestrator as o

    def boom(self):
        raise RuntimeError("solver exploded")

    monkeypatch.setattr(o.Pipeline, "stage_architecture", boom)
    with pytest.raises(RuntimeError, match="solver exploded"):
        run_pipeline(EXAMPLE, out_root=tmp_path)
    (run_dir,) = tmp_path.iterdir()
    st = load_state_file(run_dir / "state.json")
    assert st.run["status"] == "failed"
    rec = st.stages["ARCHITECTURE_SCREENING"]
    assert rec["status"] == "failed"
    assert rec["failure"]["category"] == "EXCEPTION"
    assert rec["failure"]["failed_checks"] == ["RuntimeError('solver exploded')"]


# ------------------------------------------------------------- reproducibility
def test_run_snapshots_its_inputs(pipeline_run):
    """The run keeps a byte-identical copy of what it was started from (S7)."""
    from hornflow.io.artifacts import sha256_file
    from hornflow.io.state_store import load_state_file

    st = load_state_file(pipeline_run / "state.json")
    inp = st.run["inputs"]
    definition = pipeline_run / inp["definition"]
    driver = pipeline_run / inp["driver"]
    assert definition.read_bytes() == EXAMPLE.read_bytes()
    assert driver.read_bytes() == (ROOT / "params" / "drivers"
                                  / "jbl_1200b.yaml").read_bytes()
    assert inp["definition_sha256"] == sha256_file(definition)
    assert inp["driver_sha256"] == sha256_file(driver)
    assert isinstance(inp["limits"], dict)
    assert isinstance(inp["code_version"], str) and inp["code_version"]
    # a run folder may be moved: nothing in the snapshot names an absolute path
    assert not any(str(v).startswith("/") for v in inp.values() if isinstance(v, str))


def test_the_bem_manifest_paths_are_relative_to_the_run(pipeline_run):
    """Generated files carry no absolute paths (audit S7)."""
    man = json.loads((pipeline_run / "deliverables" / "bem"
                      / "bem_manifest.json").read_text(encoding="utf-8"))

    def strings(obj):
        if isinstance(obj, str):
            yield obj
        elif isinstance(obj, dict):
            for value in obj.values():
                yield from strings(value)
        elif isinstance(obj, list):
            for value in obj:
                yield from strings(value)

    assert [s for s in strings(man) if s.startswith("/")] == []
    assert man["bem_dir"] == "deliverables/bem"
    assert man["files"]["mesh"]["path"] == "deliverables/bem/bem.msh"


def _definition_with_driver(tmp_path, reference: str) -> Path:
    """An example definition that names its driver exactly as ``reference``."""
    definition = tmp_path / "definition.yaml"
    definition.write_text(
        EXAMPLE.read_text(encoding="utf-8").replace(
            "driver: jbl_1200b.yaml", f"driver: {reference}"),
        encoding="utf-8")
    return definition


def test_a_driver_reference_keeps_its_folders_in_the_snapshot(tmp_path):
    """A ``drivers/x.yaml`` reference must resolve inside the snapshot (review #14)."""
    drivers = tmp_path / "drivers"
    drivers.mkdir()
    real = ROOT / "params" / "drivers" / "jbl_1200b.yaml"
    (drivers / real.name).write_bytes(real.read_bytes())
    definition = _definition_with_driver(tmp_path, "drivers/jbl_1200b.yaml")
    s = run_pipeline(definition, out_root=tmp_path / "runs", limits={"wall_mm": 18.0})
    st = load_state_file(Path(s["run_dir"]) / "state.json")
    inp = st.run["inputs"]
    assert inp["driver"] == "inputs/drivers/jbl_1200b.yaml"
    copied = Path(s["run_dir"]) / inp["driver"]
    assert copied.read_bytes() == real.read_bytes()
    # the run finished, so the sensitivity stage could read the snapshot too
    assert st.stage_status("CONSTRAINT_SENSITIVITY") == "passed"


def test_a_driver_reference_that_escapes_the_definition_folder_is_refused(tmp_path):
    from hornflow.workflow.orchestrator import Pipeline

    outside = tmp_path / "outside" / "jbl_1200b.yaml"
    outside.parent.mkdir()
    outside.write_bytes((ROOT / "params" / "drivers" / "jbl_1200b.yaml").read_bytes())
    params = tmp_path / "params"
    params.mkdir()
    definition = _definition_with_driver(params, "../outside/jbl_1200b.yaml")
    pipe = Pipeline(definition, out_root=tmp_path / "runs", limits={"wall_mm": 18.0})
    with pytest.raises(ValueError, match=r"\.\."):
        pipe._snapshot_inputs()                          # noqa: SLF001 - the subject


def test_a_driver_named_like_the_definition_snapshot_is_refused(tmp_path):
    from hornflow.workflow.orchestrator import Pipeline

    driver = tmp_path / "definition.yaml"
    driver.write_bytes((ROOT / "params" / "drivers" / "jbl_1200b.yaml").read_bytes())
    definition = _definition_with_driver(tmp_path, "definition.yaml")
    pipe = Pipeline(definition, out_root=tmp_path / "runs", limits={"wall_mm": 18.0})
    with pytest.raises(ValueError, match="definition.yaml"):
        pipe._snapshot_inputs()                          # noqa: SLF001 - the subject


def test_stage_one_loads_the_snapshot_it_wrote(tmp_path, monkeypatch):
    """The stages must read the bytes the run recorded, not the file it came from."""
    from hornflow.workflow import orchestrator as o

    seen = []
    real = o.config.load

    def spy(path, *args, **kwargs):
        seen.append(Path(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(o.config, "load", spy)
    s = run_pipeline(EXAMPLE, out_root=tmp_path, limits={"wall_mm": 18.0})
    assert seen, "the pipeline load its definition"
    assert seen[0] == Path(s["run_dir"]) / "inputs" / "definition.yaml"


# --------------------------------------------------------------- sensitivity
def test_the_sensitivity_levers_are_relative_and_really_move_the_run(pipeline_run):
    """Every lever must run, and each must change the thing it names (P3, P11)."""
    from hornflow.io.state_store import load_state_file

    st = load_state_file(pipeline_run / "state.json")
    runs = {r["limit"]: r for r in st.sensitivity_runs}
    # the driver lever used to error out because the driver lives in its own file
    rc = runs["rear_chamber"]
    assert "error" not in rc["stricter"]["metrics"]
    assert "error" not in rc["relaxed"]["metrics"]
    # the overrides are relative to this project, not fixed numbers
    assert rc["stricter"]["driver.rear_volume"] == pytest.approx(14000.0)
    assert rc["relaxed"]["driver.rear_volume"] == pytest.approx(56000.0)
    assert runs["passband_bottom"]["stricter"]["target.f_low"] == pytest.approx(69.0)
    # the -3 dB point is measured, not pinned at the lowest grid frequency
    assert all(r["base"]["cutoff_minus3db_hz"] != 20.0 for r in st.sensitivity_runs)
    # the mouth lever changes the geometry it claims to change
    mouth = runs["mouth_area"]
    assert mouth["relaxed"]["geometry_changed"]["mouth_area_cm2"] != 0.0
    assert mouth["relaxed"]["no_effect"] is False


# ------------------------------------------------------------------- scoring
def test_tie_is_reported_as_no_acoustic_winner(pipeline_run):
    """Two horns with identical 1-D metrics are a tie, not a winner (P1, D4)."""
    from hornflow.io.state_store import load_state_file

    st = load_state_file(pipeline_run / "state.json")
    finding = {f["check"]: f for f in st.critic_findings}["preference_not_decisive"]
    assert finding["passed"] is False
    assert finding["severity"] == "reject"
    report = (pipeline_run / "deliverables" / "report.md").read_text(encoding="utf-8")
    assert "No acoustic winner" in report
    assert "is also the best overall design" not in report


def test_a_point_five_gap_is_never_reordered_by_the_bonus():
    """The bonus may only break a tie: a 0.5-point lead stays with the data (D4).

    Probe from the review: a folded horn 1.0 point behind the raw leader won the
    reported order, and the report still called it the best overall design.
    """
    from hornflow.architecture import registry
    from hornflow.critique import critic
    from hornflow.reporting import markdown

    scores = registry.score([
        _Scored("folded_horn", 92.0, 0.0, True),
        _Scored("sealed_box", 92.7, 0.0, True),
    ])
    assert [s["architecture_id"] for s in scores] == ["sealed_box", "folded_horn"]
    assert scores[1]["preference_bonus"] == 0.0
    assert scores[1]["score"] == pytest.approx(92.0)
    assert registry.decisive_winner(scores) == "sealed_box"
    assert critic._preference_check(scores).passed is True
    report = markdown.render(_ctx(scores))
    assert "is also the best overall design" not in report
    assert "**not** the best overall design" in report


def test_the_preference_bonus_is_one_point_on_the_db_scale():
    """The bonus is a tie-breaker, not a 5-point head start (D4)."""
    from hornflow.architecture import registry

    scores = registry.score([
        _Scored("sealed_box", 91.4, 0.0, True),
        _Scored("folded_horn", 91.0, 0.0, True),
    ])
    assert registry.PREFERENCE_BONUS == {"folded_horn": 1.0}
    assert registry.TIE_TOLERANCE_POINTS == 0.5
    # inside the tolerance the bonus flips the reported order, and only by one point
    assert [s["architecture_id"] for s in scores] == ["folded_horn", "sealed_box"]
    assert scores[0]["raw_score"] == pytest.approx(91.0)
    assert scores[0]["score"] == pytest.approx(92.0)
    # the acoustic evidence cannot separate them, so the run reports a tie
    assert registry.decisive_winner(scores) is None


def test_no_feasible_candidate_is_said_plainly():
    """Zero feasible candidates is not a tie between two blank names (P1)."""
    from hornflow.architecture import registry
    from hornflow.critique import critic
    from hornflow.reporting import markdown

    scores = registry.score([
        _Scored("folded_horn", 92.0, 4.0, False),
        _Scored("sealed_box", 88.0, 5.0, False),
    ])
    finding = critic._preference_check(scores)
    assert finding.passed is False
    assert finding.severity == "reject"
    assert "no feasible candidate" in finding.detail.lower()
    assert "score within" not in finding.detail
    report = markdown.render(_ctx(scores))
    assert "no feasible candidate" in report.lower()
    assert "score within" not in report


class _Params:
    """The few report fields a scoring probe needs."""

    project = "scoring probe"
    source_path = "definition.yaml"


def _ctx(scores):
    """The report context for a scored list, in the shape the orchestrator passes."""
    return {"schema_version": "1.2", "run_id": "probe", "params": _Params(),
            "scores": scores, "best_overall": scores[0] if scores else None}


class _Scored:
    """A minimal ArchitectureResult stand-in for the scoring unit test."""

    def __init__(self, architecture_id, spl_mean_db, spl_variation_db, feasible):
        self.architecture_id = architecture_id
        self.display_name = architecture_id
        self.fidelity = "ONE_DIMENSIONAL"
        self.feasible = feasible
        self.implementation = "wired"
        self.metrics = {"spl_mean_db": spl_mean_db,
                        "spl_variation_db": spl_variation_db}


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
