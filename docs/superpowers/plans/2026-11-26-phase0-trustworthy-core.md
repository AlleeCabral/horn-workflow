# Phase 0: Trustworthy Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the audit findings that let HornFlow corrupt, misattribute or forge its run record, or overclaim in its report, so that every later feature builds on honest data.

**Architecture:** Changes are local to the existing modules. There is no new dependency.
- `hornflow/io/state_store.py` becomes the single locked writer of `state.json`.
- `hornflow/app/server.py` gains a request guard.
- The importer uses the strict transition function.
- Scoring, sensitivity and feasibility get targeted numeric fixes.
- State schema goes from 1.1 to 1.2, adding the input snapshot and run status, with a recorded migration.

**Tech Stack:** Python 3.10 to 3.12, numpy, scipy, PyYAML, pytest, hypothesis; vanilla JS in `hornflow/viz/viewer/ui/app.js`.

**Spec:**
- `docs/superpowers/specs/2026-11-26-hornflow-roadmap-design.md` (goal 1, anti-goals, D1, D2, D4).
- Finding IDs below refer to `docs/audit/2026-11-26-hornflow-audit.md`.

## Global Constraints

- **Branch:** `fix/phase0-trustworthy-core`, created in a worktree via `superpowers:using-git-worktrees`. One pull request per task group (A: Tasks 1 to 8 and 13 to 15; B: Tasks 9 to 12), or one for the phase.
- **Dependencies:** no new production or dev dependencies.
- **State writes:** every `state.json` write goes through `hornflow.io.state_store`.
- **Excursion conversions:** via `hornflow.domain.excursion` only (ADR-0012).
- **Legacy baseline:** `tests/test_baseline.py` stays green. Phase 0 must not change the legacy `curves.csv`. If a task changes the legacy report text, regenerate the baseline with `tools/capture_baseline.py` in that task's commit and say why.
- **Wording:** generated report and UI copy use no em dashes or en dashes.
- **Test commands:** run from the repository root.
  - Single test: `python3 -m pytest <file>::<test> -q`.
  - Full: `python3 tests/test_theory.py && python3 -m pytest tests -q`.

## Review Focus

1. **Two tabs, one project:** a decision posted from a tab showing run X while the server has switched to run Y returns `409 run_mismatch` and leaves Y untouched. Test in Task 3: `test_decision_for_other_run_is_refused`.
2. **Ctrl+C mid-run:** the run folder holds a `state.json` with `run.status == "interrupted"` and appears in `/api/runs`. Test in Task 7: `test_interrupted_run_is_listed`.
3. **A typo or unit slip in YAML:** `lenght:` or `throat_diameter: 0.26` stops with exit code 2 and a one-line `error:` naming the key, and leaves no run folder. Tests in Task 12: `test_unknown_key_is_rejected`, `test_cli_bad_yaml_leaves_no_run_dir`.
4. **A foreign, stale or junk export imported into a validated run:** the state stays `BEM_VALIDATED`, the earlier metrics are kept, and the attempt is recorded in `bem_manual.attempts[-1]` with `passed: False`. Test in Task 5: `test_failed_reimport_keeps_last_accepted_result`.
5. **Folded and straight horns acoustically identical:** the report says "no acoustic winner", and the critic finding `preference_not_decisive` fails. Test in Task 9: `test_tie_is_reported_as_no_acoustic_winner`.

## Task groups and order

- **Group A (persistence and app):** Tasks 1 to 8, 13, 14.
- **Group B (physics and report):** Tasks 9 to 12.
- **Task 15:** owner decisions.

Tasks 1 and 2 come first; Group A and Group B can then run in parallel (`superpowers:dispatching-parallel-agents`). Task 15 can happen any time before the pull request merges.

---

### Task 1: Test fixtures that run on a clean checkout (audit T1, T2)

**Files:**
- Create: `tests/conftest.py`
- Modify: `tests/test_app_api.py:43-50` (the `project` fixture)
- Modify: `tests/test_theory.py:26-33` (`check`)
- Modify: `.github/workflows/ci.yml` (keep the order; no pipeline-before-pytest dependency is needed after this task)

**Interfaces:**
- Produces:
  - session fixture `pipeline_run(tmp_path_factory) -> Path`: a fresh run directory made by `hornflow.workflow.orchestrator.run_pipeline("params/horn_jbl_1200b.yaml", out_root=<tmp>)`;
  - function fixture `project(tmp_path, pipeline_run) -> tuple[Path, str]`: the project root with `params/` and a copy of the run, plus the run id;
  - helper `_actions(project) -> AppActions`, equivalent to `AppActions(proj, base_definition=proj/"params/horn_jbl_1200b.yaml", run_dir=proj/"runs"/run_id)`, plus re-exports of `ApiError`, `ACCEPT_REASONS` (from `hornflow.app.actions`), `load_state_file` and `update_state`, for all app tests;
  - helper `copy_exports(run_dir: Path, pattern: str = "Akabak-Rad1_23Sept26-*") -> Path`, which copies matching `.vips` files from `tests/fixtures/bem_export` into `run_dir/deliverables/bem/export` and returns that folder.
    - It also rewrites the run manifest's `generated_utc` to `"2026-09-01T00:00:00Z"`, so the fixture exports (dated September 2026 in their headers) count as newer than the inputs.
    - Without this, Task 6's header-timestamp check would reject every fixture.

- [ ] **Step 1: Write the failing test** in `tests/test_fixtures.py`:

```python
def test_project_fixture_needs_no_repo_runs_folder(project):
    proj, run_id = project
    assert (proj / "runs" / run_id / "state.json").is_file()
    assert run_id.startswith("run_")

def test_theory_check_raises_under_pytest():
    import tests.test_theory as tt
    import pytest
    with pytest.raises(AssertionError):
        tt.check("deliberate", False, strict=True)
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_fixtures.py -q`. Expected: FAIL (fixture `project` is not defined for this module; `check` has no `strict` parameter).
- [ ] **Step 3: Implement** the fixtures in `tests/conftest.py`. Replace the body of the `project` fixture in `test_app_api.py` with the shared one.
  - Add `strict: bool = False` to `check(name, condition, detail="", strict=False)`; when `strict`, a failure raises `AssertionError(name)`.
  - Each pytest-collected `test_*` function in `test_theory.py` calls `check(..., strict=True)` through a module flag `STRICT = "pytest" in sys.modules`.
  - The standalone run still prints all checks and exits non-zero on failure.
- [ ] **Step 4: Run** the full suite command (see Global Constraints). Expected: 147/147 legacy checks; pytest with 0 errors in `test_app_api.py`.
- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_fixtures.py tests/test_app_api.py tests/test_theory.py .github/workflows/ci.yml
git commit -m "test: self-contained run fixture; theory checks fail under pytest"
```

### Task 2: One locked writer for state files (audit S1)

**Files:**
- Modify: `hornflow/io/artifacts.py:31-40` (`atomic_write`)
- Modify: `hornflow/io/state_store.py`
- Test: `tests/test_state_store.py`

**Interfaces:**
- Produces:
  - `atomic_write(path: Path, data: bytes) -> None`: same signature, now with unique temp names;
  - `STATE_LOCK: threading.RLock` in `state_store`;
  - `update_state(path: str | Path, fn: Callable[[DesignState], T]) -> T`: under `STATE_LOCK` it loads, calls `fn(state)`, saves, and returns `fn`'s result;
  - `save_state(state, path)`, which now also takes `STATE_LOCK`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_concurrent_atomic_writes_never_fail(tmp_path):
    import threading
    from hornflow.io.artifacts import atomic_write
    target = tmp_path / "x.json"
    errors = []
    def work(i):
        for _ in range(100):
            try:
                atomic_write(target, f'{{"i": {i}}}'.encode())
            except Exception as e:
                errors.append(e)
    ts = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert errors == []
    assert json.loads(target.read_text())["i"] in range(4)
    assert list(tmp_path.glob("x.json.tmp*")) == []

def test_update_state_serialises_read_modify_write(pipeline_run):
    import threading
    from hornflow.io.state_store import update_state, load_state_file
    p = pipeline_run / "state.json"
    def add(n):
        for k in range(25):
            update_state(p, lambda st: st.decision_log.append({"event": f"t{n}-{k}"}))
    ts = [threading.Thread(target=add, args=(n,)) for n in range(4)]
    [t.start() for t in ts]; [t.join() for t in ts]
    events = [e["event"] for e in load_state_file(p).decision_log]
    assert sum(e.startswith("t") for e in events) == 100
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_state_store.py -q`. Expected: FAIL (`FileNotFoundError` errors in the first test; `update_state` is missing in the second).
- [ ] **Step 3: Implement.**
  - `atomic_write` uses `tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")`, then `fsync`, then `os.replace`. It removes the temp file on exception.
  - Add `STATE_LOCK` and `update_state` to `state_store.py`.
- [ ] **Step 4: Run** the full suite. Expected: all pass.
- [ ] **Step 5: Commit** `fix(io): unique temp files and a locked state read-modify-write (S1)`.

### Task 3: Run id on every mutating call; visible unreadable state (audit S1, S2)

**Files:**
- Modify: `hornflow/app/actions.py:109-115` (`_state`), `:299-321` (`import_vips`), `:323-356` (`decision`)
- Modify: `hornflow/app/server.py:110-133` (`_handle_post`)
- Modify: `hornflow/viz/viewer/ui/app.js`: every `fetch('/api/import' | '/api/decision' | '/api/brief/freeze' | '/api/run'` call sends `run_id: view.run.run_id` (or `null` for first run)
- Test: `tests/test_app_api.py`

**Interfaces:**
- Consumes: `update_state` (Task 2).
- Produces:
  - `AppActions.import_vips(*, run_id: str, subdir=None, tolerance_db=None) -> dict`;
  - `AppActions.decision(*, run_id: str, kind, reason=None, note="", actor=None, now=None) -> dict`;
  - `ApiError("run_mismatch", ..., status=409, expected=<server run id>, got=<run_id>)`;
  - `view()` returns `{"mode": "state_error", "error": {"code": "state_unreadable", "message": str}}` when `state.json` exists but cannot be loaded.

- [ ] **Step 1: Write the failing tests:**

```python
def test_decision_for_other_run_is_refused(project):
    a = _actions(project)
    other = a.run_dir.name
    with pytest.raises(ApiError) as e:
        a.decision(run_id="run_not_this_one", kind="accept_unvalidated",
                   reason=ACCEPT_REASONS[0])
    assert e.value.code == "run_mismatch" and e.value.status == 409
    assert not load_state_file(a.run_dir / "state.json").validation.get("accepted_unvalidated")

def test_corrupt_state_is_reported_not_first_run(project):
    a = _actions(project)
    (a.run_dir / "state.json").write_text("{ broken")
    v = a.view()
    assert v["mode"] == "state_error" and v["error"]["code"] == "state_unreadable"
```

- [ ] **Step 2: Run** these tests. Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Add the `run_id` check at the top of `import_vips` and `decision`.
  - Route their state writes through `update_state`.
  - `_state()` returns `None` only when the file is missing, and raises an internal `_StateUnreadable` that `view()` maps to the error mode.
  - The server passes `body.get("run_id")`. A missing `run_id` on these two endpoints gives `400 run_id_required`.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `fix(app): mutating calls name their run; unreadable state is visible (S1, S2)`.

### Task 4: Request guard on the local server (audit S3)

**Files:**
- Modify: `hornflow/app/server.py` (`_read_body`, `do_GET`, `do_POST`, `_handle_get` `/api/health`)
- Modify: `hornflow/app/__main__.py:31` (`--host`)
- Test: `tests/test_app_api.py` (server tests use `create_server(actions, port=0)` in a thread and `http.client`)

**Interfaces:**
- Produces:
  - `_guard(self) -> None` raising `ApiError`:
    - `bad_host` (403) when the `Host` header is not `127.0.0.1:<port>` or `localhost:<port>` (or the `--host` value given at start);
    - `bad_origin` (403) when an `Origin` header is present and is not `http://<allowed host>:<port>`;
    - `bad_content_type` (415) on POST when the media type is not `application/json`;
    - `bad_length` (400) when `Content-Length` is not an integer.
  - `/api/health` returns `{"ok": true}` only.

- [ ] **Step 1: Write the failing tests:**

```python
@pytest.mark.parametrize("headers,code", [
    ({"Host": "evil.example", "Content-Type": "application/json"}, 403),
    ({"Origin": "http://evil.example", "Content-Type": "application/json"}, 403),
    ({"Content-Type": "text/plain"}, 415),
    ({"Content-Type": "application/json", "Content-Length": "abc"}, 400),
])
def test_cross_site_and_malformed_requests_are_refused(live_server, headers, code):
    status, body = live_server.post("/api/brief", {"values": {"deployment": "x"}}, headers)
    assert status == code
    assert live_server.actions.brief.draft().get("values", {}).get("deployment") != "x"

def test_health_does_not_leak_paths(live_server):
    status, body = live_server.get("/api/health")
    assert status == 200 and body == {"ok": True}
```

  - Add a `live_server` fixture in `tests/conftest.py`. It starts `create_server(actions, port=0)` in a daemon thread, provides `.get(path, headers=None)`, `.post(path, json, headers=None)` and `.actions`, and shuts down at teardown.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** `_guard` and call it first in `do_GET` and `do_POST` (static files included). `__main__` prints a warning line when `--host` is not `127.0.0.1`, `localhost` or `::1`.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `fix(app): refuse cross-site, foreign-host and non-JSON requests (S3)`.

### Task 5: Strict import transitions and attempt history (audit B2, S5 of section B)

**Files:**
- Modify: `hornflow/workflow/bem_import.py:51-69` (`_walk_to`), `:82-135` (`import_into_run`)
- Test: `tests/test_bem_manual.py`

**Interfaces:**
- Consumes: `manual.advance(current, target)` (exists, `manual.py:86`), `update_state` (Task 2), `copy_exports` (Task 1).
- Produces: `validation.bem_manual` gains `attempts: list[{"utc", "passed", "state_after", "checks", "metrics", "tolerance_db", "files_sha256": {name: sha}}]`.
  - `metrics`, `checks` and `state` at the top level always describe the **last accepted** import (passed).
  - A failed attempt never overwrites them.
  - An unknown stored state raises `ValueError("unknown manual-solve state ...")`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_failed_reimport_keeps_last_accepted_result(pipeline_run, tmp_path):
    exp = copy_exports(pipeline_run)
    first = import_into_run(pipeline_run, exp, tolerance_db=12.0)
    assert first["state"] == "BEM_VALIDATED"
    junk = tmp_path / "junk"; junk.mkdir(); (junk / "x.vips").write_text("")
    import_into_run(pipeline_run, junk, tolerance_db=12.0)
    rec = load_state_file(pipeline_run / "state.json").validation["bem_manual"]
    assert rec["state"] == "BEM_VALIDATED"
    assert rec["metrics"] == first["metrics"]
    assert rec["attempts"][-1]["passed"] is False
    assert len(rec["attempts"]) == 2

def test_unknown_stored_state_is_an_error(pipeline_run):
    update_state(pipeline_run / "state.json",
                 lambda st: st.validation.setdefault("bem_manual", {}).update(state="WHATEVER"))
    with pytest.raises(ValueError, match="unknown manual-solve state"):
        import_into_run(pipeline_run, copy_exports(pipeline_run))
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.**
  - Replace `_walk_to` with `_path_to(current, target) -> list[str]`, the shortest legal path (BFS over `ALLOWED_TRANSITIONS`). It raises `ValueError` when unreachable or unknown.
  - Apply each step with `manual.advance`.
  - On a failed attempt, append to `attempts` and leave the rest of the record unchanged.
  - Write `bem_manual_report.md` with `atomic_write`.
  - All state changes go through `update_state`.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `fix(bem): strict import transitions; failed attempts never overwrite a verdict (B2)`.

### Task 6: Bounded tolerance and hard provenance (audit B1, B4, B5)

**Files:**
- Modify: `hornflow/physics/solvers/bem_manual.py:139-225` (`validate_exports`), `hornflow/bem.py:767-768` (pressure-curve selection), `:820` (`choose_best`)
- Modify: `hornflow/physics/solvers/manual.py:108-160` (`RunManifest`, `build_manifest`): add `expected_graph_group: str | None` and `tolerance_db: float`
- Modify: `hornflow/app/server.py:118-121`, `hornflow/app/actions.py` (`import_vips`)
- Modify: `run_workflow.py:299-339` (an import never regenerates inputs); `hornflow/cli.py:92-101` (refuse a folder outside a run)
- Test: `tests/test_bem_manual.py`, `tests/test_app_api.py`

**Interfaces:**
- Produces:
  - `TOLERANCE_RANGE_DB = (0.5, 20.0)` and `DEFAULT_TOLERANCE_DB = 6.0` in `bem_manual.py` (D1 placeholder).
  - `ApiError("tolerance_out_of_range", status=400)`. `tolerance_db=None` means the manifest value, then the default; `0` is out of range, not 6.
  - Checks `belongs_to_run` and `run_manifest_matches` are `HARD`.
  - `belongs_to_run` passes only when every file's `Graph_Group` equals `manifest.expected_graph_group`. When that is `None`, all files must share one `Graph_Group`, and the check records it into the manifest on the first accepted import.
  - The directory match is no longer evidence.
  - `export_timestamp_after_inputs` uses the `.vips` header timestamp when present, else mtime.
  - The on-axis curve is chosen only from files whose `Graph_Caption` contains `Mic` and whose `Data_BaseUnit` is `Pa`.
  - `validation.relaxed_tolerance: bool` is true when `tolerance_db > DEFAULT_TOLERANCE_DB`.

- [ ] **Step 1: Write the failing tests:**

```python
@pytest.mark.parametrize("tol", [0, -1, 1e9, float("inf"), float("nan")])
def test_tolerance_out_of_range_is_refused(project, tol):
    a = _actions(project); copy_exports(a.run_dir)
    with pytest.raises(ApiError) as e:
        a.import_vips(run_id=a.run_dir.name, tolerance_db=tol)
    assert e.value.code == "tolerance_out_of_range"

def test_mixed_projects_fail_provenance(pipeline_run):
    exp = copy_exports(pipeline_run, "Akabak-*")          # Rad1 and Jbl1200B together
    res = import_into_run(pipeline_run, exp, tolerance_db=12.0)
    names = {c["name"]: c for c in res["validation"]["checks"]}
    assert names["belongs_to_run"]["passed"] is False
    assert names["belongs_to_run"]["severity"] == "hard"
    assert res["state"] != "BEM_VALIDATED"

def test_le_only_export_has_no_on_axis_curve(pipeline_run):
    exp = copy_exports(pipeline_run, "Akabak-Rad1_22Sept26-LE*")
    res = import_into_run(pipeline_run, exp, tolerance_db=20.0)
    assert res["validation"]["passed"] is False

def test_cli_import_outside_run_dir_does_not_start_a_run(tmp_path, capsys):
    from hornflow.cli import main
    rc = main(["params/horn_jbl_1200b.yaml", "--out", str(tmp_path / "runs"),
               "--bem-import", "tests/fixtures/bem_export"])
    assert rc == 2 and not (tmp_path / "runs").exists()
    assert "not inside a run" in capsys.readouterr().err
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** as specified in Interfaces.
  - The server passes `body.get("tolerance_db")` unchanged (no `or 6.0`).
  - `run_workflow.py`: when `--bem-import` is given, skip `write_bem_files` and read the existing manifest.
- [ ] **Step 4: Run** the full suite. Expected: pass. `test_baseline` is unaffected.
- [ ] **Step 5: Commit** `fix(bem): bounded tolerance, hard provenance from .vips headers, no regenerate on import (B1, B4, B5)`.

### Task 7: Per-stage saves, interrupted runs, typed failures, live progress (audit S5, S6)

**Files:**
- Modify: `hornflow/workflow/orchestrator.py:63-102` (`run`), `:207-212` (`recoverability` becomes `recoverable`), `:368-392` (`_finalize`)
- Modify: `hornflow/domain/state.py` (`run.status` allowed values)
- Modify: `hornflow/app/actions.py:95-100` (`runs`), `:260-297` (`progress`)
- Modify: `docs/adr.md` ADR-0003 ("recoverability" becomes "recoverable")
- Test: `tests/test_pipeline.py`, `tests/test_app_api.py`

**Interfaces:**
- Produces:
  - `state.run["status"]` is one of `"running"`, `"completed"`, `"failed"` or `"interrupted"`.
  - The state is saved (via `save_state`) after `INPUT_AUDIT` starts and after every stage.
  - An exception in a stage gives that stage `status="failed"` and `failure={"category": "EXCEPTION", "failed_checks": [repr(exc)]}`, then `run.status="failed"`; the exception is re-raised after saving.
  - `KeyboardInterrupt` gives `run.status="interrupted"`, saved, then re-raised.
  - `AppActions.progress()` reports the stage counts of the **active** run (`self._run["run_id"]`). A `skipped` optional stage counts as done.

- [ ] **Step 1: Write the failing tests:**

```python
def test_zero_valid_folds_is_data_not_a_crash(tmp_path):
    s = run_pipeline("params/horn_jbl_1200b.yaml", out_root=tmp_path,
                     limits={"max_fold_count": 0})
    st = load_state_file(Path(s["run_dir"]) / "state.json")
    assert st.stages["FOLD_GEOMETRY_VALIDATION"]["status"] == "failed"
    assert st.stages["FOLD_GEOMETRY_VALIDATION"]["failure"]["recoverable"] is False

def test_interrupted_run_is_listed(tmp_path, monkeypatch):
    from hornflow.workflow import orchestrator as o
    def boom(self): raise KeyboardInterrupt
    monkeypatch.setattr(o.Pipeline, "stage_architecture", boom)
    with pytest.raises(KeyboardInterrupt):
        run_pipeline("params/horn_jbl_1200b.yaml", out_root=tmp_path)
    (run_dir,) = tmp_path.iterdir()
    st = load_state_file(run_dir / "state.json")
    assert st.run["status"] == "interrupted"
    assert st.stages["PHYSICAL_FEASIBILITY"]["status"] == "passed"

def test_completed_run_progress_is_100_percent(project):
    a = _actions(project)
    a.start_run(wait=True)
    assert a.progress()["percent"] == 100
```

- [ ] **Step 2: Run.** Expected: FAIL (`TypeError` on `recoverability`; there is no `state.json` after an interrupt).
- [ ] **Step 3: Implement** as specified. `run_pipeline` adds `"run_dir": str(self.run_dir)` to its summary if it is missing.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `fix(pipeline): save state per stage, record interrupts and exceptions, fix StageFailure kwarg (S5, S6)`.

### Task 8: Reproducible runs: input snapshot, relative paths, schema 1.2 (audit S7, F15)

**Files:**
- Modify: `hornflow/workflow/orchestrator.py:137-139` (`state.run`)
- Modify: `hornflow/domain/state.py:20` (`SCHEMA_VERSION = "1.2"`), `:153` (`MIGRATIONS["1.1"]`), and `from_dict` (keep unknown top-level keys under `extra`, and write them back)
- Modify: `hornflow/workflow/bem_import.py:87`, `hornflow/optimize/sensitivity.py:57` (read the snapshot, not the original path)
- Modify: `hornflow/app/brief.py:288-367` (`freeze`): generated definition file name `<slug>-r<revision>.yaml`
- Modify: `hornflow/physics/solvers/manual.py` (manifest paths relative to the run directory)
- Modify: `docs/migration-notes.md`: add the 1.1 to 1.2 section
- Test: `tests/test_domain.py`, `tests/test_pipeline.py`

**Interfaces:**
- Produces:
  - Files `runs/<id>/inputs/definition.yaml` and `runs/<id>/inputs/driver.yaml`, copied byte for byte at run start.
  - `state.run["inputs"] = {"definition": "inputs/definition.yaml", "definition_sha256": str, "driver": "inputs/driver.yaml" | None, "driver_sha256": str | None, "limits": dict, "code_version": str}`. `code_version` is `git describe --always --dirty` when git is available, else `hornflow.__version__`.
  - `run_input_path(run_dir: Path, state) -> Path` in `hornflow/io/state_store.py`. It returns the snapshot definition, and falls back to `state.run["input_path"]` for 1.1 runs, logging that the run is "not reproducible".
  - Migration `1.1 -> 1.2` sets `run.inputs = None` and `run.status = "completed"` when missing, and records itself in `state.migrations`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_run_snapshots_its_inputs(pipeline_run):
    st = load_state_file(pipeline_run / "state.json")
    inp = st.run["inputs"]
    assert (pipeline_run / inp["definition"]).read_bytes() == Path("params/horn_jbl_1200b.yaml").read_bytes()
    assert inp["definition_sha256"] == sha256_of_file(pipeline_run / inp["definition"])
    assert not any(str(v).startswith("/") for v in inp.values() if isinstance(v, str))

def test_import_uses_snapshot_not_edited_yaml(project):
    proj, run_id = project
    run_dir = proj / "runs" / run_id
    (proj / "params" / "horn_jbl_1200b.yaml").write_text("broken: [")
    res = import_into_run(run_dir, copy_exports(run_dir), tolerance_db=12.0)
    assert res["state"] in ("BEM_VALIDATED", "BEM_REJECTED")

def test_migration_1_1_to_1_2_keeps_unknown_keys():
    raw = json.loads(Path("tests/fixtures/app_view/jbl_state_trimmed.json").read_text())
    raw["schema_version"] = "1.1"; raw["future_field"] = {"a": 1}
    st = load_state(raw)
    assert st.schema_version == "1.2" and st.to_dict()["future_field"] == {"a": 1}
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `feat(state): schema 1.2 with input snapshot and relative paths (S7)`.

### Task 9: Honest architecture scoring (audit P1; decision D4)

**Files:**
- Modify: `hornflow/architecture/registry.py:33` (`PREFERENCE_BONUS`), `:55-80` (`score`)
- Modify: `hornflow/critique/critic.py:69-81` (`_preference_check`)
- Modify: `hornflow/reporting/markdown.py` (the "best overall" sentence)
- Modify: `docs/adr.md` ADR-0005 (actual scale)
- Test: `tests/test_pipeline.py`

**Interfaces:**
- Produces:
  - `PREFERENCE_BONUS = {"folded_horn": 1.0}`, now in score points (dB-based), applied as `+ bonus` (no `100 *`). This is a D4 placeholder.
  - `TIE_TOLERANCE_POINTS = 0.5`.
  - `score()` adds `raw_score` (without bonus) to each entry.
  - `decisive_winner(scores) -> str | None`: the raw-score leader, or `None` when the top two feasible raw scores are within `TIE_TOLERANCE_POINTS`.
  - `_preference_check` fails (severity `"reject"`) when the bonus winner differs from `decisive_winner`, including `None`.
  - Report wording when `decisive_winner` is `None`: `"No acoustic winner: {a} and {b} score within {tol} points; {preferred} is listed first by preference only."`

- [ ] **Step 1: Write the failing test:**

```python
def test_tie_is_reported_as_no_acoustic_winner(pipeline_run):
    st = load_state_file(pipeline_run / "state.json")
    f = {x["check"]: x for x in st.critic_findings}["preference_not_decisive"]
    assert f["passed"] is False and f["severity"] == "reject"
    report = (pipeline_run / "deliverables" / "report.md").read_text()
    assert "No acoustic winner" in report
    assert "is also the best overall design" not in report
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** as specified. Sort raw scores independently of bonus order (`sorted(..., key=lambda s: -s["raw_score"])`).
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `fix(scoring): report ties honestly; bonus on the real scale (P1)`.

### Task 10: Sensitivity that measures what it says (audit P3, P11)

**Files:**
- Create: `hornflow/metrics.py`
- Modify: `hornflow/optimize/sensitivity.py:20-90`, `hornflow/architecture/box_models.py:43-56`
- Modify: `hornflow/config.py:357-372` (`apply_overrides`)
- Modify: `hornflow/sweep.py:203` (`sorted`)
- Test: `tests/test_metrics.py`, `tests/test_pipeline.py`

**Interfaces:**
- Produces:
  - `minus3db_cutoff(f: np.ndarray, spl: np.ndarray, f_lo: float, f_hi: float) -> float | None`: the band mean is the reference. Scan **downward** from the lowest in-band index and return the first frequency where SPL drops at or below mean minus 3 dB, linearly interpolated in log f. Return `None` when it never drops on the grid.
  - `LEVERS` become relative: `(label, key, factor_strict, factor_relaxed, unit)` with factors `f_low ×1.15 / ×0.85`, `horn.length ×0.8 / ×1.2`, `mouth` (applied to `fc` ×1.15 / ×0.85, because `fc` and length define the mouth), `driver.rear_volume ×0.5 / ×2.0`, `simulation.voltage ×0.7 / ×1.4`. Each case also records `geometry_changed: dict[str, float]` (mouth area, length, throat) and `no_effect: bool`.
  - `apply_overrides` merges `driver.*` overrides into the loaded driver file when `driver` is a file reference (it loads the file, then merges).
  - `sweep` sorts with `key=lambda v: (isinstance(v, str), v if not isinstance(v, str) else str(v))`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_cutoff_of_a_highpass_is_inside_the_grid():
    f = np.geomspace(20, 500, 400)
    spl = 100 + 10*np.log10(1/(1+(60/f)**8))          # 4th-order-ish high-pass at 60 Hz
    fc = minus3db_cutoff(f, spl, 80, 250)
    assert 55 < fc < 65

def test_cutoff_none_when_never_drops():
    f = np.geomspace(20, 500, 50)
    assert minus3db_cutoff(f, np.full_like(f, 90.0), 80, 250) is None

def test_rear_chamber_lever_runs_and_reports_effect(pipeline_run):
    st = load_state_file(pipeline_run / "state.json")
    rc = [r for r in st.sensitivity_runs if r["limit"] == "rear_chamber"]
    assert rc and "error" not in rc[0]["stricter"]["metrics"]
    assert "error" not in rc[0]["relaxed"]["metrics"]
    assert all(r["base"]["cutoff_minus3db_hz"] != 20.0 for r in st.sensitivity_runs)
    mouth = [r for r in st.sensitivity_runs if r["limit"] == "mouth_area"][0]
    assert mouth["relaxed"]["geometry_changed"]["mouth_area_cm2"] != 0.0

def test_sweep_mixed_axis_does_not_crash(tmp_path):
    # axis values "auto" and 1200 on horn.length
    ...  # call sweep.write_report with two rows having those overrides; assert the file is written
```

  - The last test must be written concretely by the implementer, using `sweep.SweepRow` with `ok=True` and `overrides={"horn.length": "auto"}` / `{"horn.length": 1200}`, and asserting that `write_report` returns a path that exists.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement.** Route `sensitivity._metrics` and `box_models.band_metrics` through `metrics.minus3db_cutoff`.
- [ ] **Step 4: Run** the full suite. Expected: pass. `test_baseline` is unaffected, because legacy sweep metrics are unchanged.
- [ ] **Step 5: Commit** `fix(sensitivity): real -3 dB point, relative levers, driver overrides (P3, P11)`.

### Task 11: Physics corrections (audit P4, P5, P6, P7, S11)

**Files:**
- Modify: `hornflow/physics/feasibility.py:117-133`
- Modify: `hornflow/theory.py:603-625` (`piston_q`, `piston_di`)
- Modify: `hornflow/workflow/orchestrator.py:110-135` (`state.driver`, constraints)
- Modify: `hornflow/io/state_store.py` (`save_state` writes `NaN` and `inf` as `null`)
- Test: `tests/test_theory.py` (new checks), `tests/test_domain.py`

**Interfaces:**
- Produces:
  - `_displacement_spl(...)` returns rms-referenced dB: peak pressure divided by `RMS_TO_PEAK` (from `domain.excursion`). Expected JBL value: 115.24 dB (was 118.25).
  - `piston_q(ka, half_space=True)`: unchanged for `half_space=True`. For `False`, use the unbaffled approximation `Q = 1 + (ka)^2` for `ka < 1`, merging into the baffled curve for `ka >= 1`. `piston_di(0.01, half_space=False)` must be within 0.05 dB of 0. Record the approximation and its source in the docstring. Q: confirm the model (D7 related).
  - `_thermal_spl` returns `None` when no rating exists. `limiting_factors` gets `"thermal-limit-unknown"`, never a NaN comparison.
  - `state.driver` writes `Xmax_mm` as `null` when unknown, `Xmax_convention` from `normalize_convention(driver.Xmax_convention)`, and adds `Xmax_one_way_peak_mm`. `depth_mm` and `mouth_area_cm2` are `null` for `auto`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_displacement_spl_is_rms_referenced():
    from hornflow.physics.feasibility import _displacement_spl
    v = _displacement_spl(50.0, 0.05286, 0.01135, 1.205, 343.0, half_space=True)
    peak = 20*np.log10(1.205*(2*np.pi*50)**2*0.05286*0.01135/(2*np.pi*1.0)/20e-6)
    assert abs(v - (peak - 20*np.log10(np.sqrt(2)))) < 1e-9

def test_free_space_di_tends_to_zero():
    from hornflow.theory import piston_di
    assert abs(float(piston_di(0.01, half_space=False)[0])) < 0.05
    assert abs(float(piston_di(0.01, half_space=True)[0]) - 3.01) < 0.05

def test_state_json_is_strict_json(pipeline_run):
    json.loads((pipeline_run / "state.json").read_text(), parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))

def test_peak_to_peak_driver_is_recorded_as_such(tmp_path):
    # copy params and the driver into tmp, set Xmax_convention: peak_to_peak, run the pipeline
    ...
    assert st.driver["Xmax_convention"] == "peak_to_peak"
    assert abs(st.driver["Xmax_one_way_peak_mm"] - 0.5*st.driver["Xmax_mm"]) < 1e-9
```

  - The last test's setup must be written concretely: copy `params/` to `tmp_path`, edit `drivers/jbl_1200b.yaml` with `yaml.safe_load` / `safe_dump`, then `run_pipeline(tmp_path/"params/horn_jbl_1200b.yaml", out_root=tmp_path/"runs")`.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** as specified.
- [ ] **Step 4: Run** the full suite. Expected: pass, including 147+ theory checks (add the two DI checks to the standalone list).
- [ ] **Step 5: Commit** `fix(physics): rms-referenced displacement SPL, free-space DI, honest Xmax and unknowns (P4 to P7)`.

### Task 12: Input validation and clean CLI errors (audit P12, U7, P10 partial)

**Files:**
- Create: `hornflow/config_schema.py`
- Modify: `hornflow/config.py:341-445` (`load`, `build`, boolean parsing)
- Modify: `hornflow/cli.py:110-136`, `run_workflow.py:233-260`
- Modify: `hornflow/workflow/orchestrator.py:38-62` (load and validate before creating the run directory)
- Modify: `hornflow/advise.py` (force `horn.profile: exponential` in candidate overrides; text uses `simulation.voltage`)
- Test: `tests/test_config.py`

**Interfaces:**
- Produces:
  - `KNOWN_KEYS: dict[str, set[str]]`, per section, from the dataclass fields plus documented extras.
  - `validate_raw(raw: dict) -> list[str]`: error strings. Unknown keys give `"unknown key 'horn.lenght' (did you mean 'horn.length'?)"` via `difflib.get_close_matches`. Non-finite numbers, non-positive dimensions, zero or negative distance or voltage, `rear_q <= 0`, and booleans given as strings are all errors.
  - `RANGE_HINTS` adds unit-slip errors: a `throat_diameter` below 5 mm or above 1000 mm gives `"looks like metres? values are in mm"`.
  - `config.load` raises `ConfigError(errors: list[str])`, a subclass of `ValueError`.
  - `cli.main(argv: list[str] | None = None) -> int`. It returns `2` and prints `error: <first error>` plus `(+N more)` to stderr on `ConfigError` or `yaml.YAMLError`. `run_workflow.py` does the same.
  - After the pipeline runs, the CLI prints one line per stage, `<status padded to 8> <STAGE>`, and returns `1` when any stage is `failed` or `blocked`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_unknown_key_is_rejected(tmp_path):
    p = _copy_def(tmp_path, lambda d: d["horn"].update(lenght=1500))
    with pytest.raises(ConfigError, match=r"unknown key 'horn.lenght' \(did you mean 'horn.length'\?\)"):
        config.load(p)

@pytest.mark.parametrize("path,value,msg", [
    ("horn.throat_diameter", 0.26, "looks like metres"),
    ("driver.Mms", float("nan"), "must be finite"),
    ("simulation.observation_distance", 0, "must be > 0"),
    ("simulation.half_space", "false", "must be true or false"),
])
def test_bad_values_are_rejected(tmp_path, path, value, msg):
    with pytest.raises(ConfigError, match=msg):
        config.load(_copy_def(tmp_path, _set(path, value)))

def test_cli_bad_yaml_leaves_no_run_dir(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"; bad.write_text("horn: [")
    rc = cli.main([str(bad), "--out", str(tmp_path / "runs")])
    assert rc == 2 and not (tmp_path / "runs").exists()
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("error:")
```

  - `_copy_def` copies `params/` to `tmp_path`, applies the edit to `horn_jbl_1200b.yaml` (inline driver dicts are expanded so `driver.*` edits work), and returns the path. `_set(path, value)` returns that edit function.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** as specified. Both example definitions in `params/` must load without errors. Remove `throat_angle` and `simulation.directivity` from `params/*.yaml` if unused, or add them to `KNOWN_KEYS` with a `"parsed, not used"` warning (not an error).
- [ ] **Step 4: Run** the full suite. Expected: pass; `test_baseline` unaffected.
- [ ] **Step 5: Commit** `feat(config): strict input validation with clear CLI errors (P12, U7)`.

### Task 13: App starts on the right project and with no runs (audit U1, U2)

**Files:**
- Modify: `hornflow/app/brief.py:131-146` (`BriefStore.__init__`)
- Modify: `hornflow/app/actions.py:72-90` (pass the selected run's definition as base)
- Modify: `hornflow/app/server.py:135-160` (`_doc_root`, `_static`)
- Test: `tests/test_app_api.py`

**Interfaces:**
- Consumes: `run_input_path` (Task 8).
- Produces:
  - `BriefStore(project_root, base_definition=None, definitions_dir=None)`: when `base_definition` is `None` and more than one definition exists, `self.base_definition = None`, and `freeze()` raises `ApiError("base_ambiguous", status=409, choices=[...])`.
  - `AppActions` sets the base to `run_input_path(run_dir, state)` whenever a run is selected or adopted.
  - With no run, `GET /viewer/viewer.html` (and `/`) serves the packaged `hornflow/viz/viewer/index.html` with `first_run_view()` embedded as `window.HORNFLOW_VIEW`, through the same embedding function used by `viz/export.py`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_freeze_uses_the_selected_runs_definition(project):
    a = AppActions(project[0])            # no --base
    a.freeze(_complete_values())
    gen = yaml.safe_load(Path(a.brief.generated_path()).read_text())
    assert gen["project"].startswith("jbl")
    assert gen["horn"]["throat_diameter"] == yaml.safe_load(
        (project[0] / "params/horn_jbl_1200b.yaml").read_text())["horn"]["throat_diameter"]

def test_first_run_page_is_served(tmp_path, live_server_factory):
    shutil.copytree("params", tmp_path / "params")
    srv = live_server_factory(AppActions(tmp_path, base_definition=tmp_path/"params/horn_jbl_1200b.yaml"))
    status, body = srv.get_text("/viewer/viewer.html")
    assert status == 200 and '"mode": "first_run"' in body
```

  - Add `generated_path()` to `BriefStore`, returning the last frozen generated definition path. Add `live_server_factory` and `get_text` to the conftest server helper.
- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** as specified. Update the README app command to show `--base` only as optional.
- [ ] **Step 4: Run** the full suite. Expected: pass.
- [ ] **Step 5: Commit** `fix(app): base definition follows the selected run; first-run page served (U1, U2)`.

### Task 14: Decision loop, stage completion, model-owned labels, fresh outputs (audit S8, S9, S10, S12, U4)

**Files:**
- Create: `hornflow/workflow/decisions.py`
- Modify: `hornflow/app/view.py:254-300` (stage completion), `:701-731` (`_outcome`, `_decided`), `:785`, `:840-842`
- Modify: `hornflow/app/actions.py` (`decision`, `import_vips`): re-emit after write
- Modify: `hornflow/workflow/bem_import.py` (re-emit and regenerate `report.md` at the end of `import_into_run`)
- Modify: `hornflow/viz/viewer/ui/app.js:430-465` (import result and outcome rendering), `:987`, `:1091-1099` (`applyView` reloads the scene when `view.run.run_id` changes)
- Test: `tests/test_app_view.py`, `tests/test_app_api.py`, `tests/test_workflow_ui.py`

**Interfaces:**
- Produces in `workflow/decisions.py`:
  - `DECISION_KINDS = {"accept_unvalidated", "accept_validated", "reject_design"}`.
  - `allowed_decisions(bem_state: str | None) -> set[str]`:
    - `BEM_VALIDATED` → `{"accept_validated", "reject_design"}`;
    - `BEM_REJECTED`, `GUI_REQUIRED`, `MANUAL_SOLVE_PENDING` → `{"accept_unvalidated", "reject_design"}`;
    - `None` (no BEM) → `{"accept_unvalidated", "reject_design"}`.
  - `is_decided(state) -> bool`: true when the last entry with `event == "decision"` is not superseded.
- Every decision entry is written with `event: "decision"` and `kind: <kind>`. A later import that changes the BEM state appends `{"event": "decision_superseded", "by": "bem_import"}` and sets the previous decision's `superseded: true`.
- `view.outcome` gains `label: str`, `tone: "ok" | "warn" | "bad"` and `allowed_decisions: list[str]`. `app.js` renders `label` and `tone` and the buttons from `allowed_decisions` only. It never derives a verdict.
- Stage completion:
  - `final_decision` is complete only when `is_decided(state)`.
  - `verification_bem` with `BEM_REJECTED` has status `closed_rejected` (a new status string the view renders as "Closed: rejected").
  - `percent` counts `skipped` and `closed_rejected` as done.
- After `import_into_run` and `decision`, call `emit_ui_for_run(run_dir, host="static")` and regenerate `deliverables/report.md` through `reporting.markdown`.

- [ ] **Step 1: Write the failing tests:**

```python
def test_rejected_import_is_labelled_rejected(project):
    a = _actions(project); copy_exports(a.run_dir)
    out = a.import_vips(run_id=a.run_dir.name, tolerance_db=6.0)
    assert out["state"] == "BEM_REJECTED"
    assert out["view"]["outcome"]["label"].startswith("BEM rejected")
    assert set(out["view"]["outcome"]["allowed_decisions"]) == {"accept_unvalidated", "reject_design"}

def test_decision_completes_final_stage_and_survives_reemit(project):
    a = _actions(project)
    a.decision(run_id=a.run_dir.name, kind="accept_unvalidated", reason=ACCEPT_REASONS[0])
    v = a.view()
    assert v["mode"] == "decided"
    assert _stage(v, "final_decision")["status"] == "complete"
    snap = json.loads((a.run_dir / "deliverables/viewer/app_view.json").read_text())
    assert snap["mode"] == "decided"

def test_validated_run_offers_accept_validated(project):
    a = _actions(project); copy_exports(a.run_dir)
    a.import_vips(run_id=a.run_dir.name, tolerance_db=12.0)
    assert "accept_validated" in a.view()["outcome"]["allowed_decisions"]
    a.decision(run_id=a.run_dir.name, kind="accept_validated")
    assert a.view()["mode"] == "decided"

def test_ui_never_reads_verdict_field():
    js = Path("hornflow/viz/viewer/ui/app.js").read_text()
    assert ".verdict" not in js and "'Imported and compared: BEM_VALIDATED'" not in js
```

- [ ] **Step 2: Run.** Expected: FAIL.
- [ ] **Step 3: Implement** as specified. Update `docs/app-local-multitab.md` §14 to §17 to match.
- [ ] **Step 4: Run** the full suite, including the Chrome DOM tests in `tests/test_workflow_ui.py` if Chrome is available. Otherwise record "skipped: no Chrome" in the PR text.
- [ ] **Step 5: Commit** `fix(app): one decision model; model-owned outcome labels; outputs re-emitted after changes (S8 to S10, S12, U4)`.

### Task 15: Owner decisions D1, D2, D4 (needs-decision)

**Files:**
- Modify: `docs/superpowers/specs/2026-11-26-hornflow-roadmap-design.md` (Open decisions → Decided)
- Modify, only if the answers differ from the placeholders: `hornflow/physics/solvers/bem_manual.py` (`TOLERANCE_RANGE_DB`, `DEFAULT_TOLERANCE_DB`), `hornflow/architecture/registry.py` (`PREFERENCE_BONUS`, `TIE_TOLERANCE_POINTS`), `hornflow/workflow/gates.py:30-53`

**Interfaces:**
- Produces, for D2: `simulation.gate_voltage: float | None` in `config.Simulation` (default `None`, meaning `simulation.voltage`) and `simulation.gate_band: "passband" | "full"` (default `"passband"`).
  - `gates.py` evaluates `excursion<=Xmax` at `gate_voltage` (excursion scales linearly with voltage in this linear model: `x * gate_voltage / voltage`), over the chosen band.
  - It routes through `domain.excursion.excursion_gate`, removing the duplicate logic (audit P9).
  - `GateResult` gains `measurement: dict` (keys `drive_vrms`, `band`, `peak_mm`, `xmax_one_way_peak_mm`).
  - The pipeline persists gates as `state.validation["gates"] = [g.to_dict() for g in self.gates]`; today they are not stored in `state.json` at all.

- [ ] **Step 1:** Run `superpowers:brainstorming` with the owner on D1, D2 and D4. Record the answers in the spec.
- [ ] **Step 2: Write the failing test:**

```python
def test_gate_uses_gate_voltage(tmp_path):
    p = _copy_def(tmp_path, _set("simulation.gate_voltage", 40.0))
    s = run_pipeline(p, out_root=tmp_path / "runs")
    st = load_state_file(Path(s["run_dir"]) / "state.json")
    g = {x["name"]: x for x in st.validation["gates"]}["excursion<=Xmax"]
    assert g["measurement"]["drive_vrms"] == 40.0
    assert g["measurement"]["band"] == "passband"
```

- [ ] **Step 3: Run.** Expected: FAIL.
- [ ] **Step 4: Implement** the gate change and the decided constants.
- [ ] **Step 5: Run** the full suite. Expected: pass. Then commit `feat(gates): safety gate at the decided drive level and band (P8, D1, D2, D4)`.

### Task 16: Phase close

- [ ] **Step 1:** `superpowers:verification-before-completion`. Run `python3 tests/test_theory.py && python3 -m pytest tests -q && python3 run_pipeline.py params/horn_jbl_1200b.yaml --out /tmp/p0-runs`. Paste the output into the PR.
- [ ] **Step 2:** `superpowers:requesting-code-review` on the whole branch. The reviewer gets the audit IDs S1 to S12, B1 to B5, P1 to P12, U1, U2, U4, T1 and T2, and checks each one off as fixed or deferred, with a reason.
- [ ] **Step 3:** Update `docs/adr.md` (ADR-0003, ADR-0005 amended) and `docs/migration-notes.md` (schema 1.2).
- [ ] **Step 4:** `superpowers:finishing-a-development-branch`. Open the PR with `.github/pull_request_template.md`, and link the audit.
