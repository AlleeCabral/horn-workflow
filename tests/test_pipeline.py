"""Integration tests: the full gated pipeline and its artifacts.

Run:  python3 -m pytest tests/test_pipeline.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow.workflow import run_pipeline, Stage                          # noqa: E402
from hornflow.workflow.stages import STAGE_ORDER, ready                    # noqa: E402

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
    assert st.schema_version == "1.0"
    assert st.stage_status("REPORT_AND_EXPORT") == "passed"
    assert len(st.fold_candidates) >= 3
    assert st.simulation_runs


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


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
