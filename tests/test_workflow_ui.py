"""Phase 2 tests: the nine-stage workflow model and the accordion Workflow tab.

Two layers are checked here:

1. the *model* (`hornflow/app/view.py`) owns the stages, their status, their lock
   reasons and every count - the browser must never derive any of it;
2. the *renderer* (`ui/app.js` / `ui/app.css`) is a static contract, plus a real
   browser smoke test using `chrome --dump-dom` when a browser is available (no
   browser-automation library is added: this reuses the tool the screenshots use).

Run standalone:  python3 tests/test_workflow_ui.py
Under pytest:    python3 -m pytest tests/test_workflow_ui.py -q
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow.app import view as V                                          # noqa: E402
from hornflow.workflow.stages import STAGE_ORDER                            # noqa: E402

EXAMPLE = ROOT / "params" / "horn_jbl_1200b.yaml"
FIXTURE = ROOT / "tests" / "fixtures" / "app_view" / "jbl_state_trimmed.json"
FIXED_NOW = "2026-10-03T00:00:00+00:00"
JS = ROOT / "hornflow" / "viz" / "viewer" / "ui" / "app.js"
CSS = ROOT / "hornflow" / "viz" / "viewer" / "ui" / "app.css"


def _state():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _run_view(**kw):
    kw.setdefault("now", FIXED_NOW)
    return V.build_view(_state(), **kw)


def _first_run(brief=None):
    return V.first_run_view(now=FIXED_NOW, brief=brief)


# ---------------------------------------------------------------------------
#  the model: nine stages, in order, with locks derived not invented
# ---------------------------------------------------------------------------
def test_there_are_nine_stages_in_the_documented_order():
    names = [s["name"] for s in V.WORKFLOW_STAGES]
    assert names == [
        "Project and deployment", "Driver and provenance",
        "Safety and electrical limits", "Acoustic target",
        "Envelope and manufacturing", "Architecture selection",
        "Acoustic and folded design", "Verification and AKABAK",
        "Final decision"]
    for label in (_first_run(), _run_view()):
        rows = label["workflow_stages"]
        assert len(rows) == 9
        assert [r["order"] for r in rows] == list(range(9))


def test_every_pipeline_gate_belongs_to_exactly_one_stage():
    """Coverage: no gate may be dropped, none may be owned twice."""
    owned = [g for s in V.WORKFLOW_STAGES for g in s["gates"]]
    assert len(owned) == len(set(owned))
    assert set(owned) == {s.value for s in STAGE_ORDER}


def test_every_question_group_belongs_to_exactly_one_stage():
    owned = [g for s in V.WORKFLOW_STAGES for g in s["groups"]]
    assert len(owned) == len(set(owned))
    assert set(owned) == {q["id"] for q in V.FIRST_RUN_QUESTIONS}


def test_exactly_one_stage_is_open_by_default_and_it_is_the_first_unfinished():
    for label in (_first_run(), _run_view()):
        rows = label["workflow_stages"]
        opened = [r for r in rows if r["open_by_default"]]
        assert len(opened) == 1
        first_unfinished = next(r for r in rows
                                if not r["complete"] and not r["locked"])
        assert opened[0]["id"] == first_unfinished["id"]
        # and the summary names the same stage
        assert label["current_state"]["current_stage"]["id"] == opened[0]["id"]


def test_locked_stages_are_never_open_by_default():
    for label in (_first_run(), _run_view()):
        for r in label["workflow_stages"]:
            if r["locked"]:
                assert r["open_by_default"] is False, r["id"]
                assert r["locked_reason"], r["id"]
                assert r["locked_by"], r["id"]


def test_a_stage_is_never_both_locked_and_complete():
    for label in (_first_run(), _run_view()):
        for r in label["workflow_stages"]:
            assert not (r["locked"] and r["complete"]), r["id"]


def test_locks_cascade_from_the_earlier_stage():
    rows = {r["id"]: r for r in _first_run()["workflow_stages"]}
    assert rows["safety_limits"]["locked_by"] == ["driver_provenance"]
    assert rows["architecture_selection"]["locked_by"] == [
        "acoustic_target", "envelope_manufacturing"]
    assert rows["acoustic_design"]["locked_by"] == ["architecture_selection"]
    assert rows["final_decision"]["locked_by"] == ["verification_bem"]
    assert "driver_provenance" in rows["safety_limits"]["locked_reason"]


def test_a_first_run_has_no_completed_stage():
    label = _first_run()
    assert label["current_state"]["stages_complete"] == 0
    assert label["workflow_stages"][0]["status"] == "needs_input"
    assert not any(r["complete"] for r in label["workflow_stages"])


def test_evidence_beats_the_lock_on_a_real_run():
    """The four engineering stages have run, so they are complete, not locked."""
    label = _run_view()
    rows = {r["id"]: r for r in label["workflow_stages"]}
    for sid in ("architecture_selection", "acoustic_design", "verification_bem",
                "final_decision"):
        assert rows[sid]["complete"] is True, sid
        assert rows[sid]["locked"] is False, sid
        assert rows[sid]["status"] == "complete", sid
        assert rows[sid]["required_total"] == 0
    # ... while the question stages still need input
    for sid in ("project_deployment", "driver_provenance", "safety_limits",
                "acoustic_target", "envelope_manufacturing"):
        assert rows[sid]["status"] == "needs_input", sid
    assert label["current_state"]["stages_complete"] == 4


def test_stage_answer_counts_match_the_groups_they_own():
    label = _run_view()
    groups = {q["id"]: q for q in label["questions"]}
    for r in label["workflow_stages"]:
        owned = [groups[g] for g in r["group_ids"]]
        assert r["required_total"] == sum(g["required_total"] for g in owned), r["id"]
        assert r["required_answered"] == sum(
            g["required_answered"] for g in owned), r["id"]
        assert r["blocker_count"] == sum(len(g["blocked_by"]) for g in owned), r["id"]
    total_blockers = sum(r["blocker_count"] for r in label["workflow_stages"])
    assert total_blockers == label["completion"]["blocker_count"]


def test_each_stage_reports_only_the_gates_it_owns():
    label = _run_view()
    gate_status = {g["stage"]: g["status"] for g in label["gates"]}
    seen = []
    for r in label["workflow_stages"]:
        for g in r["gates"]:
            assert g["status"] == gate_status[g["stage"]]
            seen.append(g["stage"])
        # a stage that collects no answers is pure pipeline work and must own
        # gates; the three question-only stages own none
        if not r["group_ids"]:
            assert r["gates"], r["id"]
    assert sorted(seen) == sorted(gate_status)


def test_brief_actions_are_disabled_with_a_reason_that_names_the_blocker():
    label = _first_run()
    act = label["brief_actions"]
    assert act["save_draft"]["enabled"] is False
    assert "M4" in act["save_draft"]["reason"]
    assert act["freeze_brief"]["enabled"] is False
    assert "20" in act["freeze_brief"]["reason"]        # the blocker count
    assert "missing" in act["freeze_brief"]["reason"]

    done = _first_run(brief={
        "deployment": "test", "boundary": "corner", "operating_orientation": "upright",
        "manufacturer": "JBL", "model": "1200B", "data_source": "measured",
        "ts_set": "datasheet", "Xmax": 11.35, "xmax_convention": "one-way",
        "thermal_power_w": 400, "min_safe_impedance_ohm": 3.0,
        "constraints": {"acoustic": {"f_low_hz": 60, "f_high_hz": 200}},
        "spl_continuous_db": 120, "measurement_distance_m": 1.0,
        "max_width_mm": 600, "max_height_mm": 900, "max_depth_mm": 1500,
        "max_mass_kg": 60, "method": "plywood"})
    assert done["completion"]["complete"] is True
    assert done["brief_actions"]["freeze_brief"]["enabled"] is True
    assert "input hash" in done["brief_actions"]["freeze_brief"]["reason"]


def test_a_fully_answered_brief_completes_every_question_stage():
    done = _first_run(brief={
        "deployment": "test", "boundary": "corner", "operating_orientation": "upright",
        "manufacturer": "JBL", "model": "1200B", "data_source": "measured",
        "ts_set": "datasheet", "Xmax": 11.35, "xmax_convention": "one-way",
        "thermal_power_w": 400, "min_safe_impedance_ohm": 3.0,
        "constraints": {"acoustic": {"f_low_hz": 60, "f_high_hz": 200}},
        "spl_continuous_db": 120, "measurement_distance_m": 1.0,
        "max_width_mm": 600, "max_height_mm": 900, "max_depth_mm": 1500,
        "max_mass_kg": 60, "method": "plywood"})
    rows = {r["id"]: r for r in done["workflow_stages"]}
    for sid in ("project_deployment", "driver_provenance", "acoustic_target",
                "envelope_manufacturing"):
        assert rows[sid]["status"] == "complete", (sid, rows[sid])
    # safety_limits unlocks once its prerequisite is complete
    assert rows["safety_limits"]["locked"] is False
    assert rows["safety_limits"]["complete"] is True
    # the engineering stages now unlock but still need the run
    assert rows["architecture_selection"]["locked"] is False
    assert rows["architecture_selection"]["status"] == "in_progress"


# ---------------------------------------------------------------------------
#  the renderer: static contract (no browser needed)
# ---------------------------------------------------------------------------
def test_renderer_never_computes_completion_or_stage_status():
    """All arithmetic lives in the model; the renderer only reads."""
    js = JS.read_text(encoding="utf-8")
    for forbidden in ("fields_answered >=", "required_answered ===",
                      "required_total -", "blockers.length === 0",
                      "filter(function (q) { return q.blocking; })"):
        assert forbidden not in js, forbidden
    for required in ("view.completion", "view.workflow_stages", "view.brief_actions",
                     "stage.required_answered", "stage.blocker_count",
                     "stage.locked_reason", "stage.open_by_default"):
        assert required in js, required


def test_accordion_headers_are_real_buttons_with_aria():
    js = JS.read_text(encoding="utf-8")
    assert "'button', { type: 'button', class: 'acc-head'" in js.replace('"', "'")
    assert "'aria-expanded'" in js.replace('"', "'")
    assert "'aria-controls'" in js.replace('"', "'")
    assert "role: 'region'" in js
    assert "'aria-labelledby'" in js.replace('"', "'")
    assert "class: 'acc-icon', 'aria-hidden': 'true'" in js.replace('"', "'")


def test_accordion_is_keyboard_operable():
    js = JS.read_text(encoding="utf-8")
    assert "ArrowDown" in js and "ArrowUp" in js
    assert "ev.key === 'Home'" in js and "ev.key === 'End'" in js
    assert "heads[j].focus()" in js


def test_sections_are_built_once_then_toggled_so_content_survives():
    """Toggling must not re-render, or form contents would be lost."""
    js = JS.read_text(encoding="utf-8")
    assert "body.hidden = !next" in js
    assert "openState[stage.id] = next" in js
    # the accordion body is built once, at construction time, not on click
    click_block = js.split("btn.addEventListener('click'")[1].split("});")[0]
    assert "stageBodyContent" not in click_block


def test_visible_field_text_is_the_human_label_and_the_key_is_only_a_tooltip():
    js = JS.read_text(encoding="utf-8")
    assert "text: f.label" in js
    assert "title: f.key" in js
    # the key must never be rendered as visible text
    assert "text: f.key" not in js


def test_layout_is_bounded_to_two_columns_and_cannot_overflow():
    css = CSS.read_text(encoding="utf-8")
    assert "#pane-workflow { padding: 14px 16px 40px; overflow-x: hidden; }" in css
    assert "box-sizing: border-box" in css
    # one column by default, two only above 900 px
    assert ".fields { display: grid; grid-template-columns: minmax(0, 1fr);" in css
    assert ("@media (min-width: 900px) {\n  .fields "
            "{ grid-template-columns: repeat(2, minmax(0, 1fr)); }\n}") in css
    # the copy command wraps instead of scrolling
    assert "white-space: pre-wrap" in css


def test_no_fixed_width_or_nowrap_rule_can_clip_a_label():
    css = CSS.read_text(encoding="utf-8")
    # min-width:0 on the flex children is what lets long labels wrap
    assert ".acc-head .acc-name { font-weight: 600; min-width: 0;" in css
    assert "#strip > span { overflow-wrap: anywhere; min-width: 0; }" in css
    assert "white-space: nowrap" not in css.split(".acc-head {")[1].split("}")[0]


# ---------------------------------------------------------------------------
#  the renderer: real browser smoke test (chrome --dump-dom; no new dependency)
# ---------------------------------------------------------------------------
def _chrome():
    return shutil.which("google-chrome") or shutil.which("chromium")


def _render(tmp_path, view):
    """A complete, self-contained viewer.html in a temp directory."""
    from hornflow import config, fold
    from hornflow.architecture.front_loaded import build_master
    from hornflow.viz import export as viz_export

    p = config.load(EXAMPLE)
    _, master = build_master(p, "folded_horn")
    cand = fold.StraightFold().generate(master, {"wall_mm": 18.0})[0]
    out = viz_export.write_viewer(cand, Path(tmp_path) / "viewer", app_view=view,
                                  title="workflow ui test")
    return Path(out["viewer"])


def _dom(html_path, tab="workflow"):
    from urllib.parse import quote

    url = "file://" + quote(str(html_path)) + "?tab=" + tab
    res = subprocess.run(
        [_chrome(), "--headless=new", "--disable-gpu", "--no-sandbox",
         "--virtual-time-budget=4000", "--dump-dom", url],
        capture_output=True, text=True, timeout=240)
    return res.stdout


def _skip_without_browser():
    if not _chrome():
        import pytest

        pytest.skip("no headless browser available")


def test_rendered_dom_has_nine_accordions_with_exactly_one_open(tmp_path):
    _skip_without_browser()
    view = _run_view()
    dom = _dom(_render(tmp_path, view))
    assert dom.count('class="acc-head"') == 9
    assert dom.count('aria-expanded="true"') == 1
    assert dom.count('aria-expanded="false"') == 8
    assert dom.count('role="region"') == 9
    # every header controls a body that exists
    for sid in [r["id"] for r in view["workflow_stages"]]:
        assert 'id="acc-b-%s"' % sid in dom
        assert 'id="acc-h-%s"' % sid in dom
    assert dom.count("Read-only snapshot") == 1


def _rendered_pane(dom, pane="pane-workflow"):
    """The rendered pane only - without the embedded data script, which of course
    contains the internal keys (that is data, not visible text)."""
    body = dom.split('<script id="app_view"')[0] + \
        dom.split("</script>", 1)[-1] if '<script id="app_view"' in dom else dom
    m = re.search(r'<section id="%s".*?</section>' % pane, body, re.S)
    return m.group(0) if m else body


def test_rendered_dom_opens_the_stage_the_model_named(tmp_path):
    _skip_without_browser()
    view = _run_view()
    dom = _dom(_render(tmp_path, view))
    current = view["current_state"]["current_stage"]["id"]
    bodies = dict(re.findall(r'<div class="acc-body" id="acc-b-([a-z_]+)"([^>]*)>', dom))
    assert len(bodies) == 9
    open_bodies = [k for k, attrs in bodies.items() if "hidden" not in attrs]
    assert open_bodies == [current], (open_bodies, current)
    # and every other body carries the hidden attribute
    assert dom.count("hidden") >= 8


def test_rendered_dom_shows_human_labels_and_never_the_internal_key_as_text(tmp_path):
    _skip_without_browser()
    view = _first_run()
    dom = _dom(_render(tmp_path, view))
    for label in ("What is it for?", "Where will it stand?",
                  "Excursion limit (Xmax)", "Amplifier minimum safe impedance",
                  "Lowest required frequency", "Manufacturing method"):
        assert label in dom, label
    # In the *rendered markup* the internal key survives only inside a title
    # attribute, never as visible text.
    pane = _rendered_pane(dom)
    assert pane
    for key in ("deployment", "min_safe_impedance_ohm", "spl_continuous_db",
                "max_external_volume_m3", "f_min_hz"):
        assert ">%s<" % key not in pane, key
    assert "text: f.key" not in JS.read_text(encoding="utf-8")


def test_rendered_dom_shows_required_or_optional_not_unknown_chips(tmp_path):
    _skip_without_browser()
    dom = _dom(_render(tmp_path, _first_run()))
    assert ">Required<" in dom and ">Optional<" in dom
    # the noisy chips the redesign removed
    assert ">UNKNOWN<" not in dom
    assert ">unanswered<" not in dom
    assert "wave A complete" not in dom
    # provenance sits under the value
    assert "required \u00b7" in dom or "optional \u00b7" in dom


def test_rendered_dom_disables_freeze_brief_and_says_why(tmp_path):
    _skip_without_browser()
    dom = _dom(_render(tmp_path, _first_run()))
    assert "Freeze brief" in dom and "Save draft" in dom
    assert "20 required answers still missing." in dom
    assert "Disabled \u2014" in dom
    assert "disabled" in dom


def test_rendered_dom_marks_locked_stages_with_a_reason(tmp_path):
    _skip_without_browser()
    view = _first_run()
    dom = _dom(_render(tmp_path, view))
    locked = [r for r in view["workflow_stages"] if r["locked"]]
    assert len(locked) == 5      # safety_limits plus the four engineering stages
    for r in locked:
        assert r["locked_reason"] in dom, r["id"]
        assert r["open_by_default"] is False
    assert ">locked<" in dom

