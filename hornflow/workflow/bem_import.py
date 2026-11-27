"""Resume a run at the manual BEM stage (state-driven ``--bem-import``).

Validates the exported ``.vips`` spectra, compares them with the run's own
one-dimensional reference, advances the manual-solve state machine legally and
writes the result back into ``state.json``.  This is the only path that can move
a candidate to ``BEM_VALIDATED``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .. import config
from ..domain.evidence import now_utc
from ..io.state_store import load_state_file, update_state
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


def _walk_to(current: str, target: str) -> str:
    """Advance along the legal transition graph, returning ``target`` when reachable."""
    from collections import deque
    chain = list(manual_mod.STATE_CHAIN) + [manual_mod.ManualSolveState.BEM_REJECTED.value]
    if current not in chain:
        current = manual_mod.ManualSolveState.MANUAL_SOLVE_PENDING.value
    if current == target:
        return current
    seen = {current}
    q = deque([current])
    while q:
        node = q.popleft()
        for nxt in manual_mod.ALLOWED_TRANSITIONS.get(node, ()):
            if nxt == target:
                return nxt
            if nxt not in seen:
                seen.add(nxt)
                q.append(nxt)
    return current


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
    """
    run_dir = Path(run_dir)
    state = load_state_file(run_dir / "state.json")
    params = config.load(state.run.get("input_path") or state.project.get("input_path", ""))
    bem_dir = run_dir / "deliverables" / out_subdir
    manifest = manual_mod.read_manifest(bem_dir / manual_mod.MANIFEST_NAME)
    tolerance_db = bem_manual.resolve_tolerance(tolerance_db, manifest)
    reference = reference_from_state(state)
    if reference is None:
        raise ValueError("the run state has no one-dimensional reference to compare against")

    result = bem_manual.import_and_validate(params, reference, folder, bem_dir,
                                            manifest=manifest, tolerance_db=tolerance_db)
    validation = result["validation"]
    accepted = bool(validation["passed"])
    target = str(result["state"])

    def apply(st):
        """Record the import; the graph-group pin happens inside this update."""
        rec = dict(st.validation.get("bem_manual") or {})
        held = str(rec.get("state") or manual_mod.ManualSolveState.GUI_REQUIRED.value)
        if accepted:
            steps = [manual_mod.ManualSolveState.VIPS_IMPORTED.value,
                     manual_mod.ManualSolveState.BEM_COMPARISON_COMPLETED.value,
                     target]
            for t in steps:
                held = _walk_to(held, t)
        else:
            # validation failed -> stay where we are; the human re-exports.
            held = _walk_to(held, manual_mod.ManualSolveState.MANUAL_SOLVE_PENDING.value)
        rec.update({
            "state": held,
            "validation_passed": accepted,
            "validation": validation,
            "checks": validation["checks"],
            "warnings": validation["warnings"],
            "source": validation["source"],
            "tolerance_db": float(tolerance_db),
            "imported_utc": now_utc(),
            "metrics": result.get("metrics"),
        })
        st.validation["bem_manual"] = rec
        st.validation["bem_status"] = (
            "validated" if held == manual_mod.ManualSolveState.BEM_VALIDATED.value else
            "accepted_with_tolerance"
            if held == manual_mod.ManualSolveState.BEM_ACCEPTED_WITH_TOLERANCE.value else
            "rejected" if held == manual_mod.ManualSolveState.BEM_REJECTED.value else
            "pending_external")
        # The pin goes to the manifest of THIS run, and only on an acceptance.
        bem_manual.pin_graph_group(manifest, bem_dir / manual_mod.MANIFEST_NAME,
                                   validation, held)
        st.log("THREE_DIMENSIONAL_VERIFICATION", "bem_import",
               state=held, source=validation["source"],
               metrics=result.get("metrics"))
        return held

    current = update_state(run_dir / "state.json", apply)
    report = bem_manual.validation_md(result, project=params.project,
                                      run_id=state.run.get("run_id", ""))
    (bem_dir / "bem_manual_report.md").write_text(report, encoding="utf-8")
    result["state"] = current
    result["report"] = str(bem_dir / "bem_manual_report.md")
    return result
