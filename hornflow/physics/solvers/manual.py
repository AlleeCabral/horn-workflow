"""The manual-solve state machine for the external (GUI-driven) BEM step.

Authoritative, verified environment - do not re-litigate:

* AKABAK **Free 3.3.2 build 144** (``AKABAK_Demo_64r.exe``) on a Linux host;
* it runs through the **Wine GUI** and there is **no usable head-less / CLI
  solve path** in this setup, so an unattended solve cannot be implemented;
* the Free/demo build **does not write the solved BEM state** as an ``.akpbe``
  file - the solved state stays in RAM;
* ``.vips`` spectra **can** be exported manually and imported by HornFlow.

HornFlow therefore writes *every* input automatically, hands over to the human
for the documented GUI actions, and validates whatever comes back.  Nothing in
this module invents a solved field: a candidate is **never** marked
``BEM_VALIDATED`` before a ``.vips`` import *plus* comparison has actually run.

This module holds no acoustic physics; it is the bookkeeping around the honest
``pending_external`` contract of the AKABAK solver adapter.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path

from ...domain.evidence import now_utc
from ...io.artifacts import atomic_write, sha256_file

MANIFEST_NAME = "bem_manifest.json"
MANIFEST_SCHEMA = "1.0"


# --------------------------------------------------------------------------- #
#  the state machine
# --------------------------------------------------------------------------- #
class ManualSolveState(str, Enum):
    """The lifecycle of the external, human-driven BEM solve."""

    INPUTS_GENERATED = "INPUTS_GENERATED"
    GUI_REQUIRED = "GUI_REQUIRED"
    MANUAL_SOLVE_PENDING = "MANUAL_SOLVE_PENDING"
    MANUAL_SOLVE_COMPLETED = "MANUAL_SOLVE_COMPLETED"
    VIPS_IMPORTED = "VIPS_IMPORTED"
    BEM_COMPARISON_COMPLETED = "BEM_COMPARISON_COMPLETED"
    BEM_VALIDATED = "BEM_VALIDATED"
    BEM_REJECTED = "BEM_REJECTED"


# Allowed forward transitions.  A *new* import of a *fresh* export supersedes an
# earlier decision, so the two decided states may return to VIPS_IMPORTED; the
# previous decision itself is never erased (it stays in the decision log).
REIMPORT_FROM = (ManualSolveState.BEM_VALIDATED.value,
                 ManualSolveState.BEM_REJECTED.value)

ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    ManualSolveState.INPUTS_GENERATED.value: (ManualSolveState.GUI_REQUIRED.value,),
    ManualSolveState.GUI_REQUIRED.value: (ManualSolveState.MANUAL_SOLVE_PENDING.value,),
    ManualSolveState.MANUAL_SOLVE_PENDING.value: (ManualSolveState.MANUAL_SOLVE_COMPLETED.value,),
    ManualSolveState.MANUAL_SOLVE_COMPLETED.value: (ManualSolveState.VIPS_IMPORTED.value,),
    ManualSolveState.VIPS_IMPORTED.value: (ManualSolveState.BEM_COMPARISON_COMPLETED.value,),
    ManualSolveState.BEM_COMPARISON_COMPLETED.value: (ManualSolveState.BEM_VALIDATED.value,
                                                     ManualSolveState.BEM_REJECTED.value),
    ManualSolveState.BEM_VALIDATED.value: (ManualSolveState.VIPS_IMPORTED.value,),
    ManualSolveState.BEM_REJECTED.value: (ManualSolveState.VIPS_IMPORTED.value,),
}

# The order the pipeline walks through; useful for reporting.
STATE_CHAIN: tuple[str, ...] = (
    ManualSolveState.INPUTS_GENERATED.value,
    ManualSolveState.GUI_REQUIRED.value,
    ManualSolveState.MANUAL_SOLVE_PENDING.value,
    ManualSolveState.MANUAL_SOLVE_COMPLETED.value,
    ManualSolveState.VIPS_IMPORTED.value,
    ManualSolveState.BEM_COMPARISON_COMPLETED.value,
    ManualSolveState.BEM_VALIDATED.value,
)


def can_advance(current: str, target: str) -> bool:
    """True when ``current -> target`` is a legal transition."""
    return target in ALLOWED_TRANSITIONS.get(str(current), ())


def advance(current: str, target: str) -> str:
    """Advance ``current`` to ``target``, rejecting illegal jumps loudly."""
    if not can_advance(current, target):
        raise ValueError(f"illegal manual-solve transition {current!r} -> {target!r}; "
                         f"allowed: {ALLOWED_TRANSITIONS.get(str(current), ())}")
    return str(target)


def is_complete(state: str) -> bool:
    """A candidate whose BEM is decided one way or the other."""
    return str(state) in (ManualSolveState.BEM_VALIDATED.value,
                          ManualSolveState.BEM_REJECTED.value)


def is_validated(state: str) -> bool:
    return str(state) == ManualSolveState.BEM_VALIDATED.value


# --------------------------------------------------------------------------- #
#  the run manifest - what HornFlow handed over, and when
# --------------------------------------------------------------------------- #
@dataclass
class RunManifest:
    """Immutable record of the inputs generated for one manual solve."""

    run_id: str
    project: str
    generated_utc: str
    input_path: str
    solver: str
    solver_version: str
    fidelity: str
    bem_dir: str
    export_dir: str
    expected_exports: list = field(default_factory=list)
    required_spectrum: str = "on-axis sound pressure (Pa)"
    files: dict = field(default_factory=dict)      # name -> {path, sha256, bytes}
    notes: str = ""
    schema_version: str = MANIFEST_SCHEMA

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "RunManifest":
        known = {f: d.get(f) for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**known)                                       # type: ignore[arg-type]


def build_manifest(*, run_id: str, project: str, input_path, solver: str,
                   solver_version: str, fidelity: str, bem_dir, export_dir,
                   files: dict | None = None, expected_exports: list | None = None,
                   notes: str = "", generated_utc: str | None = None) -> RunManifest:
    """Collect and fingerprint the inputs HornFlow generated for the manual solve."""
    rec: dict = {}
    for name, path in (files or {}).items():
        p = Path(path)
        if not p.is_file():
            continue
        rec[name] = {"path": str(p), "bytes": p.stat().st_size,
                     "sha256": sha256_file(p)}
    return RunManifest(
        run_id=str(run_id), project=str(project),
        generated_utc=generated_utc or now_utc(), input_path=str(input_path),
        solver=solver, solver_version=solver_version, fidelity=fidelity,
        bem_dir=str(bem_dir), export_dir=str(export_dir),
        expected_exports=list(expected_exports or ["*.vips"]),
        files=rec, notes=notes)


def write_manifest(manifest: RunManifest, path) -> Path:
    path = Path(path)
    atomic_write(path, (json.dumps(manifest.to_dict(), indent=2, sort_keys=True)
                        + "\n").encode("utf-8"))
    return path


def read_manifest(path) -> "RunManifest | None":
    """Read a manifest, or ``None`` when the file is absent/unreadable."""
    path = Path(path)
    if not path.is_file():
        return None
    try:
        return RunManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except (ValueError, TypeError, OSError):
        return None



# --------------------------------------------------------------------------- #
#  the run-specific checklist (a tick-as-you-go recipe for one run)
# --------------------------------------------------------------------------- #
def checklist_md(*, project: str, run_id: str, input_path, bem_dir, export_dir,
                 expected_exports, solver: str = "AKABAK Free 3.3.2 b144",
                 solver_version: str = "3.3-demo", launcher: str = "./AKABAK/akabak.sh",
                 manifest_path=None, legacy_cmd: str | None = None,
                 pipeline_cmd: str | None = None) -> str:
    """A run-specific, tick-as-you-go checklist for the manual AKABAK solve."""
    mani = Path(manifest_path) if manifest_path else (Path(bem_dir) / MANIFEST_NAME)
    exports = "; ".join(f"`{e}`" for e in (expected_exports or ["*.vips"]))
    man = read_manifest(mani)
    stamp = man.generated_utc if man else "(generate the inputs first)"
    lines = [
        f"# Run checklist - manual AKABAK solve for {project}",
        "",
        f"* **Run ID:** `{run_id}`",
        f"* **Solver:** {solver} (`{solver_version}`) - Wine GUI, **manual solve required**.",
        f"* **Definition:** `{input_path}`",
        "",
        "Why this step is manual (verified, not a limitation we can code around): there is "
        "no usable head-less/CLI solve path in this setup, and the Free/demo build does not "
        "write the solved BEM state (`.akpbe`) - it stays in RAM, so only the exported "
        "`.vips` spectra can leave the GUI.",
        "",
        "## Exact paths for this run",
        "",
        "| what | where |",
        "| --- | --- |",
        f"| inputs written by HornFlow | `{bem_dir}/` |",
        f"| **export your `.vips` spectra here** | `{export_dir}` |",
        f"| run manifest (fingerprints) | `{mani}` |",
        "",
        "## Expected export filenames",
        "",
        f"The importer accepts {exports}. AKABAK names them "
        "`Akabak-<project>-<observation>.vips`; any of the documented observation names "
        "(`Mic1`, `H 0-90`, `RadImp1`, `LE*`) is fine. Keep at least one surface-pressure "
        "observation (`Mic1` or `H 0-90`) - that is the required spectrum.",
        "",
        "## Manual actions (tick as you go)",
        "",
        f"- [ ] **1. Start AKABAK**: `{launcher}` (registers the VACS COM server, then "
        "starts the 64-bit demo). A graphical desktop is required.",
        "- [ ] **2. Open/build the project**: import the mesh file, add the Elements and "
        "the BEM tree, and wire the lumped-element network exactly as in this run's "
        "`akabak_recipe.md` (the detailed, click-by-click steps follow below).",
        "- [ ] **3. Verify the BEM tree**: `Throat` is *Driven*, `Hornwall` is a wall, the "
        "`Mouth` interface separates Interior/Exterior.",
        "- [ ] **4. Verify the LEM network**: driver terminals `s`/`t` = voice coil, "
        "`u` = diaphragm front -> horn, `v` = diaphragm rear -> rear chamber. Couple the "
        "diaphragm to the BEM **once** (never twice).",
        "- [ ] **5. Set the drive level**: `Global -> Level of Driving`, *Is rms* ticked.",
        "- [ ] **6. Solve**: BEM-Meshing -> BEM-Solving -> LE-Solving -> Ob Fields -> "
        "Ob Spectra (check the input-impedance fingerprint from the recipe before spending "
        "time elsewhere).",
        "- [ ] **7. Export the spectra**: `Options -> Preferences -> VACS -> Spectrum way "
        f"of output = Files`, *Text format* ticked, Folder = `{export_dir}`; then "
        "`Processing -> Output Spectra`. (VACS over COM also works - see step 7 below.)",
        "- [ ] **8. Confirm the folder is non-empty** and holds `*.vips` files newer than "
        f"`{stamp}`.",
        "- [ ] **9. Send it back** with the command in the last section.",
        "",
        "## Troubleshooting (quick)",
        "",
        "| symptom | fix |",
        "| --- | --- |",
        "| no window appears | run `winecfg` once, then retry the launcher |",
        "| *Cannot locate VACS...* dialog | harmless; or use the Files route (step 7) |",
        "| flat or empty curve | `Throat` not *Driven*, or the diaphragm is not coupled to the BEM |",
        "| model tiny or huge | mesh is in metres; Mesh File scaling must be 1 |",
        "| export folder stays empty | tick *Text format* under VACS -> Spectrum way of output |",
        "",
        "## Send it back (one command)",
        "",
    ]
    if legacy_cmd:
        lines += ["```", legacy_cmd, "```", ""]
    if pipeline_cmd:
        lines += ["Or, for the gated pipeline state machine:", "",
                  "```", pipeline_cmd, "```", ""]
    lines += [
        "The importer checks that the expected files exist, are non-empty, belong to this "
        "run, have a valid frequency grid, contain the required pressure spectrum, hold "
        "numeric finite values, are newer than the generated inputs, and match this run "
        "manifest - then compares them with the one-dimensional reference. Only after that "
        "comparison can the candidate become `BEM_VALIDATED`.",
        "",
    ]
    return "\n".join(lines)

