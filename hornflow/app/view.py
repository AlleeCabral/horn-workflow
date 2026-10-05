"""M1 - the app view model: `app_view.json`.

HornFlow stays authoritative.  This module is the **single translation point**
from the authoritative run artifacts (`state.json`, `logs.jsonl`, the BEM
manifest, the export folder, `deliverables/`) to the read-only model the UI
renders.  The UI never reads `state.json` and never computes anything.

Determinism: `to_json()` sorts keys and every timestamp is injectable (`now=`),
so the same state always produces byte-identical output - which is what the
golden tests assert.

Explicit assumption (M1-M3): the per-value `status`/`provenance` audit is not yet
stored in `state.json` (the orchestrator's `Constraint` list is report-only), so
a value that *resolves* from the run state is labelled
`status=FIXED, provenance=USER_INPUT, confidence=1.0` and a value that does not
is `status=UNKNOWN`.  The brief editor (M4) will carry the real provenance.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..domain.evidence import now_utc
from ..io.artifacts import atomic_write, sha256_file
from ..workflow.stages import (OPTIONAL_STAGES, STAGE_ORDER, Stage,
                               prerequisites)

VIEW_SCHEMA = "1.2"

# The eight manual-solve states, in order (the authoritative definition lives in
# hornflow.physics.solvers.manual; repeated here only as a display order).
BEM_STATES = (
    "INPUTS_GENERATED", "GUI_REQUIRED", "MANUAL_SOLVE_PENDING",
    "MANUAL_SOLVE_COMPLETED", "VIPS_IMPORTED", "BEM_COMPARISON_COMPLETED",
    "BEM_VALIDATED", "BEM_REJECTED",
)
BEM_OPEN = ("GUI_REQUIRED", "MANUAL_SOLVE_PENDING", "MANUAL_SOLVE_COMPLETED")
BEM_DECIDED = ("BEM_VALIDATED", "BEM_REJECTED")

# ---------------------------------------------------------------------------
#  the five required first-run questions (docs/app-local-multitab.md §8)
# ---------------------------------------------------------------------------
FIRST_RUN_QUESTIONS = (
    {
        "id": "Q-PRJ-01",
        "prompt": "What is this for, and where will it stand?",
        "wave": "A", "required": True,
        "why": "The boundary condition changes mouth loading and the whole "
               "path-length budget; it is the most common reason a design works "
               "but not in situ.",
        "fields": (
            {"name": "deployment", "type": "text", "unit": "", "enum": None, "path": None},
            {"name": "boundary", "type": "enum", "unit": "",
             "enum": ["free", "wall", "corner"], "path": None},
            {"name": "operating_orientation", "type": "enum", "unit": "",
             "enum": ["upright", "on_side", "inverted"], "path": None},
            {"name": "transport_orientation", "type": "enum", "unit": "",
             "enum": ["upright", "on_side", "any"], "path": None},
        ),
    },
    {
        "id": "Q-DRV-01/02",
        "prompt": "Which driver - and where do its numbers come from?",
        "wave": "A", "required": True,
        "why": "Provenance sets the confidence on every downstream number, and "
               "the T/S set is the model.",
        "fields": (
            {"name": "manufacturer", "type": "text", "unit": "", "enum": None, "path": None},
            {"name": "model", "type": "text", "unit": "", "enum": None,
             "path": "driver.name"},
            {"name": "data_source", "type": "enum", "unit": "",
             "enum": ["measured", "datasheet", "estimated"], "path": None},
            {"name": "ts_set", "type": "text", "unit": "", "enum": None, "path": None},
        ),
    },
    {
        "id": "Q-DRV-04/05+Q-ELE-02",
        "prompt": "Driver limits - Xmax (and its convention), thermal rating, "
                  "amp's minimum safe impedance",
        "wave": "A", "required": True,
        "why": "The only safety-critical questions: without them excursion and "
               "thermal margins are untrustworthy and the impedance gate cannot "
               "be enforced.",
        "fields": (
            {"name": "Xmax", "type": "number", "unit": "mm", "enum": None,
             "path": "driver.Xmax_mm"},
            {"name": "xmax_convention", "type": "enum", "unit": "",
             "enum": ["one-way", "peak-to-peak"], "path": "driver.Xmax_convention"},
            {"name": "thermal_power_w", "type": "number", "unit": "W",
             "enum": None, "path": None},
            {"name": "min_safe_impedance_ohm", "type": "number", "unit": "ohm",
             "enum": None, "path": None},
        ),
    },
    {
        "id": "Q-TGT-01/02",
        "prompt": "Band and SPL target",
        "wave": "A", "required": True,
        "why": "Sets the required path length and mouth area - i.e. whether the "
               "box is physically plausible at all.",
        "fields": (
            {"name": "f_min_hz", "type": "number", "unit": "Hz", "enum": None,
             "path": "constraints.acoustic.f_low_hz"},
            {"name": "f_max_hz", "type": "number", "unit": "Hz", "enum": None,
             "path": "constraints.acoustic.f_high_hz"},
            {"name": "spl_continuous_db", "type": "number", "unit": "dB",
             "enum": None, "path": None},
            {"name": "measurement_distance_m", "type": "number", "unit": "m",
             "enum": None, "path": None},
        ),
    },
    {
        "id": "Q-PHY-01/02+Q-MFG-01",
        "prompt": "Envelope and manufacturing method",
        "wave": "A", "required": True,
        "why": "The hard size gate, the hard mass gate, and the branch that "
               "selects the manufacturing transformer.",
        "fields": (
            {"name": "max_width_mm", "type": "number", "unit": "mm", "enum": None,
             "path": None},
            {"name": "max_height_mm", "type": "number", "unit": "mm", "enum": None,
             "path": None},
            {"name": "max_depth_mm", "type": "number", "unit": "mm", "enum": None,
             "path": "constraints.physical.depth_mm"},
            {"name": "max_external_volume_m3", "type": "number", "unit": "m^3",
             "enum": None, "path": None},
            {"name": "max_mass_kg", "type": "number", "unit": "kg", "enum": None,
             "path": None},
            {"name": "method", "type": "enum", "unit": "",
             "enum": ["print", "plywood", "either"],
             "path": "constraints.manufacturing.method"},
        ),
    },
)



# --------------------------------------------------------------------------- #
#  the accept-as-unvalidated reason list (fixed list, plus Other)
# --------------------------------------------------------------------------- #
ACCEPT_REASONS = (
    "Boundary-condition mismatch is understood but unresolved",
    "AKABAK Free/export limitation",
    "Partial evidence accepted for prototype only",
    "Comparison tolerance intentionally waived",
    "Candidate retained for geometry/manufacturing review only",
    "Other",
)

# ---------------------------------------------------------------------------
#  field presentation + completion metadata
# ---------------------------------------------------------------------------
# The model - not the UI - owns the human labels, the required flags and the
# completion arithmetic, so the browser can never derive "wave A complete" on its
# own (the defect this replaced: W4 said "wave A complete" while five required
# values were blank).  ``key`` keeps the internal name for a developer tooltip.
FIELD_LABELS = {
    "deployment": "What is it for?",
    "boundary": "Where will it stand?",
    "operating_orientation": "Operating orientation",
    "transport_orientation": "Transport orientation",
    "manufacturer": "Driver manufacturer",
    "model": "Driver model",
    "data_source": "Where the numbers come from",
    "ts_set": "Thiele/Small parameter set",
    "Xmax": "Excursion limit (Xmax)",
    "xmax_convention": "Xmax convention",
    "thermal_power_w": "Thermal power rating",
    "min_safe_impedance_ohm": "Amplifier minimum safe impedance",
    "f_min_hz": "Lowest required frequency",
    "f_max_hz": "Highest required frequency",
    "spl_continuous_db": "Continuous SPL target",
    "measurement_distance_m": "Measuring distance",
    "max_width_mm": "Maximum width",
    "max_height_mm": "Maximum height",
    "max_depth_mm": "Maximum depth",
    "max_external_volume_m3": "Maximum external volume",
    "max_mass_kg": "Maximum mass",
    "method": "Manufacturing method",
}

# Fields that never block completion because a required sibling already bounds
# them (W/H/D bound the volume) or because they are genuinely optional.
OPTIONAL_FIELDS = frozenset({"transport_orientation", "max_external_volume_m3"})

FIELD_HELP = {
    "deployment": "One line, e.g. 'club subwoofer in a corner'.",
    "data_source": "Measured beats datasheet beats estimated - it sets the "
                   "confidence of every downstream number.",
    "xmax_convention": "Data sheets usually quote one-way peak. Choose "
                       "peak-to-peak only if the sheet says so.",
    "thermal_power_w": "The voice-coil power rating, not the amplifier power.",
    "max_external_volume_m3": "Optional - derived from width x height x depth "
                              "when left blank.",
}
# ---------------------------------------------------------------------------
#  the nine progressive stages (docs/app-local-multitab.md §4)
# ---------------------------------------------------------------------------
# Each stage owns the question groups it collects and the pipeline gates it
# reports, and declares what must be complete before it unlocks.  The UI renders
# this list; it never invents a stage, an order, or a lock.
# A stage with no owned gates is complete on its answers alone (true for the five
# question stages on a first run, where every gate is still pending).
WORKFLOW_STAGES = (
    {"id": "project_deployment", "name": "Project and deployment",
     "purpose": "What the system is for and the boundary it will load into.",
     "groups": ("Q-PRJ-01",), "gates": (), "requires": ()},
    {"id": "driver_provenance", "name": "Driver and provenance",
     "purpose": "Which driver, and how trustworthy its numbers are.",
     "groups": ("Q-DRV-01/02",), "gates": (), "requires": ()},
    {"id": "safety_limits", "name": "Safety and electrical limits",
     "purpose": "The excursion, thermal and impedance limits that bound output.",
     "groups": ("Q-DRV-04/05+Q-ELE-02",), "gates": ("INPUT_AUDIT",),
     "requires": ("driver_provenance",)},
    {"id": "acoustic_target", "name": "Acoustic target",
     "purpose": "Band, level and distance - what the system must actually deliver.",
     "groups": ("Q-TGT-01/02",),
     "gates": ("LIMIT_IMPACT_ANALYSIS", "PHYSICAL_FEASIBILITY"), "requires": ()},
    {"id": "envelope_manufacturing", "name": "Envelope and manufacturing",
     "purpose": "The size and mass gates, and how it will be built.",
     "groups": ("Q-PHY-01/02+Q-MFG-01",), "gates": (), "requires": ()},
    {"id": "architecture_selection", "name": "Architecture selection",
     "purpose": "Which acoustic family wins, on scored evidence.",
     "groups": (), "gates": ("ARCHITECTURE_SCREENING",),
     "requires": ("acoustic_target", "envelope_manufacturing")},
    {"id": "acoustic_design", "name": "Acoustic and folded design",
     "purpose": "The unfolded reference, the fold, and its area-law check.",
     "groups": (),
     "gates": ("IDEAL_ACOUSTIC_OPTIMIZATION", "FOLD_TOPOLOGY_GENERATION",
               "FOLD_GEOMETRY_VALIDATION", "ONE_DIMENSIONAL_SIMULATION"),
     "requires": ("architecture_selection",)},
    {"id": "verification_bem", "name": "Verification and AKABAK",
     "purpose": "The manual 3-D solve, its import and the validation outcome.",
     "groups": (),
     "gates": ("FOLD_AWARE_SIMULATION", "THREE_DIMENSIONAL_VERIFICATION"),
     "panels": ("manual_bem", "import", "outcome"),
     "requires": ("acoustic_design",)},
    {"id": "final_decision", "name": "Final decision",
     "purpose": "Structure, manufacture, sensitivity, and the recorded decision.",
     "groups": (),
     "gates": ("STRUCTURAL_SCREENING", "MANUFACTURING_TRANSFORMATION",
               "CONSTRAINT_SENSITIVITY", "INDEPENDENT_CRITIQUE",
               "FINAL_COMPARISON", "REPORT_AND_EXPORT"),
     "panels": ("rerun",),
     "requires": ("verification_bem",)},
)

# A gate in one of these states is not holding its stage back; "skipped" is how
# the pipeline records an optional stage it deliberately did not run.
GATE_OK_STATES = ("passed", "skipped")


def _workflow_stages(questions: list, gates: list, *, run_exists: bool,
                     bem_open: bool = False) -> list:
    """Derive the nine stage rows: status, answer counts, lock reason, default open.

    A stage is complete when none of its required answers is outstanding and every
    gate it owns is done.  On a first run the gates are all still pending by
    definition, so only the answers can hold a stage back - otherwise the brief
    could never be frozen.
    """
    qmap = {q["id"]: q for q in questions}
    gmap = {g["stage"]: g for g in gates}
    status_by_id: dict = {}
    rows = []
    for spec in WORKFLOW_STAGES:
        groups = [qmap[g] for g in spec["groups"] if g in qmap]
        owned = [gmap[g] for g in spec["gates"] if g in gmap]

        req_total = sum(g["required_total"] for g in groups)
        req_done = sum(g["required_answered"] for g in groups)
        blockers = [{"group": g["id"], "field": f}
                    for g in groups for f in (g["blocked_by"] or [])]
        failed = [g["stage"] for g in owned if g["status"] in ("failed", "blocked")]
        not_done = ([] if not run_exists else
                    [g["stage"] for g in owned if g["status"] not in GATE_OK_STATES])

        # The manual BEM loop is not a pipeline gate: while it is open (the human
        # still has to solve and export), the verification stage is unfinished even
        # though every gate it owns has "passed" or been deliberately "skipped".
        manual_open = bool(bem_open) and "THREE_DIMENSIONAL_VERIFICATION" in spec["gates"]

        missing = [s for s in spec["requires"] if status_by_id.get(s) != "complete"]
        # Evidence beats the lock: a stage whose own gates have already run is not
        # "locked" - the work visibly happened.  Without this, the four
        # engineering stages would read "locked" forever on a real run whose brief
        # questions were never entered, even though their gates had all passed.
        gates_done = bool(owned) and run_exists and all(
            g["status"] in GATE_OK_STATES for g in owned)
        locked = bool(missing) and not gates_done

        # Answer-driven stages complete on their answers; gates are then
        # informational, so a pending pipeline stage cannot hold the brief back.
        # A stage with no questions of its own is pure pipeline work, and cannot
        # be complete before a run exists - otherwise it would claim "complete"
        # simply because nothing was measurable yet.
        has_questions = bool(groups)
        if has_questions:
            gates_ok = not (failed or not_done)
        else:
            gates_ok = bool(owned) and all(
                g["status"] in GATE_OK_STATES for g in owned)
        answered_ok = not blockers
        complete = answered_ok and gates_ok and not locked and not manual_open

        if locked:
            status = "locked"
        elif failed:
            status = "blocked"
        elif not answered_ok:
            status = "needs_input"
        elif not complete:
            status = "in_progress"
        else:
            status = "complete"
        status_by_id[spec["id"]] = status

        rows.append({
            "id": spec["id"], "order": len(rows), "name": spec["name"],
            "purpose": spec["purpose"], "status": status, "complete": complete,
            "manual_open": manual_open,
            "note": ("The external solve is still outstanding: solve in the AKABAK "
                     "GUI, export the .vips spectra, then import them."
                     if manual_open else None),
            "required_total": req_total, "required_answered": req_done,
            "blocker_count": len(blockers), "blockers": blockers,
            "group_ids": [g["id"] for g in groups],
            "locked": locked,
            "locked_by": (missing if locked else []),
            "locked_reason": (("Finish " + ", ".join(missing) + " first.")
                              if locked else None),
            "blocked_by_evidence": (missing if (missing and not locked) else []),
            "gates": [{"stage": g["stage"], "status": g["status"],
                       "optional": g["optional"], "detail": g["detail"]}
                      for g in owned],
            "gate_failed": failed,
            "panels": list(spec.get("panels") or ()),
        })

    # the first stage that still needs work and is not locked - opened by default
    current = next((r["id"] for r in rows
                    if not r["complete"] and not r["locked"]), None)
    for r in rows:
        r["open_by_default"] = (r["id"] == current)
    return rows


def brief_actions_for(completion: dict, *, editable: bool = False,
                      changed: bool = False) -> dict:
    """Save draft / Freeze brief, each with the reason it is enabled or not.

    ``editable`` is true only in the local host (M4); the static snapshot has no
    way to write anything, so both actions explain themselves instead.
    """
    can_freeze = bool(completion.get("complete"))
    blockers = completion.get("blocker_count") or 0
    if not editable:
        save_reason = ("No editable values in a static snapshot - start the local "
                       "host with: python3 -m hornflow.app --run-dir <run dir>")
    elif changed:
        save_reason = ("Unsaved changes in the draft; saving records them and the "
                       "frozen revision stays as it is.")
    else:
        save_reason = "Nothing to save yet - no draft value has changed."
    return {
        "save_draft": {
            "label": "Save draft", "enabled": bool(editable and changed),
            "reason": save_reason,
        },
        "freeze_brief": {
            "label": "Freeze brief", "enabled": bool(editable and can_freeze),
            "reason": ("Every required answer is present; freezing writes the "
                       "definition file and records the revision and its input hash."
                       if can_freeze else
                       f"{blockers} required answer"
                       f"{'' if blockers == 1 else 's'} still missing."),
        },
    }


def _brief_actions(completion: dict) -> dict:
    return brief_actions_for(completion, editable=False)






EXPORT_EXTS = (".vips", ".txt", ".csv", ".dat", ".tsv", ".asc")

# deliverables we fingerprint for the artifact list (relative to the run dir)
ARTIFACT_PATHS = (
    "state.json", "logs.jsonl", "deliverables/report.md",
    "deliverables/printed.stl", "deliverables/viewer/viewer.html",
    "deliverables/viewer/scene.glb", "deliverables/bem/bem.msh",
    "deliverables/bem/driver_le.txt", "deliverables/bem/bem_manifest.json",
    "deliverables/bem/akabak_recipe.md", "deliverables/bem/bem_manual_report.md",
    "deliverables/bem/compare.md", "deliverables/bem/compare.png",
    "deliverables/bem/curves_stage2.csv",
    "stages/LIMIT_IMPACT_ANALYSIS/limit_impact.md",
)


def _as_dict(state) -> dict:
    """Accept a DesignState or an already-serialised dict."""
    if state is None:
        return {}
    if hasattr(state, "to_dict"):
        return state.to_dict()
    return dict(state)


def _lookup(ctx, dotted):
    """Resolve a dotted path against nested dicts; ``None`` when absent."""
    if not dotted:
        return None
    cur = ctx
    for key in str(dotted).split("."):
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _read_logs(run_dir) -> dict:
    """``{stage: {duration_s, cache, severity, artifacts}}`` from logs.jsonl."""
    if not run_dir:
        return {}
    path = Path(run_dir) / "logs.jsonl"
    if not path.is_file():
        return {}
    out: dict = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        stage = rec.get("stage")
        if not stage:
            continue
        rec_clean = {k: rec.get(k) for k in
                     ("duration_s", "cache", "severity", "artifacts", "event")}
        # keep the last event that carries a duration (stage_done), else the first
        prev = out.get(stage)
        if prev is None or rec_clean.get("duration_s") is not None:
            out[stage] = rec_clean
    return out


def _scan_exports(export_dir) -> dict:
    """Presence-only view of the `.vips` export folder (never parses content)."""
    if not export_dir:
        return {"count": 0, "newest_utc": None, "names": []}
    d = Path(export_dir)
    if not d.is_dir():
        return {"count": 0, "newest_utc": None, "names": []}
    files = sorted(p for p in d.rglob("*")
                   if p.is_file() and p.suffix.lower() in EXPORT_EXTS)
    newest = None
    if files:
        import datetime as _dt
        newest = _dt.datetime.fromtimestamp(
            max(p.stat().st_mtime for p in files), tz=_dt.timezone.utc
        ).isoformat(timespec="seconds")
    return {"count": len(files), "newest_utc": newest,
            "names": [p.name for p in files]}


def _artifacts(run_dir) -> list:
    if not run_dir:
        return []
    run_dir = Path(run_dir)
    out = []
    for rel in ARTIFACT_PATHS:
        p = run_dir / rel
        if not p.is_file():
            continue
        out.append({"name": Path(rel).name, "path": rel,
                    "bytes": p.stat().st_size, "sha256": sha256_file(p)})
    return out


def _list_runs(run_dir):
    """Sibling run ids, newest last (deterministic, filesystem-derived)."""
    if not run_dir:
        return []
    parent = Path(run_dir).parent
    if not parent.is_dir():
        return []
    return sorted(p.name for p in parent.iterdir()
                  if p.is_dir() and (p / "state.json").is_file())



# ---------------------------------------------------------------------------
#  section builders
# ---------------------------------------------------------------------------
def _field_record(f: dict, value, source) -> dict:
    """One field: presentation + the acceptance rule, computed here and nowhere else."""
    required = f["name"] not in OPTIONAL_FIELDS
    if value is None or value == "":
        status, provenance, confidence = "UNKNOWN", None, None
    else:
        status, provenance, confidence = "FIXED", "USER_INPUT", 1.0
    # The acceptance rule (docs/app-local-multitab.md §7): a value counts only
    # when it is present, not UNKNOWN, and carries provenance *and* confidence.
    # Fixed values therefore count only when they are valid and provable, and
    # UNKNOWN never counts - which is exactly what the old W4 got wrong.
    accepted = bool(value not in (None, "") and status != "UNKNOWN"
                    and provenance is not None and confidence is not None)
    return {
        "key": f["name"],
        "label": FIELD_LABELS.get(f["name"], f["name"]),
        "help": FIELD_HELP.get(f["name"]),
        "type": f["type"], "unit": f["unit"], "enum": f["enum"],
        "path": f["path"], "value": value,
        "required": required,
        "status": status, "provenance": provenance, "confidence": confidence,
        "accepted": accepted,
        "source": source if accepted else None,
    }


def _questions(state: dict, first_run: bool, brief: dict | None = None) -> list:
    """The five questions: each field resolved from the brief, then the run state.

    Every completion number below is emitted by this function.  The UI renders
    them; it must never recompute them.
    """
    out = []
    for group in FIRST_RUN_QUESTIONS:
        fields = []
        for f in group["fields"]:
            value, source = None, None
            # Resolution order: the brief by declared path, then the brief by the
            # field's own key (some required fields - the SPL target, the
            # envelope - have no run-state path), then the run state by path.
            # Without the second step those fields could never be answered and a
            # group could never complete.
            if brief:
                if f["path"]:
                    value = _lookup(brief, f["path"])
                if value is None:
                    value = _lookup(brief, f["name"])
                if value is not None:
                    source = "brief"
            if value is None and not first_run and f["path"]:
                value = _lookup(state, f["path"])
                if value is not None:
                    source = "run_state"
            fields.append(_field_record(f, value, source))
        req = [f for f in fields if f["required"]]
        done = [f for f in req if f["accepted"]]
        out.append({
            "id": group["id"], "prompt": group["prompt"], "wave": group["wave"],
            "required": group["required"], "why": group["why"],
            "fields": fields,
            "fields_total": len(fields),
            "fields_answered": sum(1 for f in fields if f["accepted"]),
            "required_total": len(req), "required_answered": len(done),
            "complete": bool(req) and len(done) == len(req),
            "blocked_by": [f["key"] for f in req if not f["accepted"]],
            "blocking": bool(group["required"]) and len(done) != len(req),
            "first_unanswered": next((f["key"] for f in req if not f["accepted"]), None),
        })
    return out


def _completion(questions: list, *, run_exists: bool) -> dict:
    """Completion and blocker counts - the single source the UI renders.

    Rules (docs/app-local-multitab.md §7): a group is COMPLETE only when every
    *required* field is accepted; a wave is COMPLETE only when every required
    group in it is complete; empty optional fields never block; UNKNOWN never
    counts as answered.
    """
    waves: dict = {}
    for wave in sorted({q["wave"] for q in questions}):
        groups = [q for q in questions if q["wave"] == wave]
        req = [g for g in groups if g["required"]]
        waves[wave] = {
            "groups": [g["id"] for g in groups],
            "required_groups": len(req),
            "complete_groups": sum(1 for g in req if g["complete"]),
            "complete": bool(req) and all(g["complete"] for g in req),
            "blocked_by": [g["id"] for g in req if not g["complete"]],
        }
    req_fields = [f for q in questions for f in q["fields"] if f["required"]]
    blockers = [{"group": q["id"], "field": f["key"], "label": f["label"]}
                for q in questions for f in q["fields"]
                if f["required"] and not f["accepted"]]
    return {
        "run_exists": run_exists,
        "waves": waves,
        "wave_a_complete": bool((waves.get("A") or {}).get("complete")),
        "groups_total": len(questions),
        "groups_complete": sum(1 for q in questions if q["complete"]),
        "required_fields_total": len(req_fields),
        "required_fields_answered": sum(1 for f in req_fields if f["accepted"]),
        "blockers": blockers,
        "blocker_count": len(blockers),
        "next_required_field": (blockers[0] if blockers else None),
        "complete": bool(req_fields) and not blockers,
    }


def _gates(stages: dict, logs: dict) -> list:
    out = []
    for stage in STAGE_ORDER:
        name = stage.value
        rec = dict(stages.get(name) or {})
        log = logs.get(name) or {}
        blocked_by = []
        if str(rec.get("status", "pending")) == "blocked":
            for pre in prerequisites(stage):
                if str((stages.get(pre.value) or {}).get("status", "pending")) != "passed":
                    blocked_by.append(pre.value)
        out.append({
            "stage": name,
            "status": str(rec.get("status", "pending")),
            "optional": stage in OPTIONAL_STAGES,
            "detail": str(rec.get("detail", "") or ""),
            "blocked_by": blocked_by,
            "duration_s": log.get("duration_s"),
            "cache": log.get("cache"),
            "artifacts": list(log.get("artifacts") or []),
            "failure": rec.get("failure"),
        })
    return out


def _manual_bem(bem: dict, stages: dict, exports: dict) -> dict:
    if not bem:
        return {"state": None, "reason": None, "checklist": [], "available": False,
                "export_dir": None, "manifest": None, "recipe": None,
                "exported_files": exports["count"],
                "newest_export_utc": exports["newest_utc"], "chain": list(BEM_STATES)}
    return {
        "state": bem.get("state"),
        "available": True,
        "reason": bem.get("reason"),
        "solver": bem.get("solver"),
        "solver_version": bem.get("solver_version"),
        "solver_label": "AKABAK Free 3.3.2 b144",
        "export_dir": bem.get("export_dir"),
        "manifest": bem.get("manifest"),
        "recipe": _recipe_path(bem),
        "chain": list(bem.get("chain") or BEM_STATES),
        "checklist": list(CHECKLIST_ITEMS),
        "exported_files": exports["count"],
        "newest_export_utc": exports["newest_utc"],
        "next_action": bem.get("next_action"),
    }


CHECKLIST_ITEMS = (
    {"key": "start", "text": "Start AKABAK (./AKABAK/akabak.sh)"},
    {"key": "project", "text": "Open/build the project and load the mesh"},
    {"key": "tree", "text": "Verify the BEM tree (Throat / Hornwall / Mouth)"},
    {"key": "lem", "text": "Verify the LEM network (s/t = coil, u = front, v = rear)"},
    {"key": "level", "text": "Set the drive level (Is rms ticked)"},
    {"key": "solve", "text": "Solve (BEM-Meshing -> Solving -> LE -> Ob)"},
    {"key": "export", "text": "Export the .vips spectra to the export folder"},
    {"key": "confirm", "text": "Confirm the export folder is non-empty"},
    {"key": "send", "text": "Send it back with the import command"},
)


def _recipe_path(bem: dict):
    manifest = bem.get("manifest")
    if not manifest:
        return None
    return str(Path(manifest).parent / "akabak_recipe.md")



def _import_panel(bem: dict, state: dict, export_dir) -> dict:
    run = state.get("run") or {}
    export = bem.get("export_dir") or (str(export_dir) if export_dir else None)
    input_path = run.get("input_path") or "<definition.yaml>"
    command = None
    if export:
        command = f"python3 -m hornflow.cli {input_path} --bem-import {export}"
    bem_state = bem.get("state") or "INPUTS_GENERATED"
    return {
        "available": False,            # static host: no mutation (M4 adds /api/import)
        "ready": bem_state in ("MANUAL_SOLVE_PENDING", "MANUAL_SOLVE_COMPLETED"),
        "state": bem_state,
        "enabled_when_state": "MANUAL_SOLVE_COMPLETED",
        "export_dir": export,
        "last_source": bem.get("source"),
        "last_utc": bem.get("imported_utc"),
        "command": command,
    }


def _outcome(bem: dict, state: dict, findings: list) -> dict:
    final = state.get("final_recommendations") or {}
    bem_state = bem.get("state") or "INPUTS_GENERATED"
    if bem_state in BEM_OPEN or bem_state in ("INPUTS_GENERATED", "VIPS_IMPORTED"):
        exit_name = None
    elif bem_state == "BEM_VALIDATED":
        exit_name = "record_decision"
    else:
        exit_name = "re_export_or_relax_tolerance"
    metrics = bem.get("metrics")
    return {
        "bem": bem_state,
        "decided": _decided(state),
        "hard_gates": bool(final.get("hard_gates_passed")),
        "validation_passed": bem.get("validation_passed"),
        "checks": list(bem.get("checks") or []),
        "metrics": metrics,
        "warnings": list(bem.get("warnings") or []),
        "source": bem.get("source"),
        "tolerance_db": bem.get("tolerance_db"),
        "evidence": "BEM_SIMULATION" if metrics else None,
        "critic": [{"check": f.get("check"), "passed": f.get("passed"),
                    "severity": f.get("severity"), "detail": f.get("detail")}
                   for f in (findings or [])],
        "exit": exit_name,
    }


def _decided(state: dict) -> bool:
    return any(str(e.get("event", "")).startswith("decision")
               for e in (state.get("decision_log") or []))



def _current_state(state: dict, bem_state: str, gates: list, questions: list,
                   completion: dict | None = None,
                   stages: list | None = None) -> dict:
    run = state.get("run") or {}
    validation = state.get("validation") or {}
    bem = validation.get("bem_manual") or {}
    passed = sum(1 for g in gates if g["status"] == "passed")
    failed = [g["stage"] for g in gates if g["status"] in ("failed", "blocked")]
    assumptions = sum(1 for q in questions for f in q["fields"]
                      if f["provenance"] in ("DEFAULT", "ESTIMATED"))
    comp = completion or {}
    current = next((r for r in (stages or []) if r.get("open_by_default")), None)
    return {
        "brief_revision": (validation.get("brief") or {}).get("revision"),
        "input_hash": (validation.get("brief") or {}).get("input_hash"),
        "run_id": run.get("run_id"),
        "input_path": run.get("input_path"),
        "stages_total": len(gates),
        "stages_passed": passed,
        "stages_failed": failed,
        "bem_state": bem_state,
        "bem_status": validation.get("bem_status"),
        "solver": bem.get("solver"),
        "solver_version": bem.get("solver_version"),
        "solver_label": "AKABAK Free 3.3.2 b144" if bem else None,
        "assumptions": assumptions,
        "warnings": len(bem.get("warnings") or []),
        # completion is emitted by the model, never derived in the browser
        "questions_complete": comp.get("complete"),
        "required_fields_total": comp.get("required_fields_total"),
        "required_fields_answered": comp.get("required_fields_answered"),
        "blocker_count": comp.get("blocker_count"),
        "wave_a_complete": comp.get("wave_a_complete"),
        # the stage the UI opens by default, and the single next action's owner
        "current_stage": (None if current is None else
                          {"id": current["id"], "name": current["name"],
                           "status": current["status"],
                           "order": current["order"]}),
        "stages_complete": sum(1 for r in (stages or []) if r.get("complete")),
        "stages_total_workflow": len(stages or []),
    }


def _mode(state: dict, bem_state: str, gates: list) -> str:
    if not (state.get("run") or {}).get("run_id"):
        return "first_run"
    if any(g["status"] in ("failed", "blocked") for g in gates):
        return "blocked"
    if bem_state in BEM_OPEN:
        return "manual_bem"
    if _decided(state):
        return "decided"
    if any(g["stage"] == "REPORT_AND_EXPORT" and g["status"] == "passed"
           for g in gates):
        return "review"
    return "running"


def _next_action(mode: str, gates: list, questions: list, bem_state: str,
                 outcome: dict, import_panel: dict) -> dict:
    """The ordered rule table (docs/app-local-multitab.md §10). First match wins."""
    def act(aid, label, why, owner, kind="none", value=None, blockers=()):
        return {"id": aid, "label": label, "why": why, "owner": owner,
                "blockers": list(blockers), "cta": {"kind": kind, "value": value}}

    if mode == "first_run":
        missing = [q["id"] for q in questions if q["blocking"]]
        if missing:
            return act("act.brief.answer", "Answer the required questions",
                       "Five answers make architecture selection possible.",
                       "Requester", "none", None, missing)
        return act("act.brief.freeze", "Freeze brief",
                   "Freezing writes the brief and its input hash; only then can a "
                   "run start.", "Requester")

    failed = [g for g in gates if g["status"] in ("failed", "blocked")]
    if failed:
        g = failed[0]
        from_stage = ((g.get("failure") or {}).get("recommended_upstream_revision")
                      or g["stage"])
        return act("act.rerun.from", f"Re-run from {from_stage}",
                   g.get("detail") or "A stage did not pass.",
                   "Acoustics", "copy_command", from_stage)

    if bem_state in ("MANUAL_SOLVE_PENDING", "MANUAL_SOLVE_COMPLETED"):
        return act("act.bem.import", "Import & validate (.vips)",
                   "The .vips export is the last manual step; the import validates "
                   "it and compares it with the 1-D reference.",
                   "Builder", "copy_command", import_panel.get("command"))
    if bem_state == "GUI_REQUIRED":
        return act("act.bem.export", "Copy AKABAK checklist",
                   "AKABAK runs under Wine through its GUI: do the solve, export "
                   "the .vips spectra, then import them.",
                   "Builder", "copy_command", import_panel.get("command"))

    rejects = [c for c in (outcome.get("critic") or [])
               if c.get("severity") == "reject" and not c.get("passed")]
    if rejects:
        return act("act.critic", "Re-run from <STAGE>",
                   f"Critic: {rejects[0].get('check')}", "Acoustics")

    metrics = outcome.get("metrics") or {}
    if bem_state == "BEM_REJECTED":
        why = "Compared but outside tolerance."
        if metrics:
            why = (f"Compared, worst |difference| "
                   f"{metrics.get('worst_diff_db', 0):.2f} dB vs "
                   f"{outcome.get('tolerance_db')} dB tolerance.")
        return act("act.bem.retry", "Re-export and retry", why, "Builder")
    if bem_state == "BEM_VALIDATED" and not outcome.get("decided"):
        return act("act.decide", "Mark decided",
                   "Validated against the 1-D reference.", "Owner")
    return act("act.report", "Open the report",
               "The run is complete; the report holds the decision detail.",
               "Builder", "open_url", "deliverables/report.md")



# ---------------------------------------------------------------------------
#  annotations for the viewer's Dimensions overlay (M2, decision D1/D3)
# ---------------------------------------------------------------------------
def annotations_for(state, *, units: str = "m") -> dict:
    """Dimension figures for the viewer overlay. Default unit is metres."""
    import math
    s = _as_dict(state)
    ref = (s.get("reference_profiles") or [{}])[0] or {}
    folds = s.get("fold_candidates") or []
    fold_id = (s.get("validation") or {}).get("fold_id")
    chosen = next((f for f in folds if f.get("fold_id") == fold_id), None)
    if chosen is None and folds:
        chosen = next((f for f in folds if f.get("valid")), folds[0])
    pack = (chosen or {}).get("packaging") or {}

    throat_a = ref.get("throat_area_m2")
    mouth_a = ref.get("mouth_area_m2")
    aspect = float(ref.get("aspect") or 1.6) or 1.6
    mouth_w = mouth_h = None
    if mouth_a:
        mouth_h = math.sqrt(mouth_a / aspect)          # h = sqrt(A/aspect)
        mouth_w = mouth_a / mouth_h                    # w = A/h  ->  w*h = A
    bbox = None
    if pack.get("bbox_w_m") is not None:
        bbox = [pack["bbox_w_m"], pack["bbox_h_m"], pack["bbox_d_m"]]

    bends = []
    for i, b in enumerate((chosen or {}).get("bends") or [], start=1):
        bends.append({
            "id": f"B{i}",
            "radius_m": b.get("radius_m"),
            "angle_deg": (b.get("angle_rad") or 0.0) * 180.0 / math.pi,
            "phase_skew_deg": b.get("phase_skew_deg"),
            "reflection_risk": b.get("reflection_risk"),
        })
    return {
        "units": units,
        "path_length_m": ref.get("length_m"),
        "throat_diameter_mm": (2.0 * math.sqrt(throat_a / math.pi) * 1e3)
                              if throat_a else None,
        "mouth_area_cm2": (mouth_a * 1e4) if mouth_a else None,
        "mouth_width_mm": (mouth_w * 1e3) if mouth_w else None,
        "mouth_height_mm": (mouth_h * 1e3) if mouth_h else None,
        "bbox_m": bbox,
        "aspect": aspect,
        "compression_ratio": ref.get("compression_ratio"),
        "bends": bends,
    }


def _rerun(gates: list) -> dict:
    failed = [g for g in gates if g["status"] in ("failed", "blocked")]
    from_stage = reason = None
    if failed:
        g = failed[0]
        from_stage = ((g.get("failure") or {}).get("recommended_upstream_revision")
                      or g["stage"])
        reason = g.get("detail") or "A stage did not pass."
    return {"available": True, "from_stage": from_stage, "reason": reason,
            "keeps": ["brief", "decision record"],
            "regenerates": ["run_id", "all artifacts"]}



# ---------------------------------------------------------------------------
#  public API
# ---------------------------------------------------------------------------
def build_view(state, *, run_dir=None, brief=None, now=None, export_dir=None,
               runs_available=None, host: str = "static", logs=None) -> dict:
    """Build the read-only app view model from authoritative run artifacts."""
    s = _as_dict(state)
    run_rec = s.get("run") or {}
    validation = s.get("validation") or {}
    bem = validation.get("bem_manual") or {}
    validation = s.get("validation") or {}
    accepted_unvalidated = validation.get("accepted_unvalidated") is True
    bem_state = str(bem.get("state") or "INPUTS_GENERATED")
    first_run = not run_rec.get("run_id")

    log_map = logs if logs is not None else _read_logs(run_dir)
    gates = _gates(s.get("stages") or {}, log_map)
    brief_in = brief if brief is not None else (s.get("requirements") or {})
    questions = _questions(s, first_run, brief_in)
    completion = _completion(questions, run_exists=not first_run)
    stages = _workflow_stages(questions, gates, run_exists=not first_run,
                              bem_open=bem_state in BEM_OPEN)
    brief_actions = _brief_actions(completion)
    exp_dir = export_dir
    if exp_dir is None and run_dir is not None:
        exp_dir = Path(run_dir) / "deliverables" / "bem" / "export"
    exports = _scan_exports(exp_dir)
    manual = _manual_bem(bem, s.get("stages") or {}, exports)
    import_panel = _import_panel(bem, s, exp_dir)
    outcome = _outcome(bem, s, s.get("critic_findings") or [])
    mode = _mode(s, bem_state, gates)
    project = s.get("project") or {}
    family = ((s.get("final_recommendations") or {}).get("best_folded_horn")
              or {}).get("family")
    runs = runs_available if runs_available is not None else _list_runs(run_dir)

    return {
        "view_schema": VIEW_SCHEMA,
        "generated_utc": now or now_utc(),
        "host": host,
        "mode": mode,
        "project": {"name": project.get("name", ""),
                    "author": project.get("author", "")},
        "run": None if first_run else {
            "run_id": run_rec.get("run_id"),
            "input_path": run_rec.get("input_path"),
            "brief_revision": (validation.get("brief") or {}).get("revision"),
            "input_hash": (validation.get("brief") or {}).get("input_hash"),
            "runs_available": list(runs),
        },
        # a persistent, non-dismissable warning: an unvalidated result was accepted
        "unvalidated_accepted": accepted_unvalidated,
        "current_state": _current_state(s, bem_state, gates, questions, completion,
                                        stages),
        "next_action": _next_action(mode, gates, questions, bem_state, outcome,
                                    import_panel),
        "gates": gates,
        "questions": questions,
        "completion": completion,
        "workflow_stages": stages,
        "brief_actions": brief_actions,
        # the fixed reason list the UI offers when a result is accepted unvalidated
        "accept_reasons": list(ACCEPT_REASONS),
        "manual_bem": manual,
        "import_panel": import_panel,
        "outcome": outcome,
        "rerun": _rerun(gates),
        "artifacts": _artifacts(run_dir),
        "annotations": annotations_for(s),
        "viewer": {
            "title": (f"{project.get('name', '')} - {family}" if family
                      else project.get("name", "")),
            "html": "viewer/viewer.html",
            "features": {"dimensions": True, "units": "m", "mm_toggle": True,
                         "compare": False, "reference_glb": None},
        },
        "brief": brief if brief is not None else brief_in,
    }


def first_run_view(*, project=None, brief=None, now=None) -> dict:
    """The `run: null` fixture: five required questions, no gates."""
    view = build_view({}, now=now, brief=brief)
    view["mode"] = "first_run"
    view["run"] = None
    view["current_state"]["stages_total"] = len(STAGE_ORDER)
    if project:
        view["project"] = {"name": project, "author": ""}
    return view


def to_json(view: dict) -> str:
    """Deterministic serialisation (sorted keys) - the golden-test contract."""
    return json.dumps(view, indent=2, sort_keys=True) + "\n"


def emit_view(view: dict, path) -> Path:
    """Write `app_view.json` atomically."""
    path = Path(path)
    atomic_write(path, to_json(view).encode("utf-8"))
    return path

