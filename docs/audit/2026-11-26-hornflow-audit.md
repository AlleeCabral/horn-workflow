# HornFlow audit report

Repository: AlleeCabral/horn-workflow, `main` at f420496 (shallow clone, single commit visible).
Scope and rules: the brief in `hornflow-audit-prompt.md` (headless BEM direction already decided).
Nothing in the repository was modified. Commands ran only on a throwaway copy.

Line references were re-checked against the checkout. Where a finding was reproduced by a script on the copy, it says "reproduced".

---

## A. Overall assessment

**Stage 1 physics is sound; the layers built around it are not yet trustworthy.** The Webster core (`theory.py`, `response.py`) matches the paper's equations, passes its 147 checks, and the rms/peak excursion fix from October is complete in behaviour. The problems sit in the layers built on top: scoring, sensitivity, folding, the BEM import, and the local app.

**Persisted state (the run folder is the database).** Writes use temp-file-then-rename, but every writer in one process uses the same temp name, there is no lock around read-modify-write, and the state is only written at the very end of a run. Two concurrent actions in the app can corrupt `state.json` (reproduced), and the app then shows the run as "first run" without an error. A run cannot be reproduced from its folder: the definition and driver files are not snapshotted, the code version is always `None`, and the import re-reads the YAML from disk.

**Business (design) correctness.** Several outputs state things the model does not support:
- the folded horn is declared "best overall" only because of the preference bonus, while its numbers are identical to the straight horn (ADR-0005 broken);
- fold validation is circular, so every fold passes the area-law check by construction;
- the sensitivity stage reports a cut-off of 20 Hz for every case and "no effect" for levers that were silently overridden;
- displacement-limited SPL is 3 dB optimistic;
- free-space DI is wrong;
- the excursion gate is evaluated only at 2.83 V, so "hard safety gate PASS" says nothing about real drive levels.

**Stage 2 / AKABAK.** The manual loop has 17 steps, 12 of them manual, and several can fail silently. Most importantly, **no folded geometry has ever been BEM-solved**: the pipeline's folded cavity mesh is open at both ends with a single `wall` group and cannot be set up as the recipe says, and every AKABAK reference result comes from the legacy straight mesh. The importer can mark a design `BEM_VALIDATED` from exports of a different geometry (reproduced) or with an arbitrary tolerance (reproduced).

**Maintainability.** Two generations of tooling (legacy `run_workflow.py` and the gated pipeline) duplicate metrics, meshing, building and import, and give different answers for the same YAML. Documentation is extensive but partly stale and contradictory.

**Security.** Proportionate to a local tool, but there is one real exposure: the local server accepts cross-site requests. Any web page open in your browser while the app runs can change the brief, start runs, record decisions, or mark a run validated (reproduced with a forged Origin).

**Most consequential weaknesses**
1. The report can claim validation and superiority that the evidence does not support (P1, P2, B1, B2, B3).
2. State corruption and wrong-run writes in the app (S1, S2).
3. The Stage 2 path the tool presents for the folded design does not actually work (B3), which is why the headless BEM move is the right call.

---

## B. Prioritized findings

Classification key: **D** confirmed defect, **R** conditional risk, **A** architectural weakness, **M** maintainability problem, **F** friction, **Q** question for you.

### Critical / high

**S1. Concurrent writes corrupt `state.json`; corruption is hidden** (high, D)
- Where:
  - `hornflow/io/artifacts.py:35`: the temp file is `name.tmp.<pid>`, the same for every thread.
  - `hornflow/app/actions.py:299` (`import_vips`) and `:323` (`decision`): load, modify and save without `self._lock`.
  - `actions.py:109-115`: `_state()` swallows every exception and returns `None`.
- Failure (reproduced):
  - Four threads saving the draft gave hundreds of `FileNotFoundError` (HTTP 500).
  - An import plus a decision at the same moment left `state.json` unparseable, and the view then reported `mode="first_run"`.
- Trigger: a double-click on Import, two tabs, or a decision while an import runs.
- Impact: the authoritative run record (BEM verdict, decision log) is lost silently.
- Fix:
  - unique temp names (`tempfile.mkstemp` in the same directory);
  - one process lock around every state read-modify-write;
  - `_state()` returns a visible "state unreadable" error.
- Size: small, local.

**S2. Import and decision act on whichever run the server currently points at** (high, D)
- Where:
  - `actions.py:102` (`select_run`) and `:219` (`_adopt_run`) mutate the shared `self.run_dir`;
  - `server.py:118-122`: `/api/import` and `/api/decision` carry no run id.
- Failure: tab A shows run X; tab B selects Y, or a background run finishes and is adopted; tab A clicks Import or Accept. The result is written into run Y.
- Impact: a verdict or decision is recorded against the wrong design, and the log cannot reveal it.
- Fix: every mutating request carries `run_id`; the server refuses a mismatch.

**S3. No Origin/Host/Content-Type checks on the local API** (high, D)
- Where: `server.py:79` onward. No Origin or Host check; JSON is parsed whatever the Content-Type. `/api/health` (`:96`) returns the absolute project root.
- Failure (reproduced): a `text/plain` POST, a CORS "simple request" with no preflight, carrying `Origin: http://evil.example`, changed the draft. With S4, a page can POST `/api/import {"tolerance_db": 1e9}` and produce `BEM_VALIDATED`. DNS rebinding also exposes every GET.
- Fix:
  - require `application/json`;
  - accept only `Host` 127.0.0.1/localhost on the bound port, and same-origin `Origin`;
  - stop returning absolute paths;
  - warn when `--host` (`__main__.py:31`) is not loopback.
- Size: small.

**B1. The tolerance is caller-controlled and unbounded; provenance checks are soft** (high, D)
- Where:
  - `server.py:120`: `tolerance_db or 6.0`, so 0 silently becomes 6, and there is no bound anywhere.
  - `bem_manual.py:24, 203-225`: `belongs_to_run` and `run_manifest_matches` are `SOFT`.
  - `bem_manual.py:208`: "same export directory" counts as proof of origin.
  - `run_manifest_matches` compares the manifest with itself.
- Failure (reproduced):
  - The straight-horn Rad1_23Sept26 exports pass all 8 checks for the pipeline's folded `u_fold` candidate.
  - The known-broken Jbl1200B export (worst error 48.6 dB) becomes `BEM_VALIDATED` at tolerance 1e9.
- Impact: "BEM_VALIDATED" can mean "a file of unknown origin, compared with any tolerance".
- Fix:
  - store the tolerance in the definition or manifest, finite range only;
  - make provenance hard;
  - use the `.vips` header `Graph_Group`, version and timestamp, which the parser currently discards;
  - hash each imported file.
- Q: what tolerance range do you accept?

**B2. A failed re-import leaves the candidate `BEM_VALIDATED` with no metrics** (high, D)
- Where: `workflow/bem_import.py:51` (`_walk_to` silently stays put when the target is unreachable), `:105-119` (metrics overwritten).
- Failure (reproduced): validate at 12 dB, then import a junk or stale export. The state is still `BEM_VALIDATED`, with `metrics=None` and `validation_passed=False`.
- Fix: use the strict `manual.advance()`; keep the last accepted result; record failed attempts separately.

**B3. The pipeline's folded BEM mesh cannot be solved as instructed** (high, D)
- Where:
  - `orchestrator.py:246` uses `meshbuild.cavity_mesh(..., k=4)`;
  - `akabak.py:64`: `mesh_frequency` accepted, never used;
  - `akabak.py:116` points to a legacy, project-specific recipe path.
- Measured on a generated run: one physical group (`wall`), 32 boundary edges (open at throat and mouth), no `source` or `interface` group, aspect ratio up to 17.5. The checklist still says "Throat driven, Mouth interface".
- Impact: every AKABAK result in the repository, fixtures included, comes from the legacy straight mesh. The folded design shown as the winner has never had a 3-D check.
- Fix: part of the headless BEM work (section D): a closed, consistently oriented, tagged mesh.

**B4. The documented import commands fail on real exports** (high, D)
- Where: `run_workflow.py:299-304`. With `--stage 2 --bem-import`, inputs and the manifest are regenerated *before* validation, so every real export is "older than the inputs" and fails the hard timestamp check. The same regeneration overwrites `bem.msh` and the recipe.
- Also: gated `cli.py --bem-import` with a folder outside a run silently runs a brand-new pipeline and imports into that (reproduced).
- Fix: import must never regenerate; refuse a folder that does not belong to a run.

**P1. The folded horn "wins" only through the preference bonus** (high, D; breaks ADR-0005)
- Where:
  - `architecture/registry.py:33, 67`: the bonus is `100 × 0.05`, i.e. 5 points on a dB-based score (the ADR says "+0.05 on a 0-100 score");
  - `orchestrator.py:165` (`_refresh_scores`) gives every horn candidate the same master run;
  - `critique/critic.py:70-81`: the "raw" ranking is a stable sort of a list already sorted by the bonus score, so ties go to the folded horn.
- Failure (reproduced on `horn_jbl_1200b.yaml`): folded and straight both 104.5 dB / 8.0 dB; scores 101.505 vs 96.505. The critic passes "also wins without the bonus"; the report says "The folded horn is also the best overall design".
- Fix: detect ties within a tolerance and report "not decided without the bonus"; make this check blocking or force the wording; align the ADR with the real scale.
- Q: intended scale and size of the bonus?

**P2. Fold validation is circular, and fold choice ignores bend risk** (high, A)
- Where: `fold/base.py` (`sections_along` sets each station's area from the master area law), `fold/evaluate.py` (compares it against the same law), `orchestrator.py:214` (choice by `eta_pack` only).
- Observed: all 9 folds have `area_law_rms = 0.0`; every bend is `reflection_risk: high`; the chosen fold has a 0.10 m inner radius; all critic checks pass. "Fold-aware simulation" is the straight 1-D run with a new label.
- Fix:
  - measure realised area from generated walls;
  - include bend risk in selection or the critic;
  - label stage 9 honestly ("1-D, identical by construction").
- Q: prefer lowest bend risk or most compact package?

**P3. Sensitivity stage reports false numbers** (high, D)
- Where: `optimize/sensitivity.py:29-30` (also `architecture/box_models.py`): the -3 dB search scans from the bottom of the grid, so the cut-off is always `f[0]` = 20 Hz.
- More failures (reproduced):
  - **Mouth-area lever:** silently overridden. `fc` and `length` re-derive the mouth, so the deltas are 0.00.
  - **Depth lever:** silently changes the mouth too.
  - **Rear-chamber lever:** crashes with `missing required item 'dD'`, because overriding `driver.*` replaces the `driver: file.yaml` reference with `{}`. The same failure affects sweep axes on `driver.*`.
  - **Absolute levers:** they are tuned for the JBL design, so for `horn_80_250Hz.yaml` the "stricter" f_low is looser.
- Fix: scan down from the band; relative levers; merge overrides into file-referenced drivers; flag "lever had no effect".

**P8. The excursion safety gate is evaluated only at the 2.83 V simulation level** (high, Q)
- Where: `workflow/gates.py:30-53`. The maximum over the simulated range is taken at `simulation.voltage`.
- JBL example: 0.78 mm peak against 11.35 mm, so the gate passes at about 2 W. Advise and sweep never compare against Xmax at all.
- Decision needed: which drive level (rated power, target SPL, amplifier voltage) and which band (passband, or down to a high-pass) define "safe"?

**U1. The app silently bases a frozen brief on the wrong project** (high, D)
- Where: `app/brief.py:138-145`. Without `--base`, the first `params/*.yaml` alphabetically (`horn_80_250Hz.yaml`) is used, not the run's definition. The README command omits `--base`. The tests always pass it.
- Impact: a run started from the UI simulates a different throat, profile and mouth from the design you were looking at.
- Fix: default to the selected run's own definition; refuse when ambiguous.

**U2. The documented "no run yet" mode cannot serve a page** (high, D, static reading)
- Where: `server.py:135, 151`. With no run, `/viewer/viewer.html` returns `no_document_root` JSON, while the banner says "answer the brief in the page". `first_run_view()` exists but nothing renders it.
- Impact: the first-time onboarding path is dead.

**U3. The recommended folded design has no buildable output** (high, A/F)
- Where: `manufacturing/plywood.py` (panel sizes only in `state.json`; mitre = 180°/(m-1) spread over every facet); `manufacturing/additive.py` (part count says 5, but the parts still exceed the 350 mm build volume); the only file is one unsplit 1.3 × 1.6 m `printed.stl`. The legacy `--build` package exists only for the straight horn.
- Q: is your build target plywood U-fold panels, a straight slice stack, or printed parts?

### Medium

| ID | Title | Class | Where | Essence and fix |
|---|---|---|---|---|
| S5 | Typed stage failure crashes the run | D | `orchestrator.py:207-212` vs `domain/failures.py` (`recoverable`) | `recoverability=` raises `TypeError`, so "no valid fold" aborts with no `state.json` (ADR-0003 broken). Rename; add a zero-valid-fold test. |
| S6 | State written only at the end | D | `orchestrator.py:368-369` | Crashes leave invisible run folders, and progress shows the previous run (`actions.py:260`). It tops out at 94% because "skipped" is not counted. Write state at start and after each stage; record failures. |
| S7 | Run not reproducible | A | `orchestrator.py:137-139`; `bem_import.py:87`; `optimize/sensitivity.py` re-reads the YAML; `brief.py` overwrites `.hornflow/generated/<slug>.yaml` | Snapshot definition and driver with hashes; record code version, limits and tolerance; per-revision generated names. |
| S8 | Browser decides the import label | D | `actions.py:315` (`ok` = hard checks), `app.js:439` | A `BEM_REJECTED` result is shown as "BEM_VALIDATED". The model must return the label. |
| S9 | Decision loop broken | D | `app.js:447` reads `outcome.verdict`, but `view.py:712` emits `bem`; `view.py:730` expects events starting with "decision", but `actions.py:343` writes "accept_unvalidated" | "Accept as unvalidated" never renders, mode never reaches "decided", and "Mark decided" has no endpoint. One decision model enforced on the server. |
| S10 | Stage completion wrong | D | `view.py` (stage rules) | "Final decision" reads complete before any decision; `BEM_REJECTED` reads complete. |
| S11 | Pre-filled values fail at freeze | D | `orchestrator.py:114-122` writes `Xmax_mm=0`, `depth_mm=0`, enums the brief rejects | Unknown is stored as 0 and counts as answered. Use `null`; validate in the view model. |
| S12 | Stale outputs after import or decision | D | `bem_import.py`, `actions.decision`, `cli.py` | `app_view.json`, `viewer.html` and `report.md` keep saying "pending". Re-emit after every mutation (the spec in `docs/app-local-multitab.md` §17 promises it). |
| P4 | Free-space DI wrong | D | `theory.py:603-614` | Baffled formula clamped to Q ≥ 1, so DI(ka→0) is 3 dB in free space instead of 0. It affects the "DI 3.45 dB" used to explain the BEM offset. |
| P5 | Displacement-limited SPL 3 dB high | D | `physics/feasibility.py:117-124` | Peak pressure from peak Xmax is referenced to 20 µPa rms. Subtract 3.01 dB. This is the same class as the old ADR-0012 bug, in the unsafe direction. |
| P7 | Xmax convention misrecorded | D | `orchestrator.py:115` | Always `"one_way"`, whatever the driver says. The gate is right; `state.json` and the report are wrong for `peak_to_peak` drivers. |
| P10 | Advise designs one horn, simulates another | D | `advise.py` | Closed-form relations are exponential-only, but the YAML profile is kept. A hyperbolic probe: 1.60 m² advised, 1.17 m² simulated, "fits". |
| P11 | Sweep report crashes on mixed axes | D | `sweep.py:203` | `sorted()` over `{"auto", 1200}` raises `TypeError` after all simulations have run. |
| P12 | Config accepts NaN and nonsense | D | `config.py:341` (`load`) and parsers | `.nan`, distance 0, negative voltage, the typo `lenght:`, throat in metres (0.26 → "best overall: sealed box", exit 0), quoted `"false"` → True. Require finite and positive values, reject unknown keys, parse booleans strictly. |
| B5 | Diaphragm pressure accepted as on-axis SPL | D | `bem.py:767-768` | Any `Data_BaseUnit=Pa` counts. An LE-only folder passes the required-spectrum check. Select by caption and coordinates; check the mic distance. |
| B6 | Two comparison numbers, double +3.01 dB risk | D | `bem.py:464, 950` vs `bem_manual.py:252, 340` | `compare.md` says -9.1 dB, "subtract 3.01"; `bem_manual_report.md` says -8.68 dB, "already removed". |
| B7 | Legacy mesh normals and size claims wrong | D | `mesh.py` (`horn_mesh`, interface fan winding) | 42 of 294 interface triangles are reversed. The largest edge near the mouth is 0.41 to 0.58 m against a claimed 114 mm (λ/3.3 at 250 Hz). The volume as written is 0.579 m³ against 0.680 m³ analytic. |
| B8 | Recipe hardcodes JBL values | F | `bem.py` recipe text | Length, fs, impedance peak, box size and diaphragm diameter are wrong for any other design. |
| B9 | Solver interface not ready for automation | A | `physics/solvers/base.py`, `akabak.py:124`, `orchestrator.py:246-270`, `response.py:115-117` | See section D. |
| U4 | Viewer keeps old geometry after a UI run | D | `viz/viewer/index.html`, `app.js` | GLB parsed once; no stale marker. |
| U5 | Fold IDs collide | D | `fold/evaluate.py:48-53` | Hash excludes bend radius: the four u_fold radii share one id. Annotations would show the invalid R = 0.05 m candidate. |
| U6 | Two input models | A/F | `app/brief.py` | Only about 8 of 22 brief fields reach the definition. "max depth" sets path length, not box depth; "free" changes `half_space` but not the mouth termination. Q: what should the depth budget and "free" mean? |
| T1 | CI suite cannot be green on a clean checkout | D | `tests/test_app_api.py:48`, `.github/workflows/ci.yml:39-42` | The fixture needs a `runs/run_*` folder; `runs/` is gitignored and the pipeline runs *after* pytest. 34 tests error. |

### Low

- **P6.** The thermal screen is dead code: `drv.thermal_power` does not exist (`feasibility.py:130`), and `NaN` is written into `state.json` as invalid JSON.
- **P9.** The √2 conversion is re-implemented in about 7 places, and `gates.py` re-implements `domain.excursion.excursion_gate`. Behaviour is correct today.
- **P13.** The conical profile gives a 28.4° half-angle for a 45° setting. Q: confirm against Kolbrek Eq. 5/6 (the PDF is not in the repo).
- **P14 and P15.**
  - `compression_ratio` is always 1.0 in the reference profile.
  - The Webster adapter mislabels `krt_at_fmax` (it holds k·rt at fc) and ignores the `grid` and `drive` arguments.
- **B10.** The parser drops malformed rows silently, ignores `Data_AbscUnit` and `Data_LevelType`, and fails loudly on decimal commas and UTF-16.
- **S13 to S17.**
  - A `--run-root` outside the project breaks every view.
  - A value can't be cleared from the draft.
  - `from_dict` drops unknown keys, so a decision written by older code erases newer fields.
  - Several deliverables are not written atomically.
  - A `Content-Length` that isn't a number gives a 500.
- **U7.** The CLI exits 0 when stages fail and prints no stage status.
- **U8 and U9.**
  - Report polish: float noise like `27999.999999999996` and "nan dB".
  - "Copy AKABAK checklist" copies a path, not the checklist.
  - The cutaway plane removes only a sliver of the U-fold.
  - Four different masses appear across the outputs.
- **T2.** `test_theory.py` checks never raise under pytest (`tests/test_theory.py:26-33`); only the standalone run guards them.
- **T3.** The pre-commit hook is inert in a fresh clone (`core.hooksPath` is not set; CONTRIBUTING does not say how).
- **Hardcoded paths.** A home-directory path appears in the README quick start, `history.md` and `handoff.md`. Absolute paths are embedded in `state.json` and the manifest, so runs cannot be moved.

### What is sound

- **Stage 1 core.** Profiles, the exponential throat impedance including below cut-off, the frustum two-port, baffled piston radiation, the mechanical load, rms drive and the power formula all match the paper's equations. 147/147 checks pass.
- **ADR-0012 behaviour.** No reader still assumes the old excursion meaning. The gate compares peak with one-way peak.
- **Path traversal.** `safe_under` and all its callers are correct, symlinks included.
- **YAML loading.** `yaml.safe_load` is used everywhere. No user string reaches a shell. The request body is capped at 256 KiB.
- **Double start.** The single-run lock prevents starting two runs at once.
- **Comparison mechanics.** Interpolation and dB differencing are fine; the problem is what gets compared (B5, B6, B7).

---

## C. Persisted state assessment

| File | Writer | Readers | Version | Identity | Protections | Gaps |
|---|---|---|---|---|---|---|
| `runs/<id>/state.json` | pipeline `_finalize`, `bem_import`, `actions.decision` | app, emit, CLI import, tests | `schema_version` 1.1 + migration chain | `run_id` (seconds + 24 random bits) | temp+rename, fsync | shared temp name, no lock (S1, S2); written only at end (S6); unknown keys dropped; no input snapshot (S7); `NaN` tokens (P6) |
| `logs.jsonl` | `StageLogger.flush` at end | view, actions | none | `run_id` per line | atomic | nothing written during a run; lost on crash |
| `viewer/app_view.json`, `viewer.html` | `_finalize`, `emit_ui_for_run` | browser | `view_schema` 1.2 (docs say 1.0) | none | json atomic, html not | stale after import or decision (S12) |
| `report.md` | ArtifactStore | you | none | none | atomic | never regenerated after import |
| `bem/bem_manifest.json` | `manual.write_manifest` | importer, view | 1.0 | `run_id`, input sha256 | atomic | absolute paths; tautological match check (B1) |
| `bem/*recipe*.md`, `bem_manual_report.md`, `curves_stage2.csv`, `compare.*` | akabak, importer, `bem.py` | you | none | none | none | not atomic; built from the *current* YAML (S7); contradictory 3 dB advice (B6) |
| `.hornflow/brief.draft.yaml`, `brief.yaml` | BriefStore | app | schema strings, not checked on read | revision + hash (frozen) | atomic | shared temp name; revision increment unlocked |
| `.hornflow/generated/<slug>.yaml` | `freeze` | pipeline, import | brief/1 | slug only | proven loadable before kept | overwritten per slug, which breaks older runs; absolute driver path; folder is gitignored |
| legacy `results/<p>/curves.csv` | `report.py` | `report.read_csv` (v1→v2 in memory) | v1/v2 | none | n/a | fine |

**Integrity summary**
- **Ineffective protections:** the provenance checks (B1); the temp file name shared by all writers (S1); the strict transition function exists but is not used (B2).
- **Unsafe migration or compatibility behaviour:** `from_dict` drops unknown keys, and a newer schema produces "first_run" with no message. The 1.0→1.1 migration is pure and recorded, but it is persisted only on the next save.
- **Non-atomic operations:**
  - the state is written only at the end of a run;
  - import plus decision are unlocked;
  - several deliverables are written directly.
- **Stale derived data:** `app_view.json`, `viewer.html`, `report.md` and stage statuses after an import.
- **Reproducibility:** inputs, code version, limits and tolerance are not captured.
- **Backup and recovery:**
  - Nothing exists beyond git.
  - `runs/` and `.hornflow/` are gitignored, so the briefs and generated definitions that runs depend on are not versioned anywhere.
  - The AKABAK solution itself cannot be saved (demo build).

---

## D. Stage 2 transition (manual AKABAK → headless BEM)

### Current manual loop (17 steps)

| # | Step | Level | Silent failure |
|---|---|---|---|
| 1 | Generate inputs | auto | Folded mesh unusable (B3); regeneration overwrites inputs (B4) |
| 2-8 | Start Wine/AKABAK; create the project; mesh, scale, symmetry; BEM tree; NUC/edge length; type the LE network by hand; set the drive level | manual | Wrong file or scale; free-standing vs baffled never recorded; Kms/Cms or unit slips; ±3 dB rms/peak |
| 9 | Five solve buttons | manual | Solution held only in RAM (demo build) |
| 10-12 | Observations, export, copy into the run | manual | Mic position never checked (B5); export goes to the legacy folder; whether the copy keeps file times decides the timestamp check |
| 13-16 | Import, 8 checks, compare, state update | auto | B1, B2, B4, B5, B6 |
| 17 | Accept as unvalidated | UI | Broken rendering (S9) |

Three of the eight manual states (`INPUTS_GENERATED`, `MANUAL_SOLVE_COMPLETED`, and normally `MANUAL_SOLVE_PENDING`) are never written in normal flow.

### Integration points for the headless solver

| Module | Change | Fate |
|---|---|---|
| `physics/solvers/base.py` | Extend `SimulationRun` with solver, version, mesh sha256, element count, max edge vs λ at f_max, formulation (Burton-Miller on/off), radiation condition (4π / baffle), observation coordinates, complex throat impedance and pressure, c, rho, settings hash | generalize |
| new `physics/solvers/bempp.py` | Solve the exterior/interior problem; return `Z_throat(f)` on the tagged throat and `p_obs/U` at the observation points | new |
| `response.py:115-117` | Today hardcodes `theory.finite_throat_impedance`. Make the throat impedance and transfer function injectable (default Webster), so the existing Python driver model (rear box, semi-inductance, ADR-0012 excursion) couples to the BEM result. This is exactly what AKABAK's LE network does. | generalize |
| `mesh.py`, `manufacturing/meshbuild.py` | Fix winding; size elements to λ/6 or better at f_max; a closed, outward-oriented body with real wall thickness and a tagged throat cap for the folded horn (`shell_mesh` is already watertight); tests for closedness, orientation and volume | fix |
| `orchestrator.py:246-270` | Solver registry instead of a hardcoded `AkabakSolver`; stage 10 passes or fails on data instead of "skipped" | generalize |
| `bem_manual.py` checks, `manual.py` state machine, manifest, recipe | Keep only for the AKABAK cross-check (with the B1, B2, B4, B5 fixes and the hardcoded values templated out). A headless result needs only a grid check, a finiteness check and a mesh-hash match | reduce / retire |
| UI import panel, `view.py` solver label | Becomes "external solver result"; the label comes from the record, not the hardcoded "AKABAK Free 3.3.2" | generalize |
| Comparison | Split into **solver agreement** (bempp vs AKABAK on the same mesh, tight tolerance) and **model agreement** (BEM vs 1-D, explanatory, same radiation condition) | redesign |
| Old runs | Records without solver or mesh hash are read as "AKABAK, legacy, mesh unknown" | in-memory migration |

### Validation plan against the fixtures

- **Reference set:** `Rad1_23Sept26`.
  - Observations: Mic1 at (0, 0, L+1 m), H 0-90, RadImp1, LE1 to LE7.
  - Frequencies: 24 log points from 60 to 200 Hz.
  - Drive and driver: 2.83 V rms, Vb 0.028 m³.
  - Mesh: quarter mesh, free-standing, NUC none.
- **Negative controls:** `Jbl1200B_horn_19Sept26` and `Rad1_22Sept26` came from the known-wrong drive path. Any harness must reject them.
- **Order of comparison** (solve at AKABAK's exact 24 frequencies, no interpolation):
  1. **Acoustics only:** complex RadImp1, and Mic1/LE4 as p/U. This removes the driver model from the test.
  2. **Coupled:** |Ze| (LE2, peak 34.2 Ω at 66.6 Hz), peak excursion (LE1), and Mic1 SPL.
  3. **Directivity:** H 0-90, only once the arc centre is known.
- **Mesh convergence:** solve at λ/6 and λ/10 (at 200 Hz). Agreement with AKABAK should be no worse than the spread between the two bempp mesh levels.
- **Low-frequency risks:**
  - *Irregular frequencies.* The horn interior is about 0.68 m³, with its first modes around c/2L ≈ 114 Hz, inside the band. The reference was solved with no correction (NUC none). Solve with and without Burton-Miller, sweep 100 to 130 Hz in 1 Hz steps, and check the power balance (½·Re(Z_throat)·|U|² = far-field power). A spike that AKABAK shows and Burton-Miller bempp does not is an artefact of the reference.
  - *Thin walls.* Compare a thick-wall closed body against the zero-thickness model on the straight horn first. Only then go to the folded horn, which has no AKABAK reference at all.
  - *Near field.* The mic is 1 m from a 1.6 × 1.0 m mouth. Also compare at 10 m, scaled to 1 m.
- **The -8.6 dB offset:** treat it as open.
  - The difference oscillates (-10.9, -4.8, -11.5, -4.2 dB across the band) rather than shrinking smoothly, so it is not cleanly a 2π vs 4π effect.
  - bempp can solve both radiation conditions on the same mesh, which settles the question without the AKABAK infinite-baffle re-solve.
  - Until then, block "relax tolerance" as a route to `BEM_VALIDATED`.
- **Settings the repository cannot recover (please confirm):**
  - Element count actually solved: 640 or 1398 (the documents disagree).
  - The exact mesh file: no mesh or hash is stored, and AKABAK logged 0.482 m³ against 0.680 m³ regenerated.
  - AKABAK's c, rho and temperature.
  - The enclosure loss (Qb).
  - Diaphragm vs throat area mapping.
  - The centre of the H 0-90 arc.
  - Whether the semi-inductance values were entered.
  - Whether the 19 Sept full-mesh run included the baffle.

---

## E. UX and visualization assessment

**Entry points.** There are five ways to run the tool: `run_workflow.py` (six modes, about 25 flags), `run_pipeline.py`, `python -m hornflow.cli`, `python -m hornflow.app`, and `--emit-ui`. None covers everything:
- advise, sweep and the build package exist only in the legacy tool;
- folding, the report and the viewer exist only in the gated pipeline;
- there are two separate import implementations.

**Time to a first result** is excellent: the pipeline runs in about 0.9 s. The experience around it is poor:
- 16 bare stage names and no pass/fail status;
- tracebacks for ordinary input mistakes;
- an empty run folder left behind on error;
- silent acceptance of typos and unit slips (exit 0 with nonsense results).

**Workflow tab.** The nine-stage model is reasonable, but:
- for a YAML-driven run, five stages always show "needs input" (U6);
- completion states are wrong (S10);
- the next action often points away from the stage that is open.

**Viewer tab.** It shows geometry, the cutaway, the centreline, stations and dimensions. It goes stale after a UI run (U4), the cutaway removes only a sliver, and the legend promises parts that do not exist.

**First interactive features**, all built on data the pipeline already writes:

| Feature | Data already there | Constraint strain |
|---|---|---|
| Results tab v1: overlaid SPL, impedance, excursion against Xmax (rms and peak), phase, group delay | `state.simulation_runs[0]` (400 points) | none: inline SVG or canvas, offline |
| Architecture and sensitivity tables, with ties shown honestly | `architecture_candidates`, `sensitivity_runs` | none (after P1 and P3) |
| Run-to-run comparison | two `state.json` files via `/api/runs`, `/api/view?run=` | needs the host (not `file://`); needs a grid and schema check |
| Fast Stage-1 "what-if" sliders | `POST /api/preview` → `config.load(overrides)` + `WebsterSolver` (measured about 45 ms per solve) | needs the host; keep "model computes, browser draws" (ADR-0013/14) |
| Fold inspection: stations, areas, bends, phase skew | `fold_candidates` | needs station points exported (GLB extras); needs U5 first |
| 3-D BEM results: mouth or field colour map, polar plots | the headless solver output | GLB writer needs a colour attribute; polar plots are plain SVG |

---

## F. Code quality assessment

1. **Two generations of tooling side by side.**
   - The legacy tool (`run_workflow.py`, `advise.py`, `sweep.py`, `bem.py`, `mesh.py`, `build.py`, `report.py`) and the gated pipeline duplicate band metrics (5 copies; the cut-off bug exists only in the pipeline copies), meshing (straight vs folded cavity), building (slices vs shell and plywood) and import (two `--bem-import`).
   - For the same YAML they produce different BEM geometries and different objects to build.
   - Boundary: one `metrics` module and one `bem` package used by both; the legacy CLI becomes a thin front end over the pipeline services (advise and sweep as pipeline commands).
   - This removes P3-type drift and B4.
2. **The orchestrator decides physics policy inline.**
   - Scoring refresh, fold choice and the hardcoded solver live in `orchestrator.py`.
   - Boundary: a `selection` module (scoring, ties, fold choice with bend risk) and a solver registry.
   - This reduces P1, P2 and B9.
3. **Too much in the view model.**
   - `app/view.py` (1018 lines) builds the view, owns stage rules, decides completion and defines the decision vocabulary; `app.js` (1146 lines) re-derives labels.
   - Boundary: a `workflow/decisions.py` (allowed decision kinds per BEM state, enforced by `actions` and read by `view`), and stage completion rules in `workflow/` rather than in presentation.
   - This fixes the class behind S8, S9 and S10.
4. **No validation at the input boundaries.** YAML (P12), the HTTP body (S3, B1) and `.vips` metadata (B5, B10) are trusted. A small schema layer with finite, positive and unknown-key checks in `config.load` closes a whole family of silent-nonsense outcomes.
5. **Persistence.** Make `io/state_store` the only writer, with a lock, unique temp names, start-of-run and per-stage saves, unknown-key preservation, and an input snapshot (S1, S6, S7).
6. **Tests that cannot fail or cannot run.** T1 and T2 mean that "main is always green" is not true today. Build a synthetic run fixture.

Not a problem: the stdlib-first policy, the r128 viewer and the file-based state all fit a personal, offline tool. No rewrite is justified.

---

## G. Project organization

| Doc | Status | Action |
|---|---|---|
| README.md | Contradictory: legacy and gated mixed, byte-for-byte claim, hardcoded path | Rewrite as a short "start here" with one path and one example |
| CONTRIBUTING.md | Mostly current; hook setup missing | Keep; add `git config core.hooksPath .githooks`; relax the "4 docs per PR" rule |
| history.md | AKABAK ground rules still valuable; the log is superseded | Move the ground rules into `docs/akabak.md` (cross-check use only); archive the log |
| handoff.md | Superseded, and contradicts the code (mouth 1599 × 1824, test counts) | Archive; replace with a pinned "Current state" issue |
| docs/adr.md | Current; ADR-0001 stale; 0013 after 0015 | Keep; amend 0001 and 0005; add an ADR for headless BEM |
| docs/migration-notes.md | Changelog duplicated; schema notes valuable | Keep only the schema part, as `docs/schema.md` |
| docs/app-local-multitab.md | Current UI spec; status sections stale | Keep and update |
| docs/ui-two-tab-mvp.md, docs/jira-issue-flow.md | Superseded | Archive |

**Tracking setup (GitHub Issues):**
- **Labels:** `bug`, `physics`, `bem`, `ux`, `docs`, `chore`, `needs-decision`, size `S`/`M`/`L`.
- **Milestones:** "Trustworthy outputs", "Headless BEM", "Usable app".

**Initial backlog**

| # | Title | Size |
|---|---|---|
| 1 | Unique temp files plus a state lock; surface unreadable state (S1) | S |
| 2 | Run id on every mutating API call (S2) | S |
| 3 | Origin, Host and Content-Type checks on the local server (S3) | S |
| 4 | Bounded, recorded BEM tolerance; hard provenance from `.vips` headers (B1) | M |
| 5 | Strict state transitions on import; keep the last accepted result (B2) | S |
| 6 | Report ties honestly; fix the bonus scale and critic sort (P1) | S |
| 7 | Fix sensitivity cut-off, levers and driver overrides (P3) | M |
| 8 | Fix displacement SPL (-3 dB), free-space DI, and record the Xmax convention (P4, P5, P7) | S |
| 9 | Decide and implement the safety-gate drive level (P8) | M, needs-decision |
| 10 | Input validation in `config.load` with clean CLI errors (P12, U7) | M |
| 11 | App base definition = the run's own; first-run page (U1, U2) | S |
| 12 | Snapshot inputs into each run; per-stage state saves (S6, S7) | M |
| 13 | Fix the decision loop and stage completion; re-emit outputs after mutations (S8, S9, S10, S12) | M |
| 14 | Synthetic run fixture so CI passes on a clean checkout (T1, T2) | S |
| 15 | Mesh fixes: winding, λ-based sizing, closed tagged folded body (B3, B7) | M |
| 16 | Injectable throat impedance in `response.py` and a solver registry (B9) | M |
| 17 | bempp solver plus the validation harness against `Rad1_23Sept26` | L |
| 18 | Results tab v1 (curves, architecture table) | M |
| 19 | Buildable output for the chosen fold (cut list, DXF), after the build-target decision (U3) | L, needs-decision |
| 20 | Docs consolidation (README "start here", archive handoff, history log, Jira and MVP docs) | M |

---

## H. Remediation order

**1. Immediate correctness and state integrity** (all small and local, no migration)
- S1, S2, S3, B2, S5, T1.
- Then B1. It needs your tolerance decision; making provenance hard is independent of that decision.

**2. Trust in the report** (small to medium, mostly local)
- P1, P3, P4, P5, P7, P12, U1.
- P8 needs your drive-level decision.
- P2 needs your fold-selection decision.
- S7 (input snapshot) needs a small state-schema bump (1.2), with old runs read as "inputs not captured".

**3. Headless BEM** (depends on 1; benefits from 2)
- Mesh fixes (B3, B7), then the injectable throat impedance (B9), then the bempp solver.
- Then the validation harness against the fixtures, then retiring or reducing the manual loop and generalizing the UI panel.
- The record fields need a schema bump plus an in-memory migration for old AKABAK runs.

**4. UX and visualization** (depends on 1 and on S7 for run comparison)
- U2, S8, S9, S10, S12, U4.
- Then the Results tab v1, the fast Stage-1 preview, and fold inspection (after U5, which changes fold ids and needs a migration note).
- U3 and U6 need your build-target and depth-budget decisions.

**5. Maintainability** (ongoing, after 2)
- Merge the duplicate metrics, then put the legacy CLI over pipeline services, then the decisions module and view slimming.
- Docs consolidation can happen any time.

---

## I. Coverage and limitations

- **Inspected:** all Python modules under `hornflow/`, `run_workflow.py`, `run_pipeline.py`, the viewer HTML/JS/CSS, tests and fixtures, tools, hooks, CI, the requirements files, and all documents.
- **Ran on a throwaway copy:**
  - the gated pipeline and the legacy build;
  - broken-YAML variants;
  - the theory checks and most of pytest;
  - mesh generation and numpy mesh analysis;
  - all 21 `.vips` fixtures and crafted parser edge cases;
  - 9 import scenarios;
  - concurrency and cross-origin probes against the app actions and a short-lived server on a random port.
- **Environment caveat:** scipy, matplotlib and hypothesis are not installed here, and nothing was installed.
  - scipy's `j1`/`struve` were replaced by a quadrature stand-in. The legacy `curves.csv` it produced is byte-identical to the baseline fixture, and the history's -8.68 dB is reproduced exactly.
  - Plots were stubbed. The hypothesis-based property tests did not run.
- **Not verified:** anything inside AKABAK or Wine; real browser behaviour across tabs and DNS rebinding (reasoned from headers); bempp behaviour (not installed, by design); real run data (no `runs/` in the repository, so no claim is made that existing runs are corrupted); git history (a shallow clone with one commit).
- **Resting on documentation only:** the AKABAK settings used for the fixtures; the meaning of the +3.01 dB rendering offset in AKABAK; the Kolbrek conical-profile convention (the paper is not in the repository).

---

## Five most valuable next actions

1. **Make the run record safe:** unique temp files plus one lock, run id on every mutating call, and Origin/Host checks (S1, S2, S3). Three small changes that remove the only ways the app can silently destroy or forge results.
2. **Make the report honest:** fix the tie handling and bonus (P1), the sensitivity cut-off and levers (P3), the 3 dB displacement-SPL error and free-space DI (P4, P5), and decide the safety-gate drive level (P8).
3. **Snapshot inputs into every run and save state per stage** (S6, S7), so every result can be reproduced and every crash can be seen.
4. **Start headless BEM with the acoustics-only comparison:** fix the straight mesh (B7), make the throat impedance injectable (B9), and reproduce `Rad1_23Sept26` RadImp1 and Mic1/LE4 with bempp, with and without Burton-Miller. That one experiment also settles whether the -8.6 dB offset is radiation space or an AKABAK artefact.
5. **Set up GitHub Issues with the backlog above, and replace `handoff.md` and the history log with a pinned "Current state" issue and a one-page README "start here".**

### Decisions only you can make
1. Accepted BEM tolerance range, and whether "relax tolerance" may ever lead to validated.
2. The drive level and band for the excursion safety gate.
3. Fold selection: lowest bend risk or most compact.
4. Size and scale of the folded-horn preference bonus.
5. Build target: plywood U-fold, straight slice stack, or printed parts.
6. What "max depth" means (box depth or path length), and whether "free-standing" should also change the mouth model.
7. Reference radiation condition for Stage 1: baffled 2π or free 4π.
