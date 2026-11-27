"""The app's mutating actions - pure Python, no HTTP.

Every action here is a thin, typed call into an existing HornFlow function:
`run_pipeline()`, `bem_import.import_into_run()`, the brief store, and the state
store.  The HTTP layer only routes and serialises, so the whole action surface is
unit-testable without a socket.

Two invariants:

* an API request may name a *definition*, a *run id* or an export *sub-directory*
  - never a filesystem path.  Every name is resolved through `_safe_under()`,
  which refuses anything that escapes its root;
* the brief never writes `state.json`.  Only the pipeline and an explicit decision
  (`decision_log`) write run state, and both do it through the state store.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import threading
from pathlib import Path

from ..io.state_store import load_state_file, update_state
from . import view as _view
from .brief import BriefStore

# what the run-progress panel may show from logs.jsonl
LOG_TAIL = 40


class ApiError(Exception):
    """A structured failure the HTTP layer turns into a JSON error, never a 500."""

    def __init__(self, code: str, message: str, *, status: int = 400, **extra):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.extra = extra

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message,
                          **self.extra}}


def safe_under(root: Path, *parts) -> Path:
    """Resolve ``parts`` under ``root``, refusing traversal and absolute names."""
    root = Path(root).resolve()
    for part in parts:
        if part in (None, ""):
            continue
        p = Path(str(part))
        if p.is_absolute() or ".." in p.parts or "~" in str(part):
            raise ApiError("path_rejected",
                           f"{part!r} is not an allowed relative name", status=400)
    cand = (root.joinpath(*[str(p) for p in parts if p not in (None, "")])
            .resolve())
    if cand != root and root not in cand.parents:
        raise ApiError("path_rejected", "the resolved path escapes its root")
    return cand


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


class _StateUnreadable(Exception):
    """``state.json`` exists but cannot be loaded.

    Absent means a first run; unreadable means a broken run.  Treating the two
    the same is how a corrupted run silently looked brand new (audit S2).
    """


class AppActions:
    """The action surface behind the local host."""

    def __init__(self, project_root=".", *, run_root="runs", base_definition=None,
                 definitions_dir=None, run_dir=None, author=None, runner=None):
        self.root = Path(project_root).resolve()
        self.run_root = (Path(run_root) if Path(run_root).is_absolute()
                         else self.root / run_root).resolve()
        self.run_root.mkdir(parents=True, exist_ok=True)
        self.brief = BriefStore(self.root, base_definition, definitions_dir)
        self.author = author
        self.run_dir = Path(run_dir).resolve() if run_dir else None
        self._runner = runner or _run_pipeline
        self._lock = threading.Lock()
        self._run: dict = {"state": "idle", "run_id": None, "stage": None,
                           "started_utc": None, "finished_utc": None,
                           "error": None, "definition": None, "messages": []}
        if self.run_dir is None:
            self.run_dir = self._newest_run()

    # ------------------------------------------------------------------ runs
    def _newest_run(self):
        cands = [p for p in self.run_root.iterdir()
                 if p.is_dir() and (p / "state.json").is_file()]
        return max(cands, key=lambda p: p.name) if cands else None

    def runs(self) -> list:
        out = []
        for p in sorted(self.run_root.iterdir(), key=lambda q: q.name, reverse=True):
            if p.is_dir() and (p / "state.json").is_file():
                out.append({"run_id": p.name, "path": str(p.relative_to(self.root))})
        return out

    def select_run(self, run_id) -> dict:
        d = safe_under(self.run_root, run_id)
        if not (d / "state.json").is_file():
            raise ApiError("no_such_run", f"no run {run_id!r}", status=404)
        self.run_dir = d
        return {"run_id": d.name}

    def _state(self):
        if self.run_dir is None:
            return None
        path = self.run_dir / "state.json"
        if not path.is_file():
            return None
        try:
            return load_state_file(path)
        except Exception as exc:              # noqa: BLE001 - it must be visible
            raise _StateUnreadable(
                f"{path.name} in run {self.run_dir.name!r} cannot be read: "
                f"{exc}") from exc

    def _require_run(self, run_id) -> Path:
        """The run this mutating call is for, or a structured refusal.

        A tab can be showing run X while the server has moved to Y.  Every
        mutating call names its run so that write can never land in Y (audit S1).
        """
        if run_id in (None, ""):
            raise ApiError("run_id_required",
                           "name the run this call is for; the host may have "
                           "switched to another one", status=400)
        if self.run_dir is None:
            raise ApiError("no_run", "there is no run to act on", status=409)
        got = str(run_id)
        if got != self.run_dir.name:
            raise ApiError("run_mismatch",
                           f"this call names run {got!r} but the host is on "
                           f"{self.run_dir.name!r}; reload the page",
                           status=409, expected=self.run_dir.name, got=got)
        return self.run_dir

    # ------------------------------------------------------------------ view
    def view(self) -> dict:
        draft = self.brief.draft()
        unreadable = None
        try:
            state = self._state()
        except _StateUnreadable as exc:
            # Keep going: the page needs the whole shell, not only an error.
            state, unreadable = None, str(exc)
        logs = self._logs()
        v = _view.build_view(state if state is not None else {},
                             run_dir=self.run_dir, brief=draft["values"],
                             host="local", logs=logs)
        v["live"] = self.progress()
        v["definitions"] = self.brief.definitions()
        v["runs"] = self.runs()
        v["brief_draft"] = draft
        # The frozen brief is the authority for the revision and its hash.  The
        # pipeline does not write them into state.json, so without this the
        # summary would always show a blank revision.
        if draft["revision"] is not None:
            v["current_state"]["brief_revision"] = draft["revision"]
            v["current_state"]["input_hash"] = draft["input_hash"]
        v["brief_actions"] = _view.brief_actions_for(
            v["completion"], editable=True,
            changed=bool(draft["values"]) and not self._frozen_matches(draft))
        if state is not None:
            v["project"]["name"] = ((state.project or {}).get("name")
                                    or v["project"]["name"])
        if unreadable is not None:
            v = self._state_error_view(v, unreadable)
        return v

    def _state_error_view(self, v: dict, message: str) -> dict:
        """Turn a normal view into the "state cannot be read" view.

        The shape is the one ``build_view`` produced, never a hand-built dict:
        the page draws its shell only from a view that carries ``view_schema``
        and the keys the view model always has, so a missing key made app.js
        fall back to ``viewerOnly()``, which removes the tabs and never renders
        the message (review of HORN-17).

        It keeps the shell (tabs, definitions, run list), never falls back to
        the first-run view, and never offers to act on the run.
        """
        v["mode"] = "state_error"
        v["error"] = {"code": "state_unreadable", "message": message}
        v["next_action"] = None
        v["outcome"] = {}
        v["current_state"] = {}
        v["completion"] = {}
        v["brief_actions"] = {}
        v["run"] = {"run_id": (self.run_dir.name if self.run_dir else None)}
        return v

    def _frozen_matches(self, draft: dict) -> bool:
        frozen = self.brief._read_yaml(self.brief.dir / "brief.yaml")  # noqa: SLF001
        if not frozen:
            return False
        return (frozen.get("input_hash") or "") == _values_hash(draft["values"])

    def _logs(self) -> dict:
        if self.run_dir is None:
            return {}
        path = self.run_dir / "logs.jsonl"
        if not path.is_file():
            return {}
        return _view._read_logs(self.run_dir)          # noqa: SLF001 - same module family

    # ------------------------------------------------------------- the brief
    def save_draft(self, values: dict) -> dict:
        out = self.brief.save_draft(values)
        out["view"] = self.view()
        return out

    def freeze(self, values: dict) -> dict:
        """Freeze only when the model says every hard-required answer is present."""
        check = _view.build_view(self._state() or {}, run_dir=self.run_dir,
                                brief=values or {}, host="local")
        completion = check["completion"]
        if not completion["complete"]:
            return {"ok": False, "field_errors": {
                "_completion": f"{completion['blocker_count']} required answer(s) "
                               f"still missing"},
                "warnings": [], "view": self.view()}
        out = self.brief.freeze(values or {}, author=self.author)
        out["view"] = self.view()
        return out

    # --------------------------------------------------------------- the run
    def start_run(self, definition=None, *, wait=False) -> dict:
        if not self._lock.acquire(blocking=False):
            raise ApiError("run_in_progress",
                           "a run is already in flight", status=409)
        try:
            if self._run.get("state") == "running":
                raise ApiError("run_in_progress", "a run is already in flight",
                               status=409)
            path = self._definition_path(definition)
            limits = self._limits_for(path)
            self._run.update({"state": "running", "run_id": None, "stage": None,
                              "started_utc": _now(), "finished_utc": None,
                              "error": None, "definition": str(path.relative_to(self.root)),
                              "messages": [], "limits": limits})
        finally:
            self._lock.release()

        def work():
            try:
                summary = self._runner(path, self.run_root, limits,
                                       self._note_progress)
                with self._lock:
                    self._run.update({"state": "done", "run_id": summary.get("run_id"),
                                      "finished_utc": _now()})
                self._adopt_run(summary.get("run_id"))
            except Exception as exc:               # noqa: BLE001 - reported, not raised
                with self._lock:
                    self._run.update({"state": "failed", "error": str(exc),
                                      "finished_utc": _now()})

        if wait:
            work()
        else:
            threading.Thread(target=work, name="hornflow-run", daemon=True).start()
        return self.progress()

    def _note_progress(self, message: str) -> None:
        with self._lock:
            self._run["stage"] = str(message).strip("[]")
            self._run["messages"] = (self._run["messages"] + [str(message)])[-LOG_TAIL:]

    def _adopt_run(self, run_id) -> None:
        """Point at the new run only if it really exists.

        A runner that fails early (or a fake one) leaves no state.json; adopting
        it anyway would send every later request to a directory that is not there.
        """
        if not run_id:
            return
        try:
            cand = safe_under(self.run_root, run_id)
        except ApiError:
            return
        if (cand / "state.json").is_file():
            self.run_dir = cand

    def _definition_path(self, definition) -> Path:
        """A run may use a frozen definition or any definition in the allow-list."""
        allowed = {d["name"]: d for d in self.brief.definitions()}
        if definition in (None, "", "frozen"):
            frozen = self.brief._read_yaml(self.brief.dir / "brief.yaml")  # noqa: SLF001
            if not frozen.get("definition"):
                raise ApiError("no_frozen_brief",
                               "no frozen brief yet - freeze one first", status=409)
            return safe_under(self.root, frozen["definition"])
        if definition not in allowed:
            raise ApiError("unknown_definition",
                           f"{definition!r} is not one of the available definitions")
        return safe_under(self.root, allowed[definition]["path"])

    def _limits_for(self, path: Path) -> dict:
        try:
            import yaml

            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            limits = dict((raw.get("brief") or {}).get("limits") or {})
        except Exception:                          # noqa: BLE001
            limits = {}
        limits.setdefault("wall_mm", 18.0)
        return limits

    # ------------------------------------------------------------- progress
    def progress(self) -> dict:
        """Structured progress: the run lock plus the authoritative stage state.

        The browser never parses ``logs.jsonl``; everything it shows is assembled
        here from the pipeline's own callback and from ``state.json``.
        """
        with self._lock:
            live = dict(self._run)
        messages = list(live.pop("messages", None) or [])
        stages = []
        total = passed = 0
        if self.run_dir is not None:
            try:
                st = self._state()
            except _StateUnreadable:
                st = None
            if st is not None:
                for name, rec in (st.stages or {}).items():
                    status = str((rec or {}).get("status", "pending"))
                    stages.append({"stage": name, "status": status,
                                   "detail": str((rec or {}).get("detail", "") or "")})
                total = len(stages)
                passed = sum(1 for s in stages if s["status"] == "passed")
        return {
            "state": live.get("state"),
            "run_id": live.get("run_id"),
            "stage": live.get("stage"),
            "definition": live.get("definition"),
            "limits": live.get("limits") or {},
            "started_utc": live.get("started_utc"),
            "finished_utc": live.get("finished_utc"),
            "error": live.get("error"),
            "messages": messages,
            "stages": stages,
            "stages_total": total,
            "stages_passed": passed,
            "percent": (round(100.0 * passed / total) if total else 0),
            "run_dir": (str(self.run_dir.relative_to(self.root))
                        if self.run_dir else None),
        }

    # --------------------------------------------------------------- import
    def import_vips(self, *, run_id, subdir=None, tolerance_db=None) -> dict:
        """Validate + compare a ``.vips`` export.  The folder is never a path.

        ``tolerance_db=None`` means the manifest's tolerance, then the default;
        anything outside ``bem_manual.TOLERANCE_RANGE_DB`` is refused here, so a
        typo never reaches the comparison (decision D1).
        """
        run_dir = self._require_run(run_id)
        from ..physics.solvers import bem_manual
        from ..workflow import bem_import

        if tolerance_db is not None:
            try:
                tolerance_db = bem_manual.check_tolerance(tolerance_db)
            except (TypeError, ValueError) as exc:
                raise ApiError("tolerance_out_of_range", str(exc), status=400) from None
        bem_dir = run_dir / "deliverables" / "bem"
        folder = safe_under(bem_dir, subdir or "export")
        if not folder.is_dir():
            raise ApiError(
                "no_export_folder",
                "the export folder does not exist yet - do the GUI solve, export "
                "the .vips spectra into deliverables/bem/export, then import",
                status=409)
        result = bem_import.import_into_run(run_dir, folder, tolerance_db=tolerance_db)
        return {"ok": bool((result.get("validation") or {}).get("passed")),
                "state": result.get("state"),
                "stored_state": result.get("stored_state"),
                "attempt_passed": result.get("attempt_passed"),
                "validation": result.get("validation"),
                "report": result.get("report"),
                "tolerance_db": (result.get("validation") or {}).get("tolerance_db"),
                "view": self.view()}

    # ------------------------------------------------------------- decision
    def decision(self, *, run_id, kind, reason=None, note="", actor=None,
                 now=None) -> dict:
        """Record a structured decision.  Never changes a measured BEM result."""
        run_dir = self._require_run(run_id)
        if kind != "accept_unvalidated":
            raise ApiError("unknown_decision", f"unknown decision {kind!r}")
        if reason not in ACCEPT_REASONS:
            raise ApiError("reason_required", "choose one of the listed reasons",
                           allowed=list(ACCEPT_REASONS))
        if reason == "Other" and not str(note or "").strip():
            raise ApiError("note_required", "'Other' needs a note")

        def apply(st):
            bem = (st.validation or {}).get("bem_manual") or {}
            if bem.get("state") == "BEM_VALIDATED":
                raise ApiError("already_validated",
                               "this candidate is BEM_VALIDATED; acceptance is "
                               "not needed", status=409)
            entry = {
                "utc": now or _now(), "stage": "FINAL_DECISION",
                "event": "accept_unvalidated", "kind": kind, "reason": reason,
                "note": str(note or "").strip(), "actor": actor or self.author or "",
                "bem_state": bem.get("state"),
                "bem_status": (st.validation or {}).get("bem_status"),
                "tolerance_db": bem.get("tolerance_db"),
                "result_hash": _hash_json({"checks": bem.get("checks"),
                                           "metrics": bem.get("metrics")}),
                "effect": "the acoustic result stays unvalidated",
            }
            st.decision_log.append(entry)
            st.validation.setdefault("decisions", []).append(entry)
            st.validation["accepted_unvalidated"] = True
            return entry

        entry = update_state(run_dir / "state.json", apply)
        return {"ok": True, "decision": entry, "view": self.view()}


# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #
ACCEPT_REASONS = _view.ACCEPT_REASONS


def _hash_json(obj) -> str:
    from ..domain.ids import canonical_json

    return hashlib.sha256(canonical_json(obj).encode("utf-8")).hexdigest()


def _values_hash(values) -> str:
    return _hash_json({k: v for k, v in sorted((values or {}).items())})


def _run_pipeline(path, out_root, limits, progress):
    """The real runner: the existing pipeline entry point, in-process."""
    from ..workflow import run_pipeline

    return run_pipeline(path, out_root=str(out_root), limits=limits,
                        progress=progress)



