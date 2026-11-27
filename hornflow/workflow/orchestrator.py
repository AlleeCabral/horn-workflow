"""Workflow orchestration (Stage gates) - the 16-stage pipeline.

A thin driver: it sequences the stages, enforces prerequisites, records stage
status, and writes artifacts.  All engineering logic lives in the domain /
physics / architecture / fold / manufacturing / report layers.
"""

from __future__ import annotations

import time
from pathlib import Path

from .. import architecture, config, fold
from ..architecture.base import DesignContext
from ..architecture.front_loaded import build_master
from ..critique import critic
from ..domain.evidence import code_version
from ..domain.ids import stable_id
from ..domain.state import DesignState, SCHEMA_VERSION
from ..domain.limits import Constraint, InputStatus
from ..io.artifacts import ArtifactStore, new_run_id, sha256_file, atomic_write
from ..io.logs import StageLogger
from ..io.state_store import run_input_path, run_params, save_state
from ..manufacturing.additive import AdditiveTransformer
from ..manufacturing.plywood import PlywoodTransformer
from ..manufacturing import exporters
from ..physics.feasibility import FeasibilityEvaluator
from ..physics.solvers.akabak import AkabakSolver
from ..physics.solvers.webster import WebsterSolver
from ..reporting import markdown
from ..reporting.limit_impact import build_limit_impacts
from ..viz import export as viz_export
from ..optimize import run_sensitivity
from . import gates as gate_mod
from .stages import Stage, ready


class Pipeline:
    def __init__(self, param_path, out_root="runs", limits=None, progress=None) -> None:
        self.param_path = Path(param_path)
        self.out_root = Path(out_root)
        self.limits = dict(limits or {})
        self.progress = progress or (lambda m: None)
        self.run_id = new_run_id("run")
        self.run_dir = self.out_root / self.run_id
        self.store = ArtifactStore(self.run_dir, self.run_id)
        self.log = StageLogger(self.run_dir, self.run_id)
        self.state = DesignState()
        self.params = None
        self.master = None
        self.feasibility = None
        self.arch_results = []
        self.scores = []
        self.fold_candidates = []
        self.runs = {}
        self.variants = []
        self.sensitivity = []
        self.gates = []
        self.findings = []
        self.viz_files = {}
        self.deliverables = self.run_dir / "deliverables"

    # ------------------------------------------------------------------ driver
    def run(self) -> dict:
        seq = [
            (Stage.INPUT_AUDIT, self.stage_input_audit),
            (Stage.LIMIT_IMPACT_ANALYSIS, self.stage_limit_impact),
            (Stage.PHYSICAL_FEASIBILITY, self.stage_feasibility),
            (Stage.ARCHITECTURE_SCREENING, self.stage_architecture),
            (Stage.IDEAL_ACOUSTIC_OPTIMIZATION, self.stage_ideal),
            (Stage.FOLD_TOPOLOGY_GENERATION, self.stage_fold_topology),
            (Stage.FOLD_GEOMETRY_VALIDATION, self.stage_fold_validation),
            (Stage.ONE_DIMENSIONAL_SIMULATION, self.stage_1d),
            (Stage.FOLD_AWARE_SIMULATION, self.stage_fold_aware),
            (Stage.THREE_DIMENSIONAL_VERIFICATION, self.stage_3d),
            (Stage.STRUCTURAL_SCREENING, self.stage_structural),
            (Stage.MANUFACTURING_TRANSFORMATION, self.stage_manufacturing),
            (Stage.CONSTRAINT_SENSITIVITY, self.stage_sensitivity),
            (Stage.INDEPENDENT_CRITIQUE, self.stage_critique),
            (Stage.FINAL_COMPARISON, self.stage_final),
            (Stage.REPORT_AND_EXPORT, self.stage_report),
        ]
        self.state.set_run_status("running")
        self._save()               # the run is visible (and readable) from the start
        for stage, fn in seq:
            if not ready(stage, self.state.stages):
                self.state.set_stage(stage.value, "blocked")
                self.log.log(stage.value, "blocked", severity="warning")
                self._save()
                continue
            t0 = time.time()
            self.progress(f"[{stage.value}]")
            try:
                result = fn()
            except KeyboardInterrupt:
                # Ctrl+C leaves a state behind saying it was interrupted, so the
                # run folder is not an invisible half-written directory (S6).
                self.state.set_run_status("interrupted")
                self.log.log(stage.value, "stage_interrupted", severity="warning")
                self._save()
                self.log.flush()
                raise
            except Exception as exc:                    # noqa: BLE001 - recorded, then raised
                self.state.set_stage(stage.value, "failed",
                                     detail=type(exc).__name__,
                                     failure={"category": "EXCEPTION",
                                              "failed_checks": [repr(exc)]})
                self.state.set_run_status("failed")
                self.log.log(stage.value, "stage_failed", severity="error",
                             detail=repr(exc))
                self._save()
                self.log.flush()
                raise
            status = "passed"
            if isinstance(result, str):
                status = result
            elif result is not None:                       # StageFailure
                status = "failed"
                self.state.set_stage(stage.value, "failed", detail=result.category,
                                     failure=result)
                self.log.log(stage.value, "stage_failed", severity="error",
                             detail=result.category)
                self._save()
                continue
            self.state.set_stage(stage.value, status)
            self.log.log(stage.value, "stage_done", duration_s=round(time.time() - t0, 3))
            self._save()
        return self._finalize()

    def _save(self) -> None:
        """Persist the state after every stage, so a crash is never invisible (S6)."""
        save_state(self.state, self.run_dir / "state.json")

    # ------------------------------------------------------------------ 1
    def stage_input_audit(self):
        # Snapshot first, then read the run's own bytes: a file edited between
        # the copy and the read could otherwise make the run mean something
        # other than what it recorded (review of #14).
        self.state.run.update({
            "run_id": self.run_id,
            "input_path": str(Path(self.param_path).resolve()),
            "python": __import__("platform").python_version(),
            "git_commit": None,
            "inputs": self._snapshot_inputs(),
        })
        self.params = run_params(self.run_dir, self.state)
        p = self.params
        _, self.master = build_master(p, "folded_horn")
        self.feasibility = FeasibilityEvaluator().evaluate(p, self.master)
        self.state.project = {"name": p.project, "author": p.meta.get("author", "")}
        self.state.driver = {
            "name": p.driver.name, "Re_ohm": p.driver.Re, "Fs_hz": p.driver.fs,
            "Qts": p.driver.Qts, "Vas_l": p.driver.Vas * 1e3,
            "Sd_cm2": p.driver.Sd * 1e4, "Xmax_mm": (p.driver.Xmax or 0) * 1e3,
            "Xmax_convention": "one_way",
        }
        self.state.constraints = {
            "acoustic": {"f_low_hz": p.target.f_low, "f_high_hz": p.target.f_high},
            "physical": {"depth_mm": (p.horn.length or 0) * 1e3,
                         "mouth_area_cm2": (p.horn.mouth_area or 0) * 1e4},
            "electrical": {"voltage_vrms": p.simulation.voltage},
            "manufacturing": {"method": "additive+plywood"},
        }
        self._constraint_list = [
            Constraint("passband_low_hz", p.target.f_low, "Hz", InputStatus.FIXED.value),
            Constraint("passband_high_hz", p.target.f_high, "Hz", InputStatus.FIXED.value),
            Constraint("depth_mm", (p.horn.length or 0) * 1e3, "mm", InputStatus.FIXED.value),
            Constraint("mouth_area_cm2", (p.horn.mouth_area or 0) * 1e4, "cm^2",
                       InputStatus.PREFERRED.value),
            Constraint("mouth_aspect", p.horn.mouth_aspect, "", InputStatus.PREFERRED.value),
            Constraint("rear_volume_cm3", p.driver.rear_volume * 1e6, "cm^3",
                       InputStatus.FIXED.value),
            Constraint("drive_voltage_vrms", p.simulation.voltage, "V",
                       InputStatus.PREFERRED.value),
            Constraint("Xmax_mm", (p.driver.Xmax or 0) * 1e3, "mm", InputStatus.FIXED.value),
        ]
        return "passed"

    def _snapshot_inputs(self) -> dict:
        """Copy the definition and its driver into the run, byte for byte (S7).

        Everything that later reads ``state.run["input_path"]`` used to depend on
        a file outside the run: edit it and the run silently meant something
        else.  The copy lives under ``inputs/`` and is described by its hash, so
        the run directory alone says what was built.
        """
        source = Path(self.param_path)
        dest = self.run_dir / "inputs"
        definition = dest / "definition.yaml"
        dest.mkdir(parents=True, exist_ok=True)
        atomic_write(definition, source.read_bytes())
        inputs = {
            "definition": "inputs/definition.yaml",
            "definition_sha256": sha256_file(definition),
            "driver": None,
            "driver_sha256": None,
            "limits": dict(self.limits),
            "code_version": code_version(),
        }
        reference = config.driver_reference(source)
        if reference is not None:
            written = Path(reference)
            if written.is_absolute():
                written = Path(written.name)
            if ".." in written.parts:
                raise ValueError(
                    f"the driver reference {reference!r} leaves the definition's "
                    "folder, so it cannot be snapshotted into the run")
            copied = dest / written
            if copied == definition:
                raise ValueError(
                    "the driver file is named definition.yaml, which is where the "
                    "definition snapshot goes; rename the driver file")
            driver = config.driver_path(source)
            if driver is None or not driver.is_file():
                raise FileNotFoundError(
                    f"the driver file {reference!r} referenced by {source.name} "
                    "was not found")
            # keep the reference as written, so it resolves inside the snapshot
            atomic_write(copied, driver.read_bytes())
            inputs["driver"] = copied.relative_to(self.run_dir).as_posix()
            inputs["driver_sha256"] = sha256_file(copied)
        return inputs

    # ------------------------------------------------------------------ 2
    def stage_limit_impact(self):
        self.limit_impacts = build_limit_impacts(self.params, self.master, self.feasibility)
        self.state.limit_impacts = self.limit_impacts
        from ..reporting.limit_impact import to_markdown
        self.store.put_text(to_markdown(self.limit_impacts), kind="report",
                            name="limit_impact.md", stage=Stage.LIMIT_IMPACT_ANALYSIS.value)
        return "passed"

    # ------------------------------------------------------------------ 3
    def stage_feasibility(self):
        self.state.feasibility = self.feasibility.to_dict()
        return "passed"

    # ------------------------------------------------------------------ 4
    def stage_architecture(self):
        ctx = DesignContext(params=self.params, feasibility=self.feasibility,
                            master=self.master)
        self.arch_results = architecture.registry.screen(ctx)
        self.scores = architecture.registry.score(self.arch_results)
        self.state.architecture_candidates = [r.to_dict() for r in self.arch_results]
        return "passed"

    def _refresh_scores(self):
        """Attach 1-D simulation metrics to horn candidates and re-score."""
        run = self.runs.get(self.master.candidate_id)
        if run is not None:
            for r in self.arch_results:
                if r.master is not None:        # horn-class candidates
                    r.metrics = dict(r.metrics)
                    r.metrics.update({
                        "spl_mean_db": run.metrics.get("spl_mean_db"),
                        "spl_variation_db": run.metrics.get("spl_variation_db"),
                        "ze_min_ohm": run.metrics.get("ze_min_ohm"),
                        "excursion_rms_mm": run.metrics.get("excursion_rms_mm"),
                        "excursion_peak_mm": run.metrics.get("excursion_peak_mm"),
                    })
        self.scores = architecture.registry.score(self.arch_results)
        self.state.architecture_candidates = [r.to_dict() for r in self.arch_results]

    # ------------------------------------------------------------------ 5
    def stage_ideal(self):
        self.state.reference_profiles = [self.master.to_dict()]
        return "passed"

    # ------------------------------------------------------------------ 6
    def stage_fold_topology(self):
        limits = {"f_passband_max": self.params.target.f_high,
                  "c": self.params.simulation.c,
                  "wall_mm": float(self.limits.get("wall_mm", 18.0)),
                  "min_bend_radius_m": float(self.limits.get("min_bend_radius_m", 0.0)),
                  "max_fold_count": int(self.limits.get("max_fold_count", 99)),
                  "area_rms_tol": float(self.limits.get("area_rms_tol", 0.15))}
        self._fold_limits = limits
        self.fold_candidates = []
        for gen in fold.generators():
            self.fold_candidates.extend(gen.generate(self.master, limits))
        self.state.fold_candidates = [c.to_dict() for c in self.fold_candidates]
        return "passed"

    # ------------------------------------------------------------------ 7
    def stage_fold_validation(self):
        valid = [c for c in self.fold_candidates if c.valid]
        if not valid:
            from ..domain.failures import StageFailure
            return StageFailure(
                stage=Stage.FOLD_GEOMETRY_VALIDATION.value, category="GEOMETRY",
                failed_checks=["no valid fold preserves area law and clearances"],
                recoverable=False,
                recommended_upstream_revision="relax min_bend_radius or fold count",
                evidence={"n_candidates": len(self.fold_candidates)})
        # choose the most compact valid fold (highest eta_pack, then fewest bends)
        valid.sort(key=lambda c: (-c.packaging["eta_pack"], len(c.bends)))
        self.chosen_fold = valid[0]
        self._valid_folds = valid
        return "passed"

    # ------------------------------------------------------------------ 8
    def stage_1d(self):
        # ideal reference (straight) and the folded acoustic master share physics
        run = WebsterSolver(self.params).solve(master=self.master,
                                               candidate_id=self.master.candidate_id)
        self.runs[self.master.candidate_id] = run
        self.state.simulation_runs = [run.to_dict()]
        self._refresh_scores()
        return "passed"

    # ------------------------------------------------------------------ 9
    def stage_fold_aware(self):
        # area law + length preserved -> 1-D response equals the reference;
        # bend effects are 3-D and are handled by bend screening + stage 10.
        self.folded_run = self.runs[self.master.candidate_id]
        self.folded_run.fold_id = self.chosen_fold.fold_id
        self.state.validation = {
            "fold_id": self.chosen_fold.fold_id,
            "area_law_rms": self.chosen_fold.area_report.rms,
            "length_error_m": self.chosen_fold.centreline.length - self.master.length,
            "fold_aware_1d": "equals reference (area law + path preserved)",
        }
        return "passed"

    # ------------------------------------------------------------------ 10
    def stage_3d(self):
        from ..manufacturing import meshbuild as _mb
        cav = _mb.cavity_mesh(self.chosen_fold, k=4)
        ak = AkabakSolver(self.params)
        info = ak.write_inputs(cav, self.deliverables / "bem", run_id=self.run_id,
                               project=self.params.project,
                               input_path=run_input_path(self.run_dir, self.state),
                               run_dir=self.run_dir)
        self.state.validation["bem_inputs"] = info["files"]
        self.state.validation["bem_status"] = info["status"]
        self.state.validation["bem_manual"] = {
            "state": info["manual_state"],
            "chain": info["state_chain"],
            "solver": info["solver"],
            "solver_version": info["solver_version"],
            "export_dir": info["manifest"].export_dir,
            "manifest": str(Path(info["files"]["manifest"])),
            "reason": info["reason"],
            "next_action": "run the GUI solve, export .vips, then re-run with --bem-import",
        }
        self.log.log(Stage.THREE_DIMENSIONAL_VERIFICATION.value, "gui_required",
                     severity="warning", detail=info["reason"],
                     artifacts=[info["files"].get("recipe", ""),
                                info["files"].get("manifest", "")])
        # Optional stage: inputs generated, external (manual) solve pending.  The
        # candidate is NOT validated - that only happens after a .vips import plus
        # comparison (see hornflow.physics.solvers.bem_manual).
        return "skipped"

    # ------------------------------------------------------------------ 11
    def stage_structural(self):
        pkg = self.chosen_fold.packaging
        self.state.validation["structural_screening"] = {
            "evidence": "STRUCTURAL_SCREENING",
            "max_span_m": max(pkg["bbox_w_m"], pkg["bbox_h_m"], pkg["bbox_d_m"]),
            "surface_area_m2": pkg["surface_area_m2"],
            "centre_of_mass_note": "driver low and central recommended",
            "brace_spacing_note": "keep brace spacing within a 2x thickness span rule",
        }
        return "passed"

    # ------------------------------------------------------------------ 12
    def stage_manufacturing(self):
        from ..manufacturing import meshbuild as _mb
        c = self.chosen_fold
        wall = float(self.limits.get("wall_mm", 18.0))
        add = AdditiveTransformer().transform(
            c, {"wall_mm": wall, "build_volume_mm": (350, 350, 350)})
        shell = _mb.shell_mesh(c, wall_mm=wall, k=4)
        stl = self.deliverables / "printed.stl"
        exporters.write_stl(shell, stl, "printed")
        add.artifacts["stl"] = str(stl)
        ply = PlywoodTransformer().transform(
            c, {"master": self.master,
                "facet_len_mm": float(self.limits.get("facet_len_mm", 250.0))})
        self._deferred = {kind: str(exporters.deferred_stub(kind, self.deliverables, reason))
                          for kind, reason in exporters.DEFERRED.items()}
        self.variants = [add, ply]
        self.state.manufacturing_variants = [v.to_dict() for v in self.variants]
        return "passed"

    # ------------------------------------------------------------------ 13
    def stage_sensitivity(self):
        # read the run's own snapshot, not the file it was started from (S7)
        snapshot = bool((self.state.run or {}).get("inputs"))
        self.sensitivity = run_sensitivity(run_input_path(self.run_dir, self.state),
                                           snapshot=snapshot)
        self.state.sensitivity_runs = self.sensitivity
        return "passed"

    # ------------------------------------------------------------------ 14
    def stage_critique(self):
        self.gates = gate_mod.hard_gates(self.params, self.feasibility,
                                         list(self.runs.values()), self.variants,
                                         self.limits)
        self.findings = critic.review(
            self.state, gates=self.gates, runs=list(self.runs.values()),
            fold_candidates=self.fold_candidates, variants=self.variants,
            scores=self.scores)
        self.state.critic_findings = [f.to_dict() for f in self.findings]
        if critic.rejected(self.findings):
            self.log.log(Stage.INDEPENDENT_CRITIQUE.value, "recommendation_rejected",
                         severity="warning",
                         detail="; ".join(f.check for f in self.findings
                                          if f.severity == "reject" and not f.passed))
        return "passed"

    # ------------------------------------------------------------------ 15
    def stage_final(self):
        self.best_folded = self.chosen_fold
        self.best_overall = self.scores[0] if self.scores else None
        self.state.final_recommendations = {
            "best_folded_horn": {
                "family": self.best_folded.family, "fold_id": self.best_folded.fold_id,
                "valid": self.best_folded.valid,
                "area_law_rms": self.best_folded.area_report.rms,
            },
            "best_overall": self.best_overall,
            "hard_gates_passed": all(g.passed for g in self.gates),
        }
        return "passed"

    # ------------------------------------------------------------------ 16
    def stage_report(self):
        # The viewer shell embeds the app view model. Both are written in
        # _finalize(), after the state is saved, so the embedded snapshot and
        # state.json can never disagree; here we only record the expected paths.
        vdir = self.deliverables / "viewer"
        self.viz_files = {"glb": vdir / "scene.glb", "viewer": vdir / "viewer.html",
                          "vendor": vdir / "vendor", "ui": vdir / "ui",
                          "app_view": vdir / "app_view.json"}
        ctx = {
            "schema_version": SCHEMA_VERSION, "run_id": self.run_id,
            "params": self.params, "master": self.master, "feasibility": self.feasibility,
            "constraints": self._constraint_list, "limit_impacts": self.limit_impacts,
            "scores": self.scores, "fold_candidates": self.fold_candidates,
            "best_folded": self.best_folded, "runs": self.runs,
            "best_overall": self.best_overall, "validation": self.state.validation,
            "variants": self.variants, "sensitivity": self.sensitivity,
            "gates": self.gates, "critic": self.findings, "viz_files": self.viz_files,
        }

        text = markdown.render(ctx)
        self.store.put_text(text, kind="report", name="report.md", area="deliverables",
                            stage=Stage.REPORT_AND_EXPORT.value)
        return "passed"

    # ------------------------------------------------------------------
    def _finalize(self) -> dict:
        # The pipeline ran to its end; a stage may still have failed (a typed
        # StageFailure is data) or been blocked, and the stage record says which.
        self.state.set_run_status("completed")
        save_state(self.state, self.run_dir / "state.json")
        self.log.flush()
        # Now that state.json and logs.jsonl are on disk, emit the read-only view
        # model and embed it in the viewer shell (the Viewer tab plus the
        # Workflow/Results tabs).  Deferred import: app.view reads workflow.stages,
        # which would otherwise be a circular import.
        try:
            from ..app import view as app_view_mod
            view = app_view_mod.build_view(self.state, run_dir=self.run_dir,
                                           host="static")
            self.viz_files = viz_export.write_viewer(
                self.chosen_fold, self.deliverables / "viewer",
                title=f"{self.params.project} - {self.chosen_fold.family}",
                app_view=view)
            app_view_mod.emit_view(view, self.deliverables / "viewer" / "app_view.json")
            self.state.visualization_artifacts = [
                {"name": "viewer.html", "path": "deliverables/viewer/viewer.html",
                 "kind": "html"},
                {"name": "scene.glb", "path": "deliverables/viewer/scene.glb",
                 "kind": "gltf"},
                {"name": "app_view.json", "path": "deliverables/viewer/app_view.json",
                 "kind": "view-model"},
            ]
            save_state(self.state, self.run_dir / "state.json")
        except Exception as exc:                      # noqa: BLE001 - never lose a run
            self.log.log(Stage.REPORT_AND_EXPORT.value, "app_view_failed",
                         severity="warning", detail=str(exc))
            self.log.flush()
        return {
            "run_id": self.run_id,
            "run_dir": str(self.run_dir),
            "deliverables": str(self.deliverables),
            "stages": dict(self.state.stages),
            "best_folded": (self.best_folded.family
                            if getattr(self, "best_folded", None) else None),
            "best_overall": (self.best_overall.get("architecture_id")
                             if getattr(self, "best_overall", None) else None),
            "n_fold_candidates": len(self.fold_candidates),
            "report": str(self.deliverables / "report.md"),
            "viewer": str(self.viz_files.get("viewer")) if self.viz_files else None,
        }


def run_pipeline(param_path, out_root="runs", limits=None, progress=None) -> dict:
    """Convenience entry point: run the whole pipeline and return a summary.

    The definition is validated first, before the run directory exists: a typo
    must not leave a half-written run behind (audit P12).
    """
    config.load(param_path)
    return Pipeline(param_path, out_root=out_root, limits=limits,
                    progress=progress).run()


