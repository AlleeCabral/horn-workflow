"""Phase 3 tests: the M4 local host - actions, HTTP, and the safety guards.

The action surface is tested directly (no socket) and again over a real
``ThreadingHTTPServer`` on an ephemeral port, on a throwaway project directory so
nothing in the repository is touched.

Run standalone:  python3 tests/test_app_api.py
Under pytest:    python3 -m pytest tests/test_app_api.py -q
"""

from __future__ import annotations

import json
import shutil
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow.app.actions import (ACCEPT_REASONS, ApiError, AppActions,  # noqa: E402
                                  safe_under)
from hornflow.app.brief import BriefStore, slugify, validate_values      # noqa: E402
from hornflow.app.server import create_server                            # noqa: E402

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


@pytest.fixture
def project(tmp_path):
    """A throwaway project: a copy of params/ plus a copy of one real run."""
    proj = tmp_path / "proj"
    shutil.copytree(ROOT / "params", proj / "params")
    src = max((ROOT / "runs").glob("run_*"))
    shutil.copytree(src, proj / "runs" / src.name)
    return proj, src.name


def _store(project):
    proj, _ = project
    return BriefStore(proj, base_definition=proj / "params" / "horn_jbl_1200b.yaml")


def _actions(project, *, runner=None, run_dir=None):
    proj, run_id = project
    return AppActions(proj, base_definition=proj / "params" / "horn_jbl_1200b.yaml",
                      run_dir=(run_dir if run_dir is not None
                               else proj / "runs" / run_id),
                      author="tester", runner=runner)


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
    assert seen["path"].name == "club_sub_corner.yaml"
    assert seen["path"].is_file()
    assert seen["out_root"] == (_project_root(project) / "runs").resolve()
    # the limits come from the brief, not from a caller
    assert seen["limits"]["min_safe_impedance_ohm"] == 3.0
    assert seen["limits"]["max_external_volume_m3"] == pytest.approx(0.9)
    prog = a.progress()
    assert prog["state"] == "done"
    assert prog["run_id"] == "run_fake_1"
    assert prog["definition"].endswith("club_sub_corner.yaml")


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


# --------------------------------------------------------------------------- #
#  4. decisions - an audit record that never rewrites a measurement
# --------------------------------------------------------------------------- #
def test_decision_requires_a_fixed_reason_and_a_note_for_other(project):
    a = _actions(project)
    with pytest.raises(ApiError) as exc:
        a.decision(kind="accept_unvalidated", reason="invented reason")
    assert exc.value.code == "reason_required"
    assert exc.value.extra["allowed"] == list(ACCEPT_REASONS)
    with pytest.raises(ApiError) as exc:
        a.decision(kind="accept_unvalidated", reason="Other", note="  ")
    assert exc.value.code == "note_required"
    with pytest.raises(ApiError) as exc:
        a.decision(kind="delete_everything")
    assert exc.value.code == "unknown_decision"


def test_accepting_unvalidated_records_an_audit_entry_and_leaves_the_result_alone(
        project):
    a = _actions(project)
    before = a._state()                               # noqa: SLF001
    bem_before = dict(before.validation.get("bem_manual") or {})
    out = a.decision(kind="accept_unvalidated",
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
        a.decision(kind="accept_unvalidated", reason=ACCEPT_REASONS[0])
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
        a.import_vips()
    assert exc.value.code == "no_export_folder"
    assert "export the .vips" in exc.value.message


def test_import_folder_cannot_be_traversed(project):
    a = _actions(project)
    with pytest.raises(ApiError) as exc:
        a.import_vips(subdir="../../../../etc")
    assert exc.value.code == "path_rejected"


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
    base, _ = server
    code, body = _post(base, "/api/select", {"run_id": "../../../etc"})
    assert code == 400 and body["error"]["code"] == "path_rejected"
    code, body = _post(base, "/api/run", {"definition": "../../etc/passwd"})
    assert code == 400 and body["error"]["code"] == "unknown_definition"
    code, body = _post(base, "/api/import", {"subdir": "../../../../etc"})
    assert code == 400 and body["error"]["code"] == "path_rejected"


def test_the_full_brief_run_decision_loop_over_http(server):
    base, _ = server
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
                                     data=payload, headers={})
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





