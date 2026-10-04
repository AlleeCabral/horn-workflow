"""M1-M3 tests: the app view model, the tab shell, and the static Workflow tab.

Run standalone:  python3 tests/test_app_view.py
Under pytest:    python3 -m pytest tests/test_app_view.py -q
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow.app import view as V                                          # noqa: E402
from hornflow.viz import export as viz_export                               # noqa: E402
from hornflow.workflow import run_pipeline                                  # noqa: E402

EXAMPLE = ROOT / "params" / "horn_jbl_1200b.yaml"
FIXTURE = ROOT / "tests" / "fixtures" / "app_view" / "jbl_state_trimmed.json"
FIXED_NOW = "2026-10-03T00:00:00+00:00"


def _state(**over):
    """The trimmed real run state, optionally patched."""
    s = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for dotted, value in over.items():
        keys = dotted.split(".")
        cur = s
        for k in keys[:-1]:
            cur = cur.setdefault(k, {})
        cur[keys[-1]] = value
    return s


def _built(state=None, **kw):
    kw.setdefault("now", FIXED_NOW)
    return V.build_view(state if state is not None else _state(), **kw)


# ---------------------------------------------------------------------------
#  M1 - determinism (the golden contract)
# ---------------------------------------------------------------------------
def test_view_is_byte_identical_for_the_same_state():
    a = V.to_json(_built())
    b = V.to_json(_built())
    assert a == b
    assert a.endswith("\n")


def test_view_json_keys_are_sorted_and_reparse():
    text = V.to_json(_built())
    assert json.loads(text) == _built()
    keys = re.findall(r'^  "([a-z_]+)":', text, re.M)
    assert keys == sorted(keys), keys


def test_generated_utc_does_not_leak_into_the_rest():
    a = _built(now="2026-01-01T00:00:00+00:00")
    b = _built(now="2030-12-31T23:59:59+00:00")
    assert a["generated_utc"] != b["generated_utc"]
    del a["generated_utc"], b["generated_utc"]
    assert a == b


def test_emit_view_round_trips(tmp_path):
    view = _built()
    path = V.emit_view(view, tmp_path / "app_view.json")
    assert path.is_file()
    assert V.to_json(json.loads(path.read_text(encoding="utf-8"))) == V.to_json(view)

# ---------------------------------------------------------------------------
#  M1 - first_run fixture and sections
# ---------------------------------------------------------------------------
def test_first_run_fixture_has_no_run_and_five_blocking_questions():
    view = V.first_run_view(project="demo", now=FIXED_NOW)
    assert view["mode"] == "first_run"
    assert view["run"] is None
    assert len(view["questions"]) == 5
    assert all(q["required"] for q in view["questions"])
    assert all(q["blocking"] for q in view["questions"])
    assert all(f["value"] is None and f["status"] == "UNKNOWN"
               for q in view["questions"] for f in q["fields"])
    assert view["next_action"]["label"] == "Answer the required questions"
    assert len(view["next_action"]["blockers"]) == 5
    assert view["manual_bem"]["available"] is False
    assert view["gates"] and all(g["status"] == "pending" for g in view["gates"])


def test_first_run_is_deterministic():
    assert V.to_json(V.first_run_view(now=FIXED_NOW)) == \
           V.to_json(V.first_run_view(now=FIXED_NOW))


def test_questions_resolve_from_the_run_state():
    view = _built()
    by_id = {q["id"]: q for q in view["questions"]}
    fields = {f["name"]: f for f in by_id["Q-TGT-01/02"]["fields"]}
    assert fields["f_min_hz"]["value"] == 60.0
    assert fields["f_max_hz"]["value"] == 200.0
    assert fields["f_min_hz"]["status"] == "FIXED"
    assert fields["spl_continuous_db"]["value"] is None      # not in the audit yet
    assert not any(q["blocking"] for q in view["questions"])  # a run exists


def test_gates_cover_all_sixteen_stages_and_flag_the_optional_one():
    view = _built()
    assert len(view["gates"]) == 16
    assert [g["stage"] for g in view["gates"] if g["optional"]] == \
        ["THREE_DIMENSIONAL_VERIFICATION"]
    assert view["gates"][0]["stage"] == "INPUT_AUDIT"
    assert view["gates"][-1]["stage"] == "REPORT_AND_EXPORT"


def _state_with_bem(state_name, **extra):
    """The fixture with the manual-solve state forced (the fixture is BEM_VALIDATED)."""
    s = _state()
    s["validation"]["bem_manual"]["state"] = state_name
    s["validation"]["bem_manual"].update(extra)
    return s


def test_mode_and_manual_bem_are_derived_from_the_state():
    view = _built()
    assert view["mode"] == "review"                 # fixture ends BEM_VALIDATED
    mb = view["manual_bem"]
    assert mb["available"] is True and mb["state"] == "BEM_VALIDATED"
    assert mb["chain"][0] == "INPUTS_GENERATED" and mb["chain"][-1] == "BEM_VALIDATED"
    assert len(mb["checklist"]) == 9
    assert "GUI" in (mb["reason"] or "")
    # the open (manual) phase is a different mode on the same shape
    assert V.build_view(_state_with_bem("GUI_REQUIRED"), now=FIXED_NOW)["mode"] == \
        "manual_bem"
    # a failed stage wins over everything
    s = _state_with_bem("GUI_REQUIRED")
    s["stages"]["PHYSICAL_FEASIBILITY"] = {"status": "failed", "detail": "FEASIBILITY"}
    assert V.build_view(s, now=FIXED_NOW)["mode"] == "blocked"


def test_import_panel_carries_the_cli_command():
    ip = _built()["import_panel"]
    assert ip["available"] is False                # the static host cannot mutate
    assert ip["export_dir"].endswith("bem/export")
    assert ip["command"].startswith("python3 -m hornflow.cli ")
    assert "--bem-import" in ip["command"]
    assert ip["last_source"] and ip["last_utc"]    # the fixture records a real import
    # ready only while the manual phase is open
    assert V.build_view(_state_with_bem("MANUAL_SOLVE_COMPLETED"),
                        now=FIXED_NOW)["import_panel"]["ready"] is True
    assert ip["ready"] is False


def test_outcome_reads_checks_and_metrics_from_validation():
    state = _state()
    state["validation"]["bem_manual"] = {
        "state": "BEM_REJECTED", "validation_passed": True, "tolerance_db": 6.0,
        "source": "Akabak-Rad1_23Sept26-Mic1.vips",
        "imported_utc": "2026-10-03T18:00:00+00:00",
        "checks": [{"name": "expected_file_exists", "passed": True, "severity": "hard",
                    "detail": "10 file(s)"}],
        "metrics": {"curve": "Mic1", "n_points": 24, "band_hz": [60.0, 200.0],
                    "mean_diff_db": -8.68, "worst_diff_db": 11.64, "tolerance_db": 6.0},
        "warnings": [],
    }
    view = V.build_view(state, now=FIXED_NOW)
    oc = view["outcome"]
    assert oc["bem"] == "BEM_REJECTED"
    assert oc["exit"] == "re_export_or_relax_tolerance"
    assert oc["evidence"] == "BEM_SIMULATION"
    assert oc["metrics"]["worst_diff_db"] == 11.64
    assert len(oc["checks"]) == 1
    assert view["current_state"]["bem_state"] == "BEM_REJECTED"


def test_next_action_rules_first_match_wins():
    def label(state):
        return V.build_view(state, now=FIXED_NOW)["next_action"]["label"]

    assert label(_state_with_bem("GUI_REQUIRED")) == "Copy AKABAK checklist"
    assert label(_state_with_bem("MANUAL_SOLVE_PENDING")) == "Import & validate (.vips)"
    assert label(_state_with_bem("MANUAL_SOLVE_COMPLETED")) == "Import & validate (.vips)"

    s = _state_with_bem("BEM_REJECTED", metrics={
        "curve": "Mic1", "n_points": 10, "worst_diff_db": 11.6, "mean_diff_db": -8.7,
        "tolerance_db": 6.0, "band_hz": [60.0, 200.0]})
    assert label(s) == "Re-export and retry"

    assert label(_state()) == "Mark decided"          # fixture is BEM_VALIDATED

    s = _state_with_bem("GUI_REQUIRED")               # a failed stage outranks all
    s["stages"]["PHYSICAL_FEASIBILITY"] = {"status": "failed", "detail": "FEASIBILITY"}
    assert label(s).startswith("Re-run from")


def test_annotations_are_consistent_and_default_to_metres():
    a = V.annotations_for(_state())
    assert a["units"] == "m"
    assert abs(a["path_length_m"] - 1.499) < 1e-6
    # w * h == area and w / h == aspect
    assert abs(a["mouth_width_mm"] * a["mouth_height_mm"] / 1e6
               - a["mouth_area_cm2"] / 1e4) < 1e-6
    assert abs((a["mouth_width_mm"] / a["mouth_height_mm"]) - a["aspect"]) < 1e-9
    assert a["bbox_m"] and len(a["bbox_m"]) == 3
    assert a["bends"] and a["bends"][0]["angle_deg"] > 0


def test_viewer_features_default_to_metres_with_a_visible_mm_toggle():
    feats = _built()["viewer"]["features"]
    assert feats["units"] == "m"
    assert feats["mm_toggle"] is True
    assert feats["dimensions"] is True
    assert feats["compare"] is False           # not in this milestone


# ---------------------------------------------------------------------------
#  M2 - the tab shell (template + generation)
# ---------------------------------------------------------------------------
TEMPLATE = ROOT / "hornflow" / "viz" / "viewer" / "index.html"
EMBED_RE = re.compile(
    r'<script id="app_view" type="application/json">(.*?)</script>', re.S)


def _embedded(html: str):
    m = EMBED_RE.search(html)
    return None if m is None else m.group(1)


def _candidate():
    import numpy as np
    from hornflow import config, fold
    from hornflow.architecture.front_loaded import build_master
    p = config.load(EXAMPLE)
    _, master = build_master(p, "folded_horn")
    return fold.StraightFold().generate(master, {"wall_mm": 18.0})[0]


def test_template_has_the_three_tabs_and_the_placeholders():
    tpl = TEMPLATE.read_text(encoding="utf-8")
    for tab in ('data-pane="viewer"', 'data-pane="workflow"', 'data-pane="results"'):
        assert tab in tpl
    assert "__APP_VIEW__" in tpl
    assert '__GLB_B64__' in tpl and "__TITLE__" in tpl
    assert 'src="ui/app.js"' in tpl and 'href="ui/app.css"' in tpl
    assert 'id="pane-viewer"' in tpl and 'id="pane-workflow"' in tpl
    assert 'id="pane-results"' in tpl
    assert 'id="btnDims"' in tpl and 'id="btnUnits"' in tpl


def test_existing_viewer_controls_are_untouched():
    """The viewer's own script and panel must survive the shell addition."""
    tpl = TEMPLATE.read_text(encoding="utf-8")
    for marker in ('renderer.localClippingEnabled = true',
                   'new THREE.GLTFLoader().parse(b64ToArrayBuffer(B64)',
                   "document.getElementById('btnTransparent').onclick",
                   "document.getElementById('btnCut').onclick",
                   "document.getElementById('btnReset').onclick",
                   '(function loop(){ requestAnimationFrame(loop)',
                   '<div id="view"><div id="info"></div></div>',
                   '<div id="panel">'):
        assert marker in tpl, marker
    # the viewer pane wraps the original markup, in order
    assert tpl.index('<section class="pane" id="pane-viewer">') < tpl.index('<div id="wrap">')


def test_write_viewer_without_app_view_keeps_only_the_viewer(tmp_path):
    out = viz_export.write_viewer(_candidate(), tmp_path / "viewer", title="t")
    html = Path(out["viewer"]).read_text(encoding="utf-8")
    assert _embedded(html) == ""              # empty -> app.js hides the other tabs
    assert (tmp_path / "viewer" / "ui" / "app.js").is_file()
    assert (tmp_path / "viewer" / "ui" / "app.css").is_file()
    assert (tmp_path / "viewer" / "vendor" / "three.min.js").is_file()
    assert (tmp_path / "viewer" / "scene.glb").is_file()


def test_write_viewer_embeds_a_parseable_view_model(tmp_path):
    view = V.first_run_view(project="demo", now=FIXED_NOW)
    out = viz_export.write_viewer(_candidate(), tmp_path / "viewer", app_view=view)
    html = Path(out["viewer"]).read_text(encoding="utf-8")
    embedded = json.loads(_embedded(html))
    assert embedded["view_schema"] == V.VIEW_SCHEMA
    assert embedded["mode"] == "first_run"
    assert len(embedded["questions"]) == 5
    assert embedded["annotations"]["units"] == "m"      # merged in by the writer


def test_embedded_json_cannot_break_out_of_the_script_tag(tmp_path):
    view = V.first_run_view(now=FIXED_NOW)
    view["project"]["name"] = "evil</script><script>alert(1)</script>"
    out = viz_export.write_viewer(_candidate(), tmp_path / "viewer", app_view=view)
    html = Path(out["viewer"]).read_text(encoding="utf-8")
    assert "<\\/script>" in html
    assert html.count('<script id="app_view"') == 1
    assert json.loads(_embedded(html))["project"]["name"].endswith("</script>")


# ---------------------------------------------------------------------------
#  M3 - the static Workflow tab, generated from a real run
# ---------------------------------------------------------------------------
def test_app_js_is_syntactically_valid():
    import shutil
    import subprocess
    node = shutil.which("node")
    if not node:
        return                                    # optional tool: nothing to check
    app_js = ROOT / "hornflow" / "viz" / "viewer" / "ui" / "app.js"
    res = subprocess.run([node, "--check", str(app_js)], capture_output=True)
    assert res.returncode == 0, res.stderr.decode()


def test_pipeline_emits_a_consistent_view_model_and_shell(tmp_path):
    s = run_pipeline(EXAMPLE, out_root=tmp_path, limits={"wall_mm": 18.0})
    vdir = Path(s["run_dir"]) / "deliverables" / "viewer"

    # the standalone model and the embedded copy must agree exactly
    standalone = json.loads((vdir / "app_view.json").read_text(encoding="utf-8"))
    html = (vdir / "viewer.html").read_text(encoding="utf-8")
    embedded = json.loads(_embedded(html))
    assert embedded == standalone

    # the shell assets travel with the run
    assert (vdir / "ui" / "app.js").is_file()
    assert (vdir / "ui" / "app.css").is_file()

    # the Workflow tab has everything it renders from
    for key in ("gates", "questions", "manual_bem", "import_panel", "outcome",
                "current_state", "next_action", "rerun", "artifacts", "annotations"):
        assert key in standalone, key
    assert len(standalone["gates"]) == 16
    assert len(standalone["questions"]) == 5
    assert standalone["mode"] == "manual_bem"          # a fresh run stops at the GUI
    assert standalone["manual_bem"]["state"] == "GUI_REQUIRED"
    assert standalone["next_action"]["label"] == "Copy AKABAK checklist"
    assert standalone["viewer"]["features"]["units"] == "m"
    # read-only: no mutating action is offered by the static host
    assert standalone["import_panel"]["available"] is False


def test_pipeline_state_and_view_agree_on_the_manual_state(tmp_path):
    s = run_pipeline(EXAMPLE, out_root=tmp_path, limits={"wall_mm": 18.0})
    run_dir = Path(s["run_dir"])
    state = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))
    view = json.loads((run_dir / "deliverables" / "viewer"
                       / "app_view.json").read_text(encoding="utf-8"))
    assert view["current_state"]["bem_state"] == state["validation"]["bem_manual"]["state"]
    assert view["current_state"]["run_id"] == state["run"]["run_id"]
    assert view["outcome"]["hard_gates"] == \
        state["final_recommendations"]["hard_gates_passed"]
    staged = {g["stage"]: g["status"] for g in view["gates"]}
    assert set(staged) == set(state["stages"])
    assert all(staged[k] == state["stages"][k]["status"] for k in staged)


def test_app_js_falls_back_to_viewer_only_when_there_is_no_view_model():
    """Backward compatibility: no app_view -> only the Viewer tab is shown."""
    js = (ROOT / "hornflow" / "viz" / "viewer" / "ui" / "app.js").read_text(
        encoding="utf-8")
    assert "if (!raw) { viewerOnly(); return; }" in js
    assert "catch (e) { viewerOnly(); return; }" in js
    assert "if (!view || !view.view_schema) { viewerOnly(); return; }" in js
    # viewerOnly() drops every pane except viewer and activates the viewer
    assert "b.getAttribute('data-pane') !== 'viewer'" in js
    assert "b.parentNode.removeChild(b)" in js
    assert "activate('viewer')" in js


def test_old_runs_without_a_shell_still_open(tmp_path):
    """A viewer.html written before this change has no tabs and must stay valid."""
    html = viz_export.write_viewer(_candidate(), tmp_path / "viewer")["viewer"]
    text = Path(html).read_text(encoding="utf-8")
    # strip the app view the way an old run would have it
    text = EMBED_RE.sub("", text)
    assert "btnDims" in text or "btnTransparent" in text
    assert "renderer.localClippingEnabled" in text
    assert (tmp_path / "viewer" / "scene.glb").is_file()


def test_view_model_survives_a_full_import_cycle(tmp_path):
    """After --bem-import the run re-emits a model that shows the outcome."""
    from hornflow.workflow import bem_import
    s = run_pipeline(EXAMPLE, out_root=tmp_path, limits={"wall_mm": 18.0})
    run_dir = Path(s["run_dir"])
    view = json.loads((run_dir / "deliverables" / "viewer"
                       / "app_view.json").read_text(encoding="utf-8"))
    ref = json.loads((run_dir / "state.json").read_text(encoding="utf-8"))["simulation_runs"][0]

    import numpy as np
    freqs = list(np.asarray(ref["frequency_hz"], dtype=float)[:10])
    spls = list(np.asarray(ref["spl_db"], dtype=float)[:10])
    export = run_dir / "deliverables" / "bem" / "export"
    export.mkdir(parents=True, exist_ok=True)
    rows = [(f, 20e-6 * 1.4142135623730951 * 10 ** ((v + 1.0) / 20.0), 0.0)
            for f, v in zip(freqs, spls)]
    lines = ["SourceDesc=VACS_Data_Text", "Data_Format=Complex",
             "Data_LevelType=SoundPressure", "Data_AbscUnit=Hz", "Data_BaseUnit=Pa",
             'Data_Legend="Mic1; x=0"', "Data"]
    lines += [" ".join(f"{x:.10g}" for x in r) for r in rows]
    lines += ["Data_End", ""]
    (export / "Akabak-t-Mic1.vips").write_bytes(
        "\n".join(lines).replace("\n", "\r\n").encode("utf-8"))

    res = bem_import.import_into_run(run_dir, export, tolerance_db=6.0)
    assert res["state"] == "BEM_VALIDATED"

    after = V.build_view(json.loads((run_dir / "state.json").read_text()), now=FIXED_NOW)
    assert after["current_state"]["bem_state"] == "BEM_VALIDATED"
    assert after["mode"] == "review"
    assert after["outcome"]["checks"] and after["outcome"]["metrics"]
    assert after["next_action"]["label"] == "Mark decided"



# ---------------------------------------------------------------------------
#  --emit-ui: refresh the shell of a finished run without re-running
# ---------------------------------------------------------------------------
def test_emit_ui_refreshes_a_finished_run(tmp_path):
    from hornflow.app import emit as emit_mod
    s = run_pipeline(EXAMPLE, out_root=tmp_path, limits={"wall_mm": 18.0})
    run_dir = Path(s["run_dir"])
    vdir = run_dir / "deliverables" / "viewer"
    glb_before = (vdir / "scene.glb").read_bytes()

    res = emit_mod.emit_ui_for_run(run_dir, now=FIXED_NOW)
    assert Path(res["files"]["viewer"]).is_file()
    assert res["view"]["run"]["run_id"] == s["run_id"]
    # the geometry is reused, not rebuilt
    assert (vdir / "scene.glb").read_bytes() == glb_before
    # and the standalone model still matches the embedded copy
    standalone = json.loads((vdir / "app_view.json").read_text(encoding="utf-8"))
    assert json.loads(_embedded((vdir / "viewer.html").read_text(encoding="utf-8"))) \
        == standalone
    assert standalone["generated_utc"] == FIXED_NOW


def test_emit_ui_does_not_touch_state(tmp_path):
    from hornflow.app import emit as emit_mod
    s = run_pipeline(EXAMPLE, out_root=tmp_path, limits={"wall_mm": 18.0})
    state_path = Path(s["run_dir"]) / "state.json"
    before = state_path.read_bytes()
    emit_mod.emit_ui_for_run(Path(s["run_dir"]))
    assert state_path.read_bytes() == before


def test_emit_ui_requires_a_run(tmp_path):
    from hornflow.app import emit as emit_mod
    try:
        emit_mod.emit_ui_for_run(tmp_path / "nope")
        assert False, "expected FileNotFoundError"
    except FileNotFoundError as exc:
        assert "state.json" in str(exc)

