"""Resume a run at the manual BEM stage (state-driven ``--bem-import``).

Validates the exported ``.vips`` spectra, compares them with the run's own
one-dimensional reference, advances the manual-solve state machine legally and
writes the result back into ``state.json``.  This is the only path that can move
a candidate to ``BEM_VALIDATED``.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime
from pathlib import Path

import numpy as np

from .. import bem as _bem
from ..domain.evidence import now_utc
from ..io.artifacts import atomic_write, sha256_file
from ..io.state_store import load_state_file, run_params, update_state
from ..physics.solvers import bem_manual
from ..physics.solvers import manual as manual_mod


class _Design:
    def __init__(self, fc: float) -> None:
        self.fc = float(fc)


class _Reference:
    """Minimal stand-in for ``response.Result`` (what the comparators need)."""

    def __init__(self, f, spl, fc: float) -> None:
        self.f = np.asarray(f, dtype=float)
        self.spl = np.asarray(spl, dtype=float)
        self.design = _Design(fc)


def reference_from_state(state) -> _Reference | None:
    """Rebuild the 1-D reference curve recorded in the run state."""
    runs = state.simulation_runs or []
    if not runs:
        return None
    r = runs[0]
    f = r.get("frequency_hz")
    spl = r.get("spl_db")
    if f is None or spl is None:
        return None
    fc = float((state.constraints.get("acoustic") or {}).get("f_low_hz")
               or np.asarray(f, dtype=float)[0])
    return _Reference(f, spl, fc)


def _route(current: str, target: str):
    """Shortest list of states from ``current`` to ``target``, or ``None``.

    Breadth-first over ``manual_mod.ALLOWED_TRANSITIONS``, so the answer is the
    shortest legal route.  Both ends must be states the machine knows: an
    unknown stored state is an error, never a silent coercion.
    """
    current, target = str(current), str(target)
    for value in (current, target):
        if value not in manual_mod.ALLOWED_TRANSITIONS:
            raise ValueError(
                f"unknown manual-solve state {value!r}; "
                f"known states: {sorted(manual_mod.ALLOWED_TRANSITIONS)}")
    if current == target:
        return []
    came_from: dict = {current: None}
    q = deque([current])
    while q:
        node = q.popleft()
        for nxt in manual_mod.ALLOWED_TRANSITIONS.get(node, ()):
            if nxt in came_from:
                continue
            came_from[nxt] = node
            if nxt == target:
                route = []
                step = target
                while step is not None:          # walk back to the start
                    route.append(step)
                    step = came_from[step]
                route.pop()                      # `current` itself is not a step
                return list(reversed(route))
            q.append(nxt)
    return None


def _path_to(current: str, target: str) -> list[str]:
    """The shortest legal route, refusing an unknown state or an unreachable target.

    ``target`` unreachable used to be answered with ``current``, which made a
    rejected verdict and a silent no-op look identical (audit B2).
    """
    route = _route(current, target)
    if route is None:
        raise ValueError(f"no legal route from manual-solve state {current!r} "
                         f"to {target!r}")
    return route


def _advance_along(current: str, path: list[str]) -> str:
    """Apply a route one legal step at a time (``manual.advance`` refuses a jump)."""
    for step in path:
        current = manual_mod.advance(current, step)
    return str(current)


def _bem_status(state: str) -> str:
    """The run-level BEM status implied by a manual-solve state."""
    if state == manual_mod.ManualSolveState.BEM_VALIDATED.value:
        return "validated"
    if state == manual_mod.ManualSolveState.BEM_ACCEPTED_WITH_TOLERANCE.value:
        return "accepted_with_tolerance"
    if state == manual_mod.ManualSolveState.BEM_REJECTED.value:
        return "rejected"
    return "pending_external"


def _export_hashes(folder) -> dict:
    """SHA-256 of every file this attempt read, keyed by its path in ``folder``.

    ``candidate_files`` walks the folder recursively, so the key keeps the
    relative path: the validator's ``files`` list holds base names only, and a
    nested export would otherwise fingerprint as ``{}`` (review of #11).
    """
    folder = Path(folder)
    out: dict = {}
    for p in _bem.candidate_files(folder):
        try:
            key = p.relative_to(folder).as_posix()
        except ValueError:                      # a symlink outside the folder
            key = p.name
        try:
            out[key] = sha256_file(p)
        except OSError:
            continue
    return out


def _stamp(utc) -> str:
    """A filesystem-safe, sortable stamp from an ISO UTC time."""
    try:
        return datetime.fromisoformat(str(utc)).strftime("%Y%m%dT%H%M%SZ")
    except ValueError:
        return "attempt"


def find_run_dir(folder) -> "Path | None":
    """Locate the run directory that owns ``folder`` (an ancestor with a state.json)."""
    from pathlib import Path
    p = Path(folder).resolve()
    for parent in [p, *p.parents]:
        if (parent / "state.json").is_file():
            return parent
    return None


def import_into_run(run_dir, folder, *, tolerance_db: float | None = None,
                    out_subdir: str = "bem") -> dict:
    """Validate + compare an export folder against an existing run directory.

    ``tolerance_db=None`` means "the manifest's tolerance, else the default".
    A tolerance above the default accepts a result only as
    ``BEM_ACCEPTED_WITH_TOLERANCE`` (decision D1).

    ``validation.bem_manual.state``, ``checks`` and ``metrics`` always describe
    the last **accepted** import.  A failed attempt appends one entry to
    ``validation.bem_manual.attempts`` and changes nothing else, so a junk or
    stale re-import can never overwrite a verdict (audit B2).  The ``state``
    returned here is the outcome of *this* attempt.
    """
    run_dir = Path(run_dir)
    state = load_state_file(run_dir / "state.json")
    stored = dict(state.validation.get("bem_manual") or {})
    current = str(stored.get("state") or manual_mod.ManualSolveState.GUI_REQUIRED.value)
    # Refuse an unknown stored state before reading the export or writing a file.
    _path_to(current, current)

    # The definition this run was started from, from the run's own snapshot
    # (audit S7): editing the file it was created from cannot change the import.
    params = run_params(run_dir, state)
    bem_dir = run_dir / "deliverables" / out_subdir
    manifest = manual_mod.read_manifest(bem_dir / manual_mod.MANIFEST_NAME,
                                        base=run_dir)
    tolerance_db = bem_manual.resolve_tolerance(tolerance_db, manifest)
    reference = reference_from_state(state)
    if reference is None:
        raise ValueError("the run state has no one-dimensional reference to compare against")

    result = bem_manual.import_and_validate(params, reference, folder, bem_dir,
                                            manifest=manifest, tolerance_db=tolerance_db)
    validation = result["validation"]
    accepted = bool(validation["passed"])
    target = str(result["state"])
    run_id = state.run.get("run_id", "")
    attempt = {
        "utc": now_utc(),
        "passed": accepted,
        "checks": validation["checks"],
        "metrics": result.get("metrics"),
        "tolerance_db": float(tolerance_db),
        "files_sha256": _export_hashes(folder),
    }

    def apply(st):
        """Record the attempt, and write its report inside the state update."""
        rec = dict(st.validation.get("bem_manual") or {})
        held = str(rec.get("state") or manual_mod.ManualSolveState.GUI_REQUIRED.value)
        if accepted:
            held = _advance_along(held, _path_to(held, target))
            rec.update({
                "state": held,
                "validation_passed": True,
                "validation": validation,
                "checks": validation["checks"],
                "warnings": validation["warnings"],
                "source": validation["source"],
                "tolerance_db": float(tolerance_db),
                "imported_utc": attempt["utc"],
                "metrics": result.get("metrics"),
            })
        # This attempt's own answer.  A failed validation only says "re-export
        # and retry" where that step is still legal; a decided verdict stays put.
        outcome = held
        if not accepted:
            route = _route(held, manual_mod.ManualSolveState.MANUAL_SOLVE_PENDING.value)
            if route:
                outcome = _advance_along(held, route)
        history = list(rec.get("attempts") or [])
        index = len(history) + 1
        stamp = _stamp(attempt["utc"])
        result["state"] = outcome
        text = bem_manual.validation_md(result, project=params.project,
                                        run_id=run_id, stored_state=held)
        if accepted:
            # the accepted report is replaced, and archived so an older attempt
            # link stays valid
            shown = bem_dir / "bem_manual_report.md"
            archive = bem_dir / "attempts" / f"{stamp}-{index}.md"
            atomic_write(archive, text.encode("utf-8"))
            atomic_write(shown, text.encode("utf-8"))
        else:
            # a failed attempt never touches the accepted report
            shown = archive = bem_dir / "attempts" / f"{stamp}-failed-{index}.md"
            atomic_write(shown, text.encode("utf-8"))
        history.append({**attempt, "state_after": held,
                        "report": shown.relative_to(run_dir).as_posix(),
                        "archive": archive.relative_to(run_dir).as_posix()})
        rec["attempts"] = history
        st.validation["bem_manual"] = rec
        st.validation["bem_status"] = _bem_status(held)
        # The pin goes to this run's manifest, only on an acceptance, and here.
        # Only this attempt's verdict may pin (review of #12, item 4).  ``held``
        # is the last accepted state, so passing it would let a failed re-import
        # pin a run that had no pin yet; ``accepted`` only says the export
        # passed the structural checks, not that the comparison accepted.
        pin_state = target if target in bem_manual.PINNING_STATES else None
        bem_manual.pin_graph_group(manifest, bem_dir / manual_mod.MANIFEST_NAME,
                                   validation, pin_state)
        st.log("THREE_DIMENSIONAL_VERIFICATION", "bem_import", state=held,
               attempt_state=outcome, passed=accepted,
               source=validation["source"], metrics=result.get("metrics"))
        return {"held": held, "outcome": outcome, "report": shown}

    applied = update_state(run_dir / "state.json", apply)
    result["state"] = applied["outcome"]
    result["stored_state"] = applied["held"]
    result["attempt_passed"] = accepted
    result["report"] = str(applied["report"])
    return result
