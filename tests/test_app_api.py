"""Phase 3 tests: the M4 local host - actions, HTTP, and the safety guards.

The action surface is tested directly (no socket) and again over a real
``ThreadingHTTPServer`` on an ephemeral port, on a throwaway project directory so
nothing in the repository is touched.

Run standalone:  python3 tests/test_app_api.py
Under pytest:    python3 -m pytest tests/test_app_api.py -q
"""

from __future__ import annotations

import http.client
import json
import shutil
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow.app.actions import ACCEPT_REASONS, ApiError, safe_under  # noqa: E402
from hornflow.app.brief import BriefStore, slugify, validate_values      # noqa: E402
from hornflow.app.server import create_server                            # noqa: E402
from hornflow.app.view import VIEW_SCHEMA                                # noqa: E402

ANSWERS = {
    "deployment": "club sub corner", "boundary": "corner",
    "operating_orientation": "upright", "manufacturer": "JBL",
    "model": "JBL 1200B", "data_source": "measured", "ts_set": "datasheet",
    "Xmax": 11.35, "xmax_convention": "one-way", "thermal_power_w": 400,
    "min_safe_impedance_ohm": 3.0, "f_min_hz": 60, "f_max_hz": 200,
    "spl_continuous_db": 120, "measurement_distance_m": 1.0,
    "max_width_mm": 600, "max_height_mm": 1000, "max_depth_mm": 1500,
    "max_mass_kg": 100, "method": "plywood",
}


from conftest import _actions, copy_exports, load_state_file, update_state  # noqa: E402


def _store(project):
    proj, _ = project
    return BriefStore(proj, base_definition=proj / "params" / "horn_jbl_1200b.yaml")


# --------------------------------------------------------------------------- #
#  1. the path guard - an API request never names a filesystem path
# --------------------------------------------------------------------------- #
def test_safe_under_accepts_plain_relative_names(tmp_path):
    root = tmp_path / "root"
    (root / "a" / "b").mkdir(parents=True)
    assert safe_under(root, "a", "b") == (root / "a" / "b").resolve()
    assert safe_under(root) == root.resolve()


@pytest.mark.parametrize("bad", ["..", "../x", "../../etc/passwd", "a/../../b",
                                 "/etc/passwd", "~/.ssh/id_rsa", "a/~/b"])
def test_safe_under_refuses_traversal_and_absolute_paths(tmp_path, bad):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ApiError) as exc:
        safe_under(root, bad)
    assert exc.value.code == "path_rejected"
    assert exc.value.status == 400


def test_safe_under_cannot_escape_via_a_symlink(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.txt").write_text("x", encoding="utf-8")
    (root / "link").symlink_to(outside)
    with pytest.raises(ApiError):
        safe_under(root, "link", "secret.txt")


# --------------------------------------------------------------------------- #
#  2. the brief store
# --------------------------------------------------------------------------- #
def test_draft_round_trips_and_validates(project):
    s = _store(project)
    assert s.draft()["values"] == {}
    out = s.save_draft({"deployment": "a", "f_min_hz": 60})
    assert out["ok"] is True
    assert s.draft()["values"] == {"deployment": "a", "f_min_hz": 60}
    s.save_draft({"f_max_hz": 200})          # merges rather than replacing
    assert s.draft()["values"]["deployment"] == "a"
    assert s.draft()["values"]["f_max_hz"] == 200


def test_draft_rejects_a_bad_value_with_a_field_error(project):
    s = _store(project)
    out = s.save_draft({"f_min_hz": 99999})
    assert out["ok"] is False
    assert "f_min_hz" in out["field_errors"]
    assert s.draft()["values"] == {}          # nothing written


def test_validation_rules():
    assert validate_values({"boundary": "corner"}).ok
    assert not validate_values({"boundary": "space"}).ok
    assert not validate_values({"Xmax": "big"}).ok
    assert not validate_values({"Xmax": -1}).ok
    assert not validate_values({"nonsense_field": 1}).ok
    bad = validate_values({"f_min_hz": 200, "f_max_hz": 60})
    assert not bad.ok and "f_max_hz" in bad.errors
    warn = validate_values({"Xmax": 22.7, "xmax_convention": "peak-to-peak"})
    assert warn.ok and any("peak-to-peak" in w for w in warn.warnings)
    assert validate_values({"transport_orientation": None}).ok


def test_freeze_writes_a_definition_the_pipeline_can_load(project):
    from hornflow import config

    proj, _ = project
    out = _store(project).freeze(dict(ANSWERS), author="tester",
                                 now="2026-10-04T00:00:00+00:00")
    assert out["ok"] is True, out
    path = proj / out["definition"]
    assert path.is_file()
    params = config.load(path)                       # the real loader accepts it
    assert params.target.f_low == 60.0
    assert params.target.f_high == 200.0
    assert params.simulation.observation_distance == 1.0
    assert params.horn.length == pytest.approx(1.5)   # 1500 mm
    assert params.driver.Xmax == pytest.approx(0.01135)
    assert params.simulation.half_space is True       # boundary = corner
    assert "jbl_1200b" in out["applied"]["driver.file"]


def test_freeze_records_revision_hash_and_what_it_applied(project):
    import yaml

    proj, _ = project
    s = _store(project)
    first = s.freeze(dict(ANSWERS))
    second = s.freeze({**ANSWERS, "f_min_hz": 55})
    assert (first["revision"], second["revision"]) == (1, 2)
    assert first["input_hash"] != second["input_hash"]
    assert second["applied"]["target.f_low"] == 55.0
    assert s.draft()["revision"] == 2
    written = yaml.safe_load((proj / second["definition"]).read_text(encoding="utf-8"))
    assert written["brief"]["revision"] == 2
    assert written["brief"]["input_hash"] == second["input_hash"]
    assert written["brief"]["values"]["f_min_hz"] == 55
    assert written["brief"]["limits"]["min_safe_impedance_ohm"] == 3.0
    # the implied volume limit comes from W x H x D
    assert written["brief"]["limits"]["max_external_volume_m3"] == pytest.approx(0.9)
    # a later freeze never overwrites an earlier revision's definition (S7)
    assert first["definition"] != second["definition"]
    assert (proj / first["definition"]).is_file()


def test_the_input_hash_is_stable_for_the_same_values(project):
    a = _store(project).freeze(dict(ANSWERS))
    b = _store(project).freeze(dict(ANSWERS))
    assert a["input_hash"] == b["input_hash"]


def test_freeze_reports_the_unmodelled_thermal_limit(project):
    out = _store(project).freeze(dict(ANSWERS))
    assert any("thermal" in w for w in out["warnings"])


def test_freezing_an_unloadable_definition_is_refused_and_leaves_nothing(project):
    proj, _ = project
    (proj / "params" / "drivers" / "jbl_1200b.yaml").unlink()
    out = _store(project).freeze(dict(ANSWERS))
    assert out["ok"] is False
    assert "_definition" in out["field_errors"]
    gen = proj / ".hornflow" / "generated"
    assert not list(gen.glob("*.yaml"))
    assert not list(gen.glob(".*staging*"))


def test_driver_matching_is_forgiving_but_never_invents_one(project):
    s = _store(project)
    assert s.resolve_driver("JBL 1200B")
    assert s.resolve_driver("1200b")
    assert s.resolve_driver("jbl_1200b")
    assert s.resolve_driver("B&C 21DS115") is None
    assert s.resolve_driver("") is None


def test_slugify():
    assert slugify("Club sub, corner!") == "club_sub_corner"
    assert slugify("") == "brief"
    assert slugify("...") == "brief"


# --------------------------------------------------------------------------- #
#  3. the actions (no socket)
# --------------------------------------------------------------------------- #
def test_view_is_local_and_carries_the_live_blocks(project):
    a = _actions(project)
    v = a.view()
    assert v["host"] == "local"
    assert v["view_schema"]
    for key in ("live", "definitions", "runs", "brief_draft", "brief_actions",
                "completion", "workflow_stages", "unvalidated_accepted"):
        assert key in v, key
    assert v["live"]["state"] == "idle"
    assert v["brief_actions"]["freeze_brief"]["enabled"] is False
    assert "missing" in v["brief_actions"]["freeze_brief"]["reason"]
    # the snapshot message is gone: this host CAN write
    assert "static snapshot" not in v["brief_actions"]["save_draft"]["reason"]


def test_freeze_through_actions_needs_every_required_answer(project):
    a = _actions(project)
    out = a.freeze({"deployment": "x"})
    assert out["ok"] is False
    assert "_completion" in out["field_errors"]
    out = a.freeze(dict(ANSWERS))
    assert out["ok"] is True
    assert out["view"]["current_state"]["brief_revision"] == 1
    assert out["view"]["brief_actions"]["freeze_brief"]["enabled"] is True


def test_save_draft_then_the_view_offers_save_then_freeze(project):
    a = _actions(project)
    out = a.save_draft(dict(ANSWERS))
    assert out["ok"] is True
    assert out["view"]["brief_actions"]["freeze_brief"]["enabled"] is True
    # save-draft is offered only while the draft differs from the frozen revision
    assert out["view"]["brief_actions"]["save_draft"]["enabled"] is True
    frozen = a.freeze(dict(ANSWERS))
    assert frozen["ok"] is True
    assert frozen["view"]["brief_actions"]["save_draft"]["enabled"] is False


def test_run_requires_a_frozen_brief_and_an_allow_listed_definition(project):
    a = _actions(project, runner=lambda *args: {"run_id": "run_fake"})
    with pytest.raises(ApiError) as exc:
        a.start_run()
    assert exc.value.code == "no_frozen_brief"
    with pytest.raises(ApiError) as exc:
        a.start_run("../../../etc/passwd")
    assert exc.value.code == "unknown_definition"
    assert "not one of the available" in exc.value.message


def test_start_run_uses_the_frozen_definition_and_its_limits(project):
    seen = {}

    def runner(path, out_root, limits, progress):
        seen.update(path=Path(path), out_root=Path(out_root), limits=limits)
        progress("[ARCHITECTURE_SCREENING]")
        return {"run_id": "run_fake_1"}

    a = _actions(project, runner=runner)
    a.freeze(dict(ANSWERS))
    a.start_run(wait=True)
    assert seen["path"].name == "club_sub_corner-r1.yaml"
    assert seen["path"].is_file()
    assert seen["out_root"] == (_project_root(project) / "runs").resolve()
    # the limits come from the brief, not from a caller
    assert seen["limits"]["min_safe_impedance_ohm"] == 3.0
    assert seen["limits"]["max_external_volume_m3"] == pytest.approx(0.9)
    prog = a.progress()
    assert prog["state"] == "done"
    assert prog["run_id"] == "run_fake_1"
    assert prog["definition"].endswith("club_sub_corner-r1.yaml")


def _project_root(project):
    return project[0]


def test_one_run_lock_refuses_a_second_concurrent_run(project):
    release = threading.Event()

    def runner(path, out_root, limits, progress):
        progress("[INPUT_AUDIT]")
        release.wait(timeout=20)
        return {"run_id": "run_fake_2"}

    a = _actions(project, runner=runner)
    a.freeze(dict(ANSWERS))
    first = a.start_run()
    assert first["state"] == "running"
    with pytest.raises(ApiError) as exc:
        a.start_run()
    assert exc.value.code == "run_in_progress"
    assert exc.value.status == 409
    release.set()
    for _ in range(200):
        if a.progress()["state"] == "done":
            break
        threading.Event().wait(0.05)
    assert a.progress()["state"] == "done"
    # ... and after it finishes, a new run is allowed again
    a.start_run(wait=True)
    assert a.progress()["state"] == "done"


def test_a_failing_runner_is_reported_not_raised(project):
    def boom(path, out_root, limits, progress):
        raise RuntimeError("solver exploded")

    a = _actions(project, runner=boom)
    a.freeze(dict(ANSWERS))
    a.start_run(wait=True)
    prog = a.progress()
    assert prog["state"] == "failed"
    assert "solver exploded" in prog["error"]


def test_progress_reports_the_authoritative_stages(project):
    a = _actions(project)
    prog = a.progress()
    assert prog["stages_total"] == len(_stage_names(a))
    assert prog["stages_passed"] >= 1
    assert prog["percent"] == round(100.0 * prog["stages_passed"] / prog["stages_total"])
    assert all({"stage", "status", "detail"} <= set(s) for s in prog["stages"])


def _stage_names(a):
    st = a._state()                                   # noqa: SLF001 - the test's subject
    return list((st.stages or {}).keys())


def test_completed_run_progress_is_100_percent(project):
    """The optional BEM stage is skipped by design; done is done (audit S6)."""
    a = _actions(project)
    a.freeze(dict(ANSWERS))
    a.start_run(wait=True)
    prog = a.progress()
    assert prog["state"] == "done"
    assert prog["percent"] == 100
    assert prog["stages_passed"] == prog["stages_total"]


def test_progress_counts_the_run_in_flight_not_the_selected_one(project):
    """The id is only known when the runner returns; the state is not (audit S6)."""
    ready = threading.Event()
    release = threading.Event()

    def runner(path, out_root, limits, progress):
        from hornflow.domain.state import DesignState
        from hornflow.io.state_store import save_state

        # sorts after any real run id, which is a UTC timestamp
        run_dir = Path(out_root) / "run_29991231T235959Z_live"
        st = DesignState()
        st.run = {"run_id": run_dir.name, "status": "running"}
        st.set_stage("INPUT_AUDIT", "passed")
        save_state(st, run_dir / "state.json")
        progress("[INPUT_AUDIT]")
        ready.set()
        release.wait(timeout=20)
        return {"run_id": run_dir.name}

    a = _actions(project, runner=runner)
    a.freeze(dict(ANSWERS))
    a.start_run()
    try:
        assert ready.wait(timeout=20)
        prog = a.progress()
        assert prog["run_id"] is None          # not yet reported by the runner
        assert [s["stage"] for s in prog["stages"]] == ["INPUT_AUDIT"]
        assert prog["percent"] == 100
    finally:
        release.set()


def test_runs_show_how_each_run_ended(project):
    """An interrupted run is listed, and it says so (audit S6)."""
    proj, run_id = project
    state_path = proj / "runs" / run_id / "state.json"
    update_state(state_path, lambda st: st.set_run_status("interrupted"))
    a = _actions(project)
    (entry,) = [r for r in a.runs() if r["run_id"] == run_id]
    assert entry["status"] == "interrupted"


def test_a_decision_on_a_run_still_being_written_is_refused(project):
    """The pipeline saves the whole state after every stage: a write now is lost."""
    proj, run_id = project
    state_path = proj / "runs" / run_id / "state.json"
    update_state(state_path, lambda st: st.set_run_status("running"))
    before = len(load_state_file(state_path).decision_log)
    a = _actions(project)
    with pytest.raises(ApiError) as exc:
        a.decision(run_id=run_id, kind="accept_unvalidated", reason=ACCEPT_REASONS[0])
    assert exc.value.code == "run_in_progress"
    assert exc.value.status == 409
    # and nothing was written into the state the pipeline owns
    assert len(load_state_file(state_path).decision_log) == before


def test_a_failed_run_is_adopted_so_progress_does_not_show_the_last_one(project):
    def runner(path, out_root, limits, progress):
        from hornflow.domain.state import DesignState
        from hornflow.io.state_store import save_state

        run_dir = Path(out_root) / "run_29991231T235959Z_failed"
        st = DesignState()
        st.run = {"run_id": run_dir.name, "status": "failed"}
        st.set_stage("INPUT_AUDIT", "failed")
        save_state(st, run_dir / "state.json")
        raise RuntimeError("solver exploded")

    a = _actions(project, runner=runner)
    a.freeze(dict(ANSWERS))
    a.start_run(wait=True)
    prog = a.progress()
    assert prog["state"] == "failed"
    assert [s["stage"] for s in prog["stages"]] == ["INPUT_AUDIT"]
    assert prog["run_dir"].endswith("run_29991231T235959Z_failed")


# --------------------------------------------------------------------------- #
#  4. decisions - an audit record that never rewrites a measurement
# --------------------------------------------------------------------------- #
def test_decision_requires_a_fixed_reason_and_a_note_for_other(project):
    a = _actions(project)
    with pytest.raises(ApiError) as exc:
        a.decision(run_id=project[1], kind="accept_unvalidated", reason="invented reason")
    assert exc.value.code == "reason_required"
    assert exc.value.extra["allowed"] == list(ACCEPT_REASONS)
    with pytest.raises(ApiError) as exc:
        a.decision(run_id=project[1], kind="accept_unvalidated", reason="Other", note="  ")
    assert exc.value.code == "note_required"
    with pytest.raises(ApiError) as exc:
        a.decision(run_id=project[1], kind="delete_everything")
    assert exc.value.code == "unknown_decision"


def test_accepting_unvalidated_records_an_audit_entry_and_leaves_the_result_alone(
        project):
    a = _actions(project)
    before = a._state()                               # noqa: SLF001
    bem_before = dict(before.validation.get("bem_manual") or {})
    out = a.decision(run_id=project[1], kind="accept_unvalidated",
                     reason="AKABAK Free/export limitation",
                     note="prototype only", actor="alex",
                     now="2026-10-04T12:00:00+00:00")
    assert out["ok"] is True
    entry = out["decision"]
    assert entry["reason"] == "AKABAK Free/export limitation"
    assert entry["note"] == "prototype only"
    assert entry["actor"] == "alex"
    assert entry["utc"] == "2026-10-04T12:00:00+00:00"
    assert len(entry["result_hash"]) == 64
    assert entry["effect"] == "the acoustic result stays unvalidated"

    after = a._state()                                # noqa: SLF001
    bem_after = dict(after.validation.get("bem_manual") or {})
    # the measurement is untouched: same BEM state, same checks
    assert bem_after.get("state") == bem_before.get("state")
    assert bem_after.get("checks") == bem_before.get("checks")
    assert after.validation.get("bem_status") == before.validation.get("bem_status")
    # and the decision is recorded, with the persistent warning
    assert after.decision_log[-1]["event"] == "accept_unvalidated"
    assert after.validation["accepted_unvalidated"] is True
    assert out["view"]["unvalidated_accepted"] is True


def test_a_validated_candidate_cannot_be_accepted_as_unvalidated(project):
    """The guard that stops BEM_VALIDATED being overwritten by 'accept'."""
    import json as _json

    proj, run_id = project
    a = _actions(project)
    path = proj / "runs" / run_id / "state.json"
    raw = _json.loads(path.read_text(encoding="utf-8"))
    raw["validation"]["bem_manual"]["state"] = "BEM_VALIDATED"
    raw["validation"]["bem_status"] = "validated"
    path.write_text(_json.dumps(raw), encoding="utf-8")
    with pytest.raises(ApiError) as exc:
        a.decision(run_id=run_id, kind="accept_unvalidated", reason=ACCEPT_REASONS[0])
    assert exc.value.code == "already_validated"
    assert exc.value.status == 409
    # and nothing was recorded
    after = _json.loads(path.read_text(encoding="utf-8"))
    assert not after["validation"].get("accepted_unvalidated")
    assert not any(e.get("event") == "accept_unvalidated"
                   for e in after.get("decision_log") or [])


def test_import_without_an_export_folder_fails_with_an_actionable_message(project):
    a = _actions(project)
    shutil.rmtree(_project_root(project) / "runs" / project[1] / "deliverables"
                  / "bem" / "export", ignore_errors=True)
    with pytest.raises(ApiError) as exc:
        a.import_vips(run_id=project[1])
    assert exc.value.code == "no_export_folder"
    assert "export the .vips" in exc.value.message


def test_import_folder_cannot_be_traversed(project):
    a = _actions(project)
    with pytest.raises(ApiError) as exc:
        a.import_vips(run_id=a.run_dir.name, subdir="../../../../etc")
    assert exc.value.code == "path_rejected"


# --------------------------------------------------------------------------- #
#  4b. every mutating call names its run; an unreadable state is visible
#      (audit S1, S2)
# --------------------------------------------------------------------------- #
def test_decision_for_other_run_is_refused(project):
    """Two tabs, one project: the tab showing run X cannot decide for run Y."""
    a = _actions(project)
    other = "run_not_this_one"
    with pytest.raises(ApiError) as exc:
        a.decision(run_id=other, kind="accept_unvalidated", reason=ACCEPT_REASONS[0])
    assert exc.value.code == "run_mismatch" and exc.value.status == 409
    assert exc.value.extra == {"expected": a.run_dir.name, "got": other}
    assert not load_state_file(a.run_dir / "state.json").validation.get(
        "accepted_unvalidated")


def test_import_for_other_run_is_refused_before_reading_its_exports(project):
    a = _actions(project)
    before = (a.run_dir / "state.json").read_bytes()
    with pytest.raises(ApiError) as exc:
        a.import_vips(run_id="run_not_this_one")
    assert exc.value.code == "run_mismatch" and exc.value.status == 409
    assert (a.run_dir / "state.json").read_bytes() == before


@pytest.mark.parametrize("call", [
    lambda a: a.decision(run_id=None, kind="accept_unvalidated",
                         reason=ACCEPT_REASONS[0]),
    lambda a: a.import_vips(run_id=None),
])
def test_a_mutating_call_with_a_missing_run_id_is_refused(project, call):
    """None is not "the current run": an unnamed run is refused, never guessed."""
    a = _actions(project)
    with pytest.raises(ApiError) as exc:
        call(a)
    assert exc.value.code == "run_id_required" and exc.value.status == 400
    assert not load_state_file(a.run_dir / "state.json").validation.get(
        "accepted_unvalidated")


def test_accepted_with_tolerance_is_its_own_state(project):
    """Review of #12, decision D1: a relaxed acceptance never reads as validated."""
    a = _actions(project)
    copy_exports(a.run_dir)
    out = a.import_vips(run_id=a.run_dir.name, tolerance_db=12.0)
    assert out["state"] == "BEM_ACCEPTED_WITH_TOLERANCE"
    stored = load_state_file(a.run_dir / "state.json").validation
    assert stored["bem_status"] == "accepted_with_tolerance"
    v = a.view()
    assert v["current_state"]["bem_state"] == "BEM_ACCEPTED_WITH_TOLERANCE"
    assert v["outcome"]["bem"] == "BEM_ACCEPTED_WITH_TOLERANCE"
    assert v["mode"] == "review"


def test_corrupt_state_is_reported_not_treated_as_a_first_run(project):
    a = _actions(project)
    normal = set(a.view())
    (a.run_dir / "state.json").write_text("{ broken", encoding="utf-8")
    v = a.view()
    assert v["mode"] == "state_error"
    assert v["error"]["code"] == "state_unreadable"
    assert "state.json" in v["error"]["message"]
    # The page only draws the shell from a view that passes the app.js gate, and
    # the strip takes its text from view.mode / view.error (app.js renderStrip).
    # A hand-built dict without view_schema sent the browser to viewerOnly(),
    # which removed the tabs and never rendered the message (review of HORN-17).
    assert v["view_schema"] == VIEW_SCHEMA
    # Nothing the shell reads may be missing; "error" is the only addition.
    assert set(v) - normal == {"error"}
    assert normal - set(v) == set()          # and nothing the shell reads disappeared
    js = (ROOT / "hornflow" / "viz" / "viewer" / "ui" / "app.js").read_text(
        encoding="utf-8")
    assert "if (!view || !view.view_schema) { viewerOnly(); return; }" in js
    assert "view.mode === 'state_error'" in js


def test_a_missing_state_file_is_still_a_first_run(project):
    """The distinction that matters: absent means new, unreadable means broken."""
    proj, _ = project
    empty = proj / "runs" / "run_empty"
    empty.mkdir()
    a = _actions(project, run_dir=empty)
    assert a.view()["mode"] != "state_error"


def test_progress_survives_an_unreadable_state(project):
    a = _actions(project)
    (a.run_dir / "state.json").write_text("{ broken", encoding="utf-8")
    prog = a.progress()
    assert prog["stages"] == [] and prog["percent"] == 0


def test_the_decision_is_written_through_the_locked_writer(project, monkeypatch):
    from hornflow.app import actions as actions_mod

    calls = []
    real = actions_mod.update_state

    def spy(path, fn):
        calls.append(Path(path).name)
        return real(path, fn)

    monkeypatch.setattr(actions_mod, "update_state", spy)
    a = _actions(project)
    a.decision(run_id=a.run_dir.name, kind="accept_unvalidated",
               reason=ACCEPT_REASONS[0])
    assert calls == ["state.json"]


# --------------------------------------------------------------------------- #
#  5. over HTTP - a real ThreadingHTTPServer on an ephemeral port
# --------------------------------------------------------------------------- #
@pytest.fixture
def server(project):
    a = _actions(project, runner=lambda *args: {"run_id": "run_http_1"})
    httpd = create_server(a, port=0)
    host, port = httpd.server_address[:2]
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://{host}:{port}", a
    finally:
        httpd.shutdown()
        httpd.server_close()


def _get(base, path, raw=False):
    try:
        with urllib.request.urlopen(base + path, timeout=30) as r:
            data = r.read()
            return (r.status, data) if raw else (r.status, json.loads(data))
    except urllib.error.HTTPError as e:
        data = e.read()
        return e.code, (data if raw else json.loads(data))


def _post(base, path, obj, raw=False):
    req = urllib.request.Request(base + path, method="POST",
                                 data=json.dumps(obj).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            data = r.read()
            return (r.status, data) if raw else (r.status, json.loads(data))
    except urllib.error.HTTPError as e:
        data = e.read()
        return e.code, (data if raw else json.loads(data))


def test_get_endpoints(server):
    base, _ = server
    code, health = _get(base, "/api/health")
    assert code == 200 and health["ok"] is True
    code, view = _get(base, "/api/view")
    assert code == 200 and view["host"] == "local"
    code, prog = _get(base, "/api/progress")
    assert code == 200 and prog["state"] == "idle"
    code, defs = _get(base, "/api/definitions")
    assert code == 200 and any(d["name"] == "horn_jbl_1200b.yaml"
                               for d in defs["definitions"])
    code, runs = _get(base, "/api/runs")
    assert code == 200 and runs["runs"] and runs["current"]


def test_static_files_are_served_with_correct_types(server):
    base, _ = server
    code, html = _get(base, "/viewer/viewer.html", raw=True)
    assert code == 200 and b'id="app_view"' in html
    code, root = _get(base, "/", raw=True)
    assert code == 200 and b"<html" in root.lower()
    code, js = _get(base, "/viewer/ui/app.js", raw=True)
    assert code == 200 and b"acc-head" in js
    code, css = _get(base, "/viewer/ui/app.css", raw=True)
    assert code == 200 and b".acc" in css


def test_a_missing_static_file_is_a_json_404(server):
    base, _ = server
    code, body = _get(base, "/nope.html")
    assert code == 404 and body["error"]["code"] == "not_found"


@pytest.mark.parametrize("path", ["/../state.json", "/viewer/../../state.json",
                                  "/../../etc/passwd", "/%2e%2e/state.json"])
def test_static_traversal_is_refused(server, path):
    base, _ = server
    code, body = _get(base, path)
    assert code in (400, 404), path
    assert body["error"]["code"] in ("path_rejected", "not_found")


def test_traversal_through_the_api_is_refused(server):
    base, a = server
    code, body = _post(base, "/api/select", {"run_id": "../../../etc"})
    assert code == 400 and body["error"]["code"] == "path_rejected"
    code, body = _post(base, "/api/run", {"definition": "../../etc/passwd"})
    assert code == 400 and body["error"]["code"] == "unknown_definition"
    code, body = _post(base, "/api/import", {"run_id": a.run_dir.name,
                                            "subdir": "../../../../etc"})
    assert code == 400 and body["error"]["code"] == "path_rejected"


def test_a_mutating_post_names_its_run(server):
    """The HTTP contract behind audit S1: a stale tab cannot write to this run."""
    base, a = server
    payload = {"kind": "accept_unvalidated", "reason": ACCEPT_REASONS[0]}
    code, body = _post(base, "/api/decision", payload)
    assert code == 400 and body["error"]["code"] == "run_id_required"
    code, body = _post(base, "/api/decision", dict(payload, run_id="run_not_this_one"))
    assert code == 409 and body["error"]["code"] == "run_mismatch"
    assert body["error"]["expected"] == a.run_dir.name
    code, body = _post(base, "/api/decision", dict(payload, run_id=a.run_dir.name))
    assert code == 200 and body["ok"] is True
    code, body = _post(base, "/api/import", {"run_id": "run_not_this_one"})
    assert code == 409 and body["error"]["code"] == "run_mismatch"


def test_the_full_brief_run_decision_loop_over_http(server):
    base, a = server
    code, body = _post(base, "/api/brief", {"values": {"f_min_hz": 99999}})
    assert code == 200 and body["ok"] is False and "f_min_hz" in body["field_errors"]
    code, body = _post(base, "/api/brief", {"values": {"deployment": "http loop"}})
    assert code == 200 and body["ok"] is True
    code, body = _post(base, "/api/brief/freeze", {"values": ANSWERS})
    assert code == 200 and body["ok"] is True, body
    assert body["revision"] == 1 and body["definition"].endswith(".yaml")
    code, body = _post(base, "/api/run", {})
    assert code == 200 and body["state"] in ("running", "done")
    code, prog = _get(base, "/api/progress")
    assert code == 200 and prog["state"] == "done"
    assert prog["run_id"] == "run_http_1"
    code, body = _post(base, "/api/decision", {
        "run_id": a.run_dir.name,
        "kind": "accept_unvalidated",
        "reason": "Partial evidence accepted for prototype only", "actor": "http"})
    assert code == 200 and body["ok"] is True
    assert body["view"]["unvalidated_accepted"] is True
    code, view = _get(base, "/api/view")
    assert code == 200 and view["unvalidated_accepted"] is True
    assert view["live"]["state"] == "done"


def test_a_bad_body_is_rejected_without_a_traceback(server):
    base, _ = server
    for payload, needle in ((b"{not json", "bad_json"), (b"[1,2,3]", "JSON object")):
        req = urllib.request.Request(base + "/api/brief", method="POST",
                                     data=payload,
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=30)
            raise AssertionError("expected an error")
        except urllib.error.HTTPError as exc:
            code, body = exc.code, json.loads(exc.read())
        assert code == 400
        assert (body["error"]["code"] == needle
                or needle in body["error"]["message"])


def test_an_oversized_body_is_refused(server):
    base, _ = server
    big = json.dumps({"values": {"deployment": "x" * 300000}}).encode("utf-8")
    req = urllib.request.Request(base + "/api/brief", method="POST", data=big,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30)
        raise AssertionError("expected an error")
    except urllib.error.HTTPError as exc:
        code, body = exc.code, json.loads(exc.read())
    assert code == 413 and body["error"]["code"] == "body_too_large"


def test_an_unknown_endpoint_is_a_structured_404(server):
    base, _ = server
    code, body = _post(base, "/api/nope", {})
    assert code == 404 and body["error"]["code"] == "unknown_endpoint"


def test_an_internal_error_never_leaks_a_traceback(server, monkeypatch):
    base, actions = server

    def boom(*_a, **_k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(actions, "view", boom)
    code, body = _get(base, "/api/view")
    assert code == 500
    assert body["error"]["code"] == "internal"
    text = json.dumps(body)
    assert "secret internal detail" not in text
    assert "Traceback" not in text


# --------------------------------------------------------------------------- #
#  6. the request guard: foreign host, cross-site origin, non-JSON (audit S3)
#
#  A page on any origin can POST to 127.0.0.1 without a preflight when the body
#  is "simple" (text/plain), and DNS rebinding makes every GET readable.  So the
#  guard runs before any route: a refused request writes nothing and serves
#  nothing, and the answer is a structured error, never a 500.
# --------------------------------------------------------------------------- #
def _raw(base, method, path, *, body=None, headers=None):
    """One request with full control over the headers; urllib sets Host itself."""
    url = urllib.parse.urlparse(base)
    conn = http.client.HTTPConnection(url.hostname, url.port, timeout=60)
    try:
        conn.request(method, path, body=body, headers=headers or {})
        res = conn.getresponse()
        data = res.read()
        try:
            return res.status, json.loads(data)
        except ValueError:
            return res.status, data
    finally:
        conn.close()


def _port(base):
    return urllib.parse.urlparse(base).port


def test_a_foreign_host_header_is_refused_on_every_route(server):
    """The Host header is what DNS rebinding cannot forge; GET included."""
    base, actions = server
    before = actions.brief.draft()
    attempts = (
        ("GET", "/api/health", None),
        ("GET", "/api/view", None),
        ("GET", "/viewer/ui/app.js", None),
        ("POST", "/api/brief", b'{"values": {"deployment": "evil.example"}}'),
        ("POST", "/api/select", b'{"run_id": "whatever"}'),
    )
    for method, path, body in attempts:
        status, payload = _raw(base, method, path, body=body,
                               headers={"Host": "evil.example",
                                        "Content-Type": "application/json"})
        assert status == 403, (method, path, status)
        assert payload["error"]["code"] == "bad_host"
    assert actions.brief.draft() == before


def test_a_cross_origin_post_is_refused_and_writes_nothing(server):
    base, actions = server
    before = actions.brief.draft()
    status, payload = _raw(base, "POST", "/api/brief",
                           body=b'{"values": {"deployment": "evil.example"}}',
                           headers={"Origin": "http://evil.example",
                                    "Content-Type": "application/json"})
    assert status == 403 and payload["error"]["code"] == "bad_origin"
    assert actions.brief.draft() == before


@pytest.mark.parametrize("origin", ["http://evil.example",
                                    "http://127.0.0.1:1",
                                    "https://127.0.0.1",
                                    "http://127.0.0.1:not-a-port",
                                    "http://[::1",
                                    "http://127.0.0.1",
                                    "null"])
def test_a_malformed_or_foreign_origin_is_a_clean_refusal(server, origin):
    """A garbage Origin is a refusal, never a 500 and never a write.

    ``http://[::1`` cannot even be parsed, and ``http://127.0.0.1`` names the
    default port 80 (not the bound port), so neither may pass as this app.
    """
    base, actions = server
    if origin == "https://127.0.0.1":
        origin = "https://127.0.0.1:%d" % _port(base)
    before = actions.brief.draft()
    status, payload = _raw(base, "POST", "/api/brief",
                           body=b'{"values": {"deployment": "evil.example"}}',
                           headers={"Origin": origin,
                                    "Content-Type": "application/json"})
    assert status == 403 and payload["error"]["code"] == "bad_origin"
    assert actions.brief.draft() == before


@pytest.mark.parametrize("name", ["127.0.0.1", "localhost"])
def test_a_same_origin_post_is_allowed(server, name):
    """The viewer's own posts carry an Origin; both loopback spellings pass."""
    base, actions = server
    origin = "http://%s:%d" % (name, _port(base))
    status, payload = _raw(base, "POST", "/api/brief",
                           body=b'{"values": {"deployment": "corner"}}',
                           headers={"Origin": origin,
                                    "Content-Type": "application/json"})
    assert status == 200 and payload["ok"] is True
    assert actions.brief.draft()["values"]["deployment"] == "corner"


@pytest.mark.parametrize("ctype", ["text/plain",
                                   "application/x-www-form-urlencoded",
                                   "application/jsonp", None])
def test_a_non_json_content_type_is_refused(server, ctype):
    base, actions = server
    before = actions.brief.draft()
    headers = {} if ctype is None else {"Content-Type": ctype}
    status, payload = _raw(base, "POST", "/api/brief",
                           body=b'{"values": {"deployment": "evil.example"}}',
                           headers=headers)
    assert status == 415, (ctype, status)
    assert payload["error"]["code"] == "bad_content_type"
    assert actions.brief.draft() == before


@pytest.mark.parametrize("ctype", ["application/json",
                                   "application/json; charset=utf-8",
                                   "APPLICATION/JSON"])
def test_a_json_media_type_is_accepted_whatever_the_parameters(server, ctype):
    base, _ = server
    status, payload = _raw(base, "POST", "/api/brief",
                           body=b'{"values": {"deployment": "corner"}}',
                           headers={"Content-Type": ctype})
    assert status == 200 and payload["ok"] is True


def test_a_non_integer_content_length_is_refused(server):
    base, actions = server
    before = actions.brief.draft()
    status, payload = _raw(base, "POST", "/api/brief", body=b"{}",
                           headers={"Content-Type": "application/json",
                                    "Content-Length": "abc"})
    assert status == 400 and payload["error"]["code"] == "bad_length"
    assert actions.brief.draft() == before


def test_health_does_not_leak_paths(server):
    base, actions = server
    status, payload = _get(base, "/api/health")
    assert status == 200 and payload == {"ok": True}
    assert actions.root.name not in json.dumps(payload)
    assert str(actions.root) not in json.dumps(payload)


def test_a_non_loopback_bind_says_so_at_startup(project, monkeypatch, capsys):
    import hornflow.app.__main__ as app_main

    proj, _ = project
    seen = {}
    monkeypatch.setattr(app_main, "serve",
                        lambda actions, **kw: seen.update(kw) or 0)
    argv = ["--project", str(proj),
            "--base", str(proj / "params" / "horn_jbl_1200b.yaml"),
            "--host", "0.0.0.0"]
    assert app_main.main(argv) == 0
    assert seen["host"] == "0.0.0.0"
    assert "loopback" in capsys.readouterr().err


def test_a_loopback_bind_is_quiet(project, monkeypatch, capsys):
    import hornflow.app.__main__ as app_main

    proj, _ = project
    monkeypatch.setattr(app_main, "serve", lambda actions, **kw: 0)
    argv = ["--project", str(proj),
            "--base", str(proj / "params" / "horn_jbl_1200b.yaml")]
    assert app_main.main(argv) == 0
    assert capsys.readouterr().err == ""






