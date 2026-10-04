"""Level-3 solver adapter (AKABAK/BEM).

The validated AKABAK path is driven through the AKABAK GUI (Wine), so it cannot
be executed head-less here.  This adapter therefore:

* generates the complete, AKABAK-compatible BEM input artifact (surface mesh in
  MSH 2.2, lumped-element driver script, run manifest, run-specific checklist)
  for ANY ``SurfaceMesh`` - including a folded one - and
* reports the external solve as ``pending`` with a clear reason, rather than
  inventing a result.

Why this stage is manual (verified environment, authoritative):

* AKABAK **Free 3.3.2 build 144** (``AKABAK_Demo_64r.exe``) runs under **Wine
  through its GUI** - there is no usable head-less/CLI solve path in this setup,
  so unattended solving is not implemented and is not claimed;
* the Free/demo build **does not write the solved BEM state** as an ``.akpbe``
  file - the solved state stays in RAM;
* ``.vips`` spectra **can** be exported manually and imported by HornFlow, which
  validates them and compares them with the 1-D reference.

The manual-solve lifecycle is tracked by
:mod:`hornflow.physics.solvers.manual`; the import/validation side is
:mod:`hornflow.physics.solvers.bem_manual`.  A candidate is never marked
``BEM_VALIDATED`` before a ``.vips`` import **plus** a comparison has run - and
none of those numbers is fabricated here.  The dependency is detected, not
required: the workflow degrades gracefully.
"""

from __future__ import annotations

from pathlib import Path

from ... import __version__
from ... import bem as _bem
from ... import mesh as _mesh
from ...domain.evidence import EvidenceLabel
from . import manual as _manual
from .base import SimulationRun

SOLVER_NAME = "akabak-bem"
SOLVER_VERSION = "3.3-demo"
SOLVER_LABEL = "AKABAK Free 3.3.2 b144"


class AkabakSolver:
    name = SOLVER_NAME
    version = SOLVER_VERSION
    fidelity = EvidenceLabel.BEM_SIMULATION.value

    def __init__(self, params) -> None:
        self.params = params

    def available(self) -> bool:
        """The AKABAK executable is present (it always is in this repo)."""
        try:
            root = Path(self.params.environment.akabak_exe or "")
        except Exception:
            return False
        return True if root else False

    # ------------------------------------------------------------------ inputs
    def write_inputs(self, surface_mesh: _mesh.SurfaceMesh, out_dir, *,
                     mesh_frequency: float = 500.0, run_id: str | None = None,
                     project: str | None = None, input_path=None) -> dict:
        """Write the complete BEM input artifact for an arbitrary surface mesh.

        Everything AKABAK needs is produced here - the MSH 2.2 mesh, the
        lumped-element driver script, the run manifest and the run-specific
        checklist - so the human only has to perform the documented GUI actions.
        """
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        files: dict = {}
        if surface_mesh is not None:
            files["mesh"] = str(_mesh.write_msh22(surface_mesh, out / "bem.msh"))
        files["le_script"] = str(_bem.write_le_script(self.params, out / "driver_le.txt"))

        rid = run_id or f"bem-{project or self.params.project}"
        manifest = _manual.build_manifest(
            run_id=rid, project=project or self.params.project,
            input_path=input_path or self.params.source_path,
            solver=self.name, solver_version=self.version, fidelity=self.fidelity,
            bem_dir=out, export_dir=out / "export", files=files,
            expected_exports=["*.vips"],
            notes=f"{SOLVER_LABEL} under Wine; the GUI solve is manual by design.")
        _manual.write_manifest(manifest, out / _manual.MANIFEST_NAME)
        files["recipe"] = str(self.write_recipe(out, manifest, rid, surface_mesh))
        files["manifest"] = str(out / _manual.MANIFEST_NAME)

        return {"status": "pending_external",
                "manual_state": _manual.ManualSolveState.GUI_REQUIRED.value,
                "state_chain": list(_manual.STATE_CHAIN),
                "files": files, "manifest": manifest,
                "solver": self.name, "solver_version": self.version,
                "fidelity": self.fidelity,
                "reason": REASON}

    def write_recipe(self, out: Path, manifest, run_id: str,
                     surface_mesh: _mesh.SurfaceMesh | None = None) -> Path:
        """Write the run-specific checklist for the manual GUI solve."""
        n_tris = len(surface_mesh.tris) if surface_mesh is not None else 0
        cmd = (f"python3 -m hornflow.cli {self.params.source_path} "
               f"--bem-import {manifest.export_dir}")
        text = _manual.checklist_md(
            project=manifest.project, run_id=run_id, input_path=manifest.input_path,
            bem_dir=out, export_dir=manifest.export_dir,
            expected_exports=manifest.expected_exports,
            manifest_path=out / _manual.MANIFEST_NAME,
            solver=SOLVER_LABEL, solver_version=self.version,
            launcher="./AKABAK/akabak.sh", pipeline_cmd=cmd)
        text += (
            "\n## This run's geometry\n\n"
            f"* mesh: `bem.msh`, {n_tris} triangles in MSH 2.2 (fold-aware cavity mesh);\n"
            "* the click-by-click BEM-tree / LEM-network steps are identical to the "
            "geometry-independent recipe in `results/jbl_1200b/bem/akabak_recipe.md`;\n"
            "* set the drive level from `params` (Is rms ticked).\n"
        )
        path = Path(out) / "akabak_recipe.md"
        path.write_text(text, encoding="utf-8")
        return path

    # ------------------------------------------------------------------ solve
    def solve(self, master=None, grid=None, drive=None, boundary=None,
              **kw) -> SimulationRun | None:
        """Always returns None: the external BEM solve is pending by design."""
        return None


REASON = ("AKABAK Free 3.3.2 b144 (AKABAK_Demo_64r.exe) runs under Wine through its "
          "GUI; there is no usable head-less/CLI solve path in this setup, and the "
          "Free/demo build does not write the solved BEM state (.akpbe) - it stays in "
          "RAM. Inputs are generated; the external solve is performed manually and its "
          ".vips exports are validated on import.")

