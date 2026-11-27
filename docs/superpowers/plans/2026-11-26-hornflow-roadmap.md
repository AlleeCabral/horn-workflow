# HornFlow Roadmap Implementation Plan (master)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn HornFlow into a trustworthy, interactive horn design tool. It gets a tuning bench, a design diary, honesty labels, interactive bending, a headless BEM solver, and build outputs that include a telescoping printed horn for transport.

**Architecture:** The work runs in eight phases on top of the existing Python core and the offline Three.js viewer.
- Phase 0 makes the run record and the report trustworthy. Every later phase depends on it.
- Each later phase is a separate sub-plan, expanded with superpowers:writing-plans right before it starts, against the code as it is then.

**Tech Stack:**
- Python 3.10 to 3.12; numpy, scipy, PyYAML, matplotlib; pytest and hypothesis.
- A stdlib HTTP host, and Three.js r128 (vendored).
- Optional: bempp-cl and gmsh for Phase 3, Pyodide for Phase 7.

**Spec:** `docs/superpowers/specs/2026-11-26-hornflow-roadmap-design.md` (with `docs/audit/2026-11-26-hornflow-audit.md` as evidence).

## Global Constraints

- **Python versions:** 3.10, 3.11 and 3.12. Production dependencies are only `numpy>=1.24`, `scipy>=1.10`, `PyYAML>=5.4` and `matplotlib>=3.6`.
- **Optional dependencies:** listed in `requirements-optional.txt`, imported lazily. When one is missing, raise `DependencyMissing(name, purpose)` with an install hint.
- **Branches:** every change goes on a branch named `feat/<topic>`, `fix/<topic>` or `docs/<topic>`, through a pull request. CI must be green. Never commit to `main`.
- **Excursion conventions:** all rms/peak and Xmax conversions go through `hornflow/domain/excursion.py` (ADR-0012). No inline `sqrt(2)`.
- **Model owns completion:** the browser never computes completion, verdicts or physics (ADR-0013, ADR-0014). It renders what the model returns.
- **State writes:** every `state.json` write goes through `hornflow/io/state_store.py`. That module is the only writer, and it holds the state lock.
- **Evidence labels:** `ANALYTICAL_ESTIMATE`, `ONE_D_SIMULATION`, `BEM_HEADLESS`, `BEM_AKABAK`, `MEASURED` (introduced in Phase 1). Until Phase 1 the existing labels stay.
- **Hardcoded paths:** none in code or generated files. Paths inside a run folder are stored relative to that folder.
- **User-facing text:** no em dashes or en dashes in generated reports and UI copy (owner preference).

## Review Focus

Phase 0 tests exercise these directly; later phases must keep them covered.

1. **Two browser tabs on the same project:** a write in one tab never lands in the run shown in the other. Covered by Phase 0 Task 3.
2. **A run interrupted by Ctrl+C or a crash:** the run folder says "interrupted" and appears in the run list. It never vanishes. Covered by Phase 0 Task 7.
3. **A YAML file with a typo or a unit slip** (`lenght:`, or a throat in metres): the tool stops with a one-line error naming the key. It must not exit 0 with nonsense. Covered by Phase 0 Task 12.
4. **Re-importing a different, stale or foreign BEM export into a validated run:** the earlier verdict is kept and the attempt is recorded as failed. Covered by Phase 0 Task 5.
5. **A design where folded and straight horns are acoustically identical:** the report says there is no acoustic winner, and does not call the folded horn "best overall". Covered by Phase 0 Task 9.

---

## Superpowers workflow (applies to every phase)

| When | Skill | What it does here |
|---|---|---|
| Before a phase's sub-plan, when it has an open owner decision or new UX | `superpowers:brainstorming` | Settles D1 to D8 and UI shape; produces or updates the phase design section in the spec |
| Before code in each phase | `superpowers:writing-plans` | Expands the phase outline below into bite-sized tasks against the then-current code (Phase 0 is already expanded) |
| Start of each phase | `superpowers:using-git-worktrees` | One worktree and branch per phase (`fix/phase0-trustworthy-core`, `feat/phase1-bench-diary`, ...) |
| Every task | `superpowers:test-driven-development` | Failing test first; the plan names each test |
| Executing a phase | `superpowers:subagent-driven-development` (default) or `superpowers:executing-plans` | Task by task, with a fresh reviewer per task |
| Independent task groups | `superpowers:dispatching-parallel-agents` | Phase 0 groups A (persistence and app) and B (physics and report) run in parallel; Phase 4 plywood and telescoping run in parallel |
| Any failing test or surprise | `superpowers:systematic-debugging` | Root cause before any fix |
| End of each task and phase | `superpowers:requesting-code-review` | Reviewer checks against the spec and the audit finding IDs |
| Handling review comments | `superpowers:receiving-code-review` | Verify each comment technically before changing code |
| Before saying "done", committing or opening a PR | `superpowers:verification-before-completion` | Run the full suite and paste the output; no claims without evidence |
| End of each phase | `superpowers:finishing-a-development-branch` | Merge decision, PR text and cleanup |
| Phase 6 | `superpowers:writing-skills` | Creates the project skill `hornflow-dev` (conventions, test commands, units, evidence labels) so future sessions start oriented |
| When a session goes off track | `superpowers:diagnosing-superpowers` | Diagnoses repeated work or ignored plans |
| Session start | `superpowers:using-superpowers` | Skill discovery |

**Prerequisites before Phase 0:**
1. Push access to `AlleeCabral/horn-workflow`. The current session has read-only access.
2. A local environment with the dev dependencies:

```bash
python3 -m pip install -r requirements.txt -r requirements-dev.txt
```

3. Then the baseline, recorded as the starting point:

```bash
python3 tests/test_theory.py && python3 -m pytest tests -q
```

Expected: 147/147 legacy checks pass. pytest shows the known 34 errors in `tests/test_app_api.py` (audit T1; fixed by Phase 0 Task 15).

---

## Phase map and dependencies

```
Phase 0 Trustworthy core ──┬─> Phase 1 Bench + Diary + Honesty labels ──┬─> Phase 2 Interactive bending
                           │                                            ├─> Phase 5 Measurement loop
                           ├─> Phase 3 Headless BEM ────────────────────┤
                           └─> Phase 6 Consolidation + docs (rolling)   └─> Phase 4 Build companion + telescoping
Phase 7 Nothing to install: after Phase 1 (Stage 1 only)
```

| Phase | Sub-plan file | Size | Owner decisions needed first |
|---|---|---|---|
| 0 | `2026-11-26-phase0-trustworthy-core.md` (ready) | L (16 tasks) | D1, D2, D4 (placeholders allowed) |
| 1 | `phase1-bench-diary-honesty.md` (to expand) | L | none |
| 2 | `phase2-interactive-bending.md` | L | D3, D6 |
| 3 | `phase3-headless-bem.md` | L | D7 |
| 4 | `phase4-build-companion-telescoping.md` | L | D5, D8 |
| 5 | `phase5-measurement-loop.md` | M | none |
| 6 | `phase6-consolidation-docs.md` | M, rolling | none |
| 7 | `phase7-zero-install.md` | M | none |

---

## Phase 1: Tuning bench, design diary, honesty labels (outline)

**Files:**
- Create `hornflow/domain/evidence.py` (extend the existing module).
- Create `hornflow/app/preview.py`, `hornflow/app/diary.py`, `hornflow/viz/viewer/ui/charts.js`.
- Modify `hornflow/app/server.py`, `hornflow/app/actions.py`, `hornflow/app/view.py`, `hornflow/reporting/markdown.py`, `hornflow/viz/viewer/ui/app.js`, `index.html`.

**Outline:**
- [ ] **Task 1.1 Evidence model.**
  - Add the enum `Evidence` with values `ANALYTICAL_ESTIMATE < ONE_D_SIMULATION < BEM_AKABAK = BEM_HEADLESS < MEASURED`, plus `weakest(*labels) -> Evidence`.
  - Every metric written to `state.json` becomes `{"value": x, "unit": u, "evidence": label}`. This is state schema 1.3, with an in-memory migration that labels old numbers `ONE_D_SIMULATION` or `ANALYTICAL_ESTIMATE` by their source field.
  - Test: `test_report_claim_never_exceeds_weakest_input`.
- [ ] **Task 1.2 Report claim ceiling.**
  - `reporting/markdown.py` renders each headline with its label.
  - An "architecture winner" sentence requires a decisive raw score (Phase 0 Task 9) and states its evidence level.
- [ ] **Task 1.3 Charts.**
  - `charts.js` draws SVG line charts: SPL, |Ze|, excursion peak with an Xmax line, phase, group delay. Data comes from `app_view.json["curves"]`, which `view.py` adds from `simulation_runs[0]`.
  - No library. Log frequency axis.
  - DOM test in `tests/test_workflow_ui.py` style: chart present, Xmax line drawn at the one-way peak value.
- [ ] **Task 1.4 Results tab v1.** Curves, the architecture table showing ties honestly, the sensitivity table, and evidence badges. This replaces the placeholder.
- [ ] **Task 1.5 Preview endpoint.**
  - `POST /api/preview {"run_id", "overrides": {"horn.length": 1.6, ...}}` calls `config.load(definition, overrides)` and `WebsterSolver`. It returns curves and metrics labelled `ONE_D_SIMULATION`.
  - It persists nothing. Overrides are checked against an allow-list of slider keys with bounds taken from config validation (Phase 0 Task 12).
  - Test: the response arrives within 300 ms on the JBL definition, the run is not modified, and an unknown key gives 400.
- [ ] **Task 1.6 Bench UI.** Sliders for `horn.length`, mouth area or `fc`, `throat_diameter`, `profile`, `simulation.voltage` and the rear volume. Debounced at 150 ms. The ghost curve is the run's stored result. "Save as new run" freezes the overrides through the existing brief/freeze path.
- [ ] **Task 1.7 Diary model.**
  - `app/diary.py` provides:
    - `timeline(run_root) -> list[RunSummary]`;
    - `diff(run_a, run_b) -> InputDiff`, comparing snapshotted definitions from Phase 0 Task 8;
    - `overlay(run_ids) -> curves`, which refuses mismatched grids or schemas and says so.
  - Endpoints: `GET /api/diary`, `GET /api/diary/diff?a=&b=`.
- [ ] **Task 1.8 Diary UI.** A Diary tab with a vertical timeline, a two-run diff table, an overlay chart, and a decision note per run (stored through the decision log).
- [ ] **Task 1.9 Retire `handoff.md`.**
  - The diary has a "current state" card: latest run, open decisions, next action.
  - `handoff.md` moves to `docs/archive/`.

## Phase 2: Interactive bending (outline)

**Files:**
- Create `hornflow/fold/path_spec.py`, `hornflow/fold/realised.py`, `hornflow/viz/viewer/vendor/TransformControls.js` (r128) and `hornflow/viz/viewer/ui/bend.js`.
- Modify `hornflow/fold/evaluate.py`, `hornflow/fold/base.py`, `hornflow/workflow/orchestrator.py`, `hornflow/app/server.py`, `hornflow/app/actions.py`.

- [ ] **Task 2.1 Non-circular fold validation (audit P2).**
  - `fold/realised.py`: `realised_area(centreline, walls) -> np.ndarray` measures the cross-section from the generated wall polygons, not from the target law.
  - `evaluate.py` compares the realised area with the master law.
  - Test: a deliberately pinched bend fails `area_law_rms`.
- [ ] **Task 2.2 Fold ids include all generator parameters (audit U5).** Old ids are mapped through a migration note.
- [ ] **Task 2.3 Path spec.**
  - `PathSpec = list[Leg(length_m) | Arc(radius_m, angle_deg, plane_deg)]` and `PathSpec.to_centreline(total_length_m) -> np.ndarray`.
  - The last leg absorbs the length difference, so the total length is exact (ADR-0007).
  - The existing J, U and serpentine generators become PathSpec presets.
- [ ] **Task 2.4 Live checks.**
  - `fold/live.py`: `check_path(spec, master, limits) -> LiveReport` with fields `bbox_m`, `clearance_ok`, `self_intersection`, `bends[i].risk`, `min_radius_ok`, `panel_count` and `est_mass_kg`.
  - Fast enough for drag: 50 ms or less per call on the JBL design.
  - Fold selection follows D3.
- [ ] **Task 2.5 Bend endpoint.** `POST /api/bend/preview {run_id, path_spec}` returns the LiveReport plus GLB bytes (base64) of the cavity.
- [ ] **Task 2.6 Bend editor UI.**
  - Handles on each bend in the Viewer. Angle and radius inputs. Risk colour per bend. Box outline with dimensions.
  - "Save as fold candidate" stores the PathSpec in the brief and starts a run.
- [ ] **Task 2.7 Honest acoustics label.** The 1-D response is shown as "unchanged by bending (1-D model)". Bend risk drives a "needs 3-D check" badge until Phase 3 provides `BEM_HEADLESS`.

## Phase 3: Headless BEM (outline)

**Files:**
- Create `hornflow/physics/solvers/bempp.py`, `hornflow/physics/solvers/registry.py`, `hornflow/physics/radiation.py`, `tests/test_bem_headless.py` (skipped without bempp-cl) and `tests/test_mesh_quality.py`.
- Modify `hornflow/mesh.py`, `hornflow/manufacturing/meshbuild.py`, `hornflow/response.py`, `hornflow/physics/solvers/base.py`, `hornflow/workflow/orchestrator.py`, `hornflow/workflow/bem_import.py`, `hornflow/app/view.py` and `requirements-optional.txt`.

- [ ] **Task 3.1 Mesh quality tests and fixes (audit B7).**
  - `mesh_report(msh) -> {closed, consistent_orientation, outward, volume_m3, max_edge_m, groups}`.
  - Fix the interface fan winding.
  - Size elements so that `max_edge` is no more than `lambda(f_max)/6`.
  - Tests: the straight-horn volume is within 1% of the analytic 0.680 m³; there are no reversed faces.
- [ ] **Task 3.2 Folded body mesh (audit B3).** A closed, outward, thick-wall body with tagged `throat` and `wall` groups (and `mouth` for the interface variant), built from `meshbuild.shell_mesh`.
- [ ] **Task 3.3 Injectable radiation (audit B9).**
  - `response.simulate(params, *, throat_impedance=None, transfer=None)`. The default is Webster.
  - `physics/radiation.py` defines `RadiationModel` with the protocol `throat_impedance(f) -> complex[]` and `pressure_per_volume_velocity(f, points) -> complex[,]`.
- [ ] **Task 3.4 Solver registry and result record.**
  - `SimulationRun` gains `solver`, `solver_version`, `mesh_sha256`, `n_elements`, `max_edge_over_lambda`, `formulation`, `radiation_condition`, `observation_points`, `z_throat`, `p_obs`, `c`, `rho` and `settings_hash`.
  - Stage 10 runs the registered solver, or records `skipped: solver unavailable`.
- [ ] **Task 3.5 bempp adapter.** Helmholtz exterior with Burton-Miller (switchable), and an interior/exterior interface variant to match AKABAK. Driven by unit volume velocity on `throat`.
- [ ] **Task 3.6 Validation harness against `Rad1_23Sept26`.**
  - Stage A, acoustics only: RadImp1, and Mic1/LE4.
  - Stage B, coupled: LE2 |Ze|, LE1, Mic1 SPL.
  - Solve on the 24 exact frequencies. Run a mesh convergence check at lambda/6 and lambda/10.
  - Tolerances per D1. Negative controls (`Jbl1200B_horn_19Sept26`, `Rad1_22Sept26`) must fail.
- [ ] **Task 3.7 Irregular-frequency probe.** A 1 Hz sweep from 100 to 130 Hz, with and without Burton-Miller, plus a power-balance check.
- [ ] **Task 3.8 The -8.6 dB question.** Solve baffled and free-standing on the same mesh and record the result. Per D7, decide the Stage 1 reference condition and close or keep open the offset in the diary.
- [ ] **Task 3.9 Generalise import.** "External solver result" import for AKABAK cross-checks, with the Phase 0 provenance rules. Delete the states that are no longer reachable (`INPUTS_GENERATED`, `MANUAL_SOLVE_COMPLETED`), with an in-memory migration.
- [ ] **Task 3.10 Viewer.** A mouth-plane or field colour map (vertex colours in the GLB writer) and polar plots in SVG.

## Phase 4: Build companion and telescoping transport horn (outline)

**Files:**
- Create `hornflow/manufacturing/cutlist.py`, `hornflow/manufacturing/dxf.py`, `hornflow/manufacturing/telescoping/{segments.py, joints.py, tiles.py, report.py}` and `hornflow/viz/viewer/ui/assembly.js`.
- Modify `hornflow/manufacturing/plywood.py`, `hornflow/manufacturing/additive.py`, `hornflow/physics/` (step model) and `hornflow/workflow/orchestrator.py`.

- [ ] **Task 4.1 Plywood cut list (audit U3).**
  - `cutlist(fold_candidate, sheet_mm=18) -> list[Panel(name, w_mm, h_mm, bevel_deg, qty)]`, using the real bend angles in place of `180/(m-1)`.
  - CSV output, plus a DXF with R12 LINE entities (stdlib writer).
- [ ] **Task 4.2 Exploded assembly view.** Panel order, an "explode" slider, step numbers.
- [ ] **Task 4.3 Telescoping segmentation.**
  - `segment(master, n, wall_mm, clearance_mm, overlap_mm) -> list[Segment(z0, z1, inner_profile, outer_profile)]`.
  - Constraint: for every z, segment i's outer surface, slid toward the mouth into segment i+1, stays at least `clearance_mm` inside segment i+1's inner surface.
  - Objective: minimise collapsed length (the longest segment), subject to the D8 piece mass and the bed size after tiling.
  - Straight horns only. A folded master is rejected with a clear message.
- [ ] **Task 4.4 Joint design.** A tapered friction seal over `overlap_mm`, a gasket groove (O-ring cord size from a table), and a bayonet or over-centre latch. The pressure at each joint is taken from the 1-D model at the D2 drive level, to rank the seal requirement.
- [ ] **Task 4.5 Step acoustics.** Model each joint's area step as a short discontinuity in the Webster chain. Report the SPL deviation against the smooth horn, labelled `ONE_D_SIMULATION`.
- [ ] **Task 4.6 Tiling for the printer bed.** Split each segment into tiles of 350 mm or less (per D8) with interlocking seams. Report `part_count`, the true per-part bounding box (fixes audit F13) and mass per part.
- [ ] **Task 4.7 Stiffness.** Rib placement for large panels near the mouth, with a first-mode estimate for each panel against the passband. Panels below `f_high` are flagged.
- [ ] **Task 4.8 Transport report and collapse animation.** Extended and collapsed dimensions, collapsed volume, mass per piece, assembly steps and time. The viewer animates collapse and extend.
- [ ] **Task 4.9 Outdoor checklist.** Material (PETG or ASA, from D8), UV and water notes, handles, feet, and a strap anchor. All are generated into the build sheet.

## Phase 5: Measurement loop (outline)

- [ ] **Task 5.1 REW importer.** `hornflow/measure/rew.py`: `read_rew_txt(path) -> Measurement(freq_hz, spl_db, phase_deg|None, kind, distance_m, drive_vrms)`. Rejects files missing a unit or distance unless the user provides one.
- [ ] **Task 5.2 Alignment.** Distance and level normalisation to the model's observation distance and drive level. The rules are explicit and recorded.
- [ ] **Task 5.3 Compare.** Measured against 1-D and against BEM curves, with deviation bands. Labelled `MEASURED`. Stored per run in the diary.
- [ ] **Task 5.4 UI.** An import panel in Results, and overlays in the bench.

## Phase 6: Consolidation and docs (rolling, outline)

- [ ] **Task 6.1 One metrics module.** `hornflow/metrics.py` with `band_metrics(f, spl, f_lo, f_hi) -> BandMetrics`, used by `advise.py`, `sweep.py`, `webster.py`, `sensitivity.py` and `box_models.py` (audit P9, workflow 7).
- [ ] **Task 6.2 One import path.** The legacy `run_workflow.py --bem-import` delegates to `workflow/bem_import.py`.
- [ ] **Task 6.3 Commands.** Advise and sweep become pipeline commands (`hornflow.cli advise|sweep|build`). `run_workflow.py` becomes a thin compatibility front end; the baseline test still passes.
- [ ] **Task 6.4 Docs.**
  - A README "start here"; `docs/akabak.md` (the ground rules, cross-check only); `docs/schema.md`.
  - Archive `history.md` (log), `handoff.md`, `docs/ui-two-tab-mvp.md` and `docs/jira-issue-flow.md`.
  - Amend ADR-0001 and ADR-0005; add ADR-0016 (headless BEM) and ADR-0017 (evidence labels).
- [ ] **Task 6.5 GitHub Issues.**
  - Labels `bug`, `physics`, `bem`, `ux`, `docs`, `chore`, `needs-decision`, `S`, `M`, `L`.
  - Milestones "Trustworthy outputs", "Headless BEM", "Usable app".
  - Create the 20 backlog issues from audit section G, and a pinned "Current state" issue. Needs push access and the `gh` CLI.
- [ ] **Task 6.6 Project skill.** Use `superpowers:writing-skills` to create `.claude/skills/hornflow-dev/SKILL.md`: test commands, units and conventions, evidence labels, where state lives, and the "model owns completion" rule.
- [ ] **Task 6.7 Hook setup.** CONTRIBUTING gains `git config core.hooksPath .githooks`.

## Phase 7: Nothing to install (outline, optional)

- [ ] **Task 7.1** Check that `theory.py`, `response.py` and `config.py` import under Pyodide (numpy, scipy and PyYAML are available as Pyodide packages). List any blockers.
- [ ] **Task 7.2** `tools/build_standalone.py` writes `hornflow-standalone.html`: the viewer, the Pyodide loader (vendored, pinned version), the Stage 1 sources, the example definitions, and the bench running in a web worker.
- [ ] **Task 7.3** Offline test: the page loads with network disabled after the first open, using a vendored Pyodide distribution. Document the file size.
