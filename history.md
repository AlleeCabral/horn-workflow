# horn-workflow — history & run-book

> **How to use this file.** The *frozen header* below (sections 0–2) holds the
> commands, paths and ground rules. It does not change.
> Below the divider, sessions are appended chronologically — newest last.
> To resume work: read section 0, then jump to **CURRENT STATE** at the bottom.
> To start a **fresh Cline session**: copy the prompt in **`handoff.md`** — it carries the
> full context (environment, final goal, current state, next step, constraints).

---

<!-- ==================== FROZEN HEADER - DO NOT EDIT ==================== -->

## 0. Commands — open AKABAK, the manual, the workflow

```bash
cd '/home/alex/AI projects/horn-workflow'

# --- AKABAK (3.3 demo) under Wine -------------------------------------------
./AKABAK/akabak.sh          # registers the VACS COM server, starts AKABAK,
                            # holds a sleep lock so a lid-close cannot kill a solve
./AKABAK/akabak.sh --vacs   # only (re-)register VacsViewer as COM server
pgrep -af AKABAK_Demo_64r   # is AKABAK already running?

# --- the manual (CHM -> plain HTML, opens in Firefox) -----------------------
7z x -y -o/tmp/akabak_manual 'AKABAK/free/Akabak.chm'
firefox file:///tmp/akabak_manual/Chapters/Index.html
#   handy pages: Desktop/_Index.html (status bar), Desktop/Form-LevelOfDriving.html,
#   Desktop/Form-BEM-Parameters.html, LEM-Part/Cmps/Elec-Dyn-Driver.html,
#   Observation-Part/_Index.html, BEM-Part/Form-Infinite-Baffle.html,
#   Appendix/Radiation Conditions.html, Appendix/Infinite Baffle.html,
#   Appendix/Pro vs Demo Version.html
#   (/tmp is lost on reboot - re-extract when needed)

# --- the workflow -----------------------------------------------------------
python3 run_workflow.py params/horn_jbl_1200b.yaml                       # stage 1 (1P)
python3 run_workflow.py params/horn_jbl_1200b.yaml --stage 2 --bem-symmetry xy
python3 run_workflow.py params/horn_jbl_1200b.yaml --stage 2 \
        --bem-import results/jbl_1200b/bem/export        # validation + stage 1 vs BEM
python3 tests/test_theory.py                             # 147 checks

# --- the gated pipeline (folded horns) + the manual BEM round trip -----------
python3 -m hornflow.cli params/horn_jbl_1200b.yaml --out runs    # 16 stages, ~2 s
python3 -m hornflow.cli params/horn_jbl_1200b.yaml \
        --bem-import runs/<run_id>/deliverables/bem/export       # resume + validate
#   -> inputs, run manifest (bem_manifest.json) and the run checklist
#      (akabak_recipe.md) are written by the pipeline itself;
#   -> --bem-tolerance-db N changes the BEM_VALIDATED threshold (default 6 dB);
#   -> the candidate is NEVER BEM_VALIDATED without a .vips import AND comparison.
python3 -m pytest tests/ -q                              # 122 checks
```

## 1. Where everything lives

| what | path |
|---|---|
| workflow code + reports | `~/AI projects/horn-workflow/` (README.md, run_workflow.py, hornflow/) |
| design definition | `params/horn_jbl_1200b.yaml`, `params/drivers/jbl_1200b.yaml` |
| Stage-1 output | `results/jbl_1200b/` (`curves.csv`, `spl_onaxis.png`, `throat_impedance.png`, `report.md`) |
| Stage-2 input files | `results/jbl_1200b/bem/` — `bem.msh` (full, 2772 tri), `bem_quarter.msh` (640), `bem_half.msh` (1344), `driver_le.txt`, `bem.geo`, `akabak_recipe.md` |
| Stage-2 results | `results/jbl_1200b/bem/export/` — the `*.vips` files AKABAK writes |
| GUI project (Windows/Wine side) | `~/AI projects/horn design/Saved/*.akp` |
| launcher | `AKABAK/akabak.sh`, `AKABAK/free/AKABAK_Demo_64r.exe`, `AKABAK/free/VACS/VacsViewer.exe` |
| Wine settings | `~/.wine/drive_c/users/alex/Local Settings/Application Data/RDTeam/Akabak.ini` |

## 2. Ground rules (learned the hard way)

1. **The demo cannot write the BEM result file (`*.akpbe`).** The solved BEM state lives in
   RAM only. Consequence: `BEM-Meshing` / `BEM-Solving` are expensive and must not be
   re-run without need; **`LE-Solving`, `Ob Spectra`, `Ob Fields` are cheap** — they use
   superposition, *"as long as we do not change the acoustic boundary condition the
   BEM-part does not need to be re-solved"* (Appendix/Processing).
2. **Always save the project (`File → Save As…`, new name) before an experiment.**
   Result files are never saved, so the model is the only thing worth keeping.
3. **Symmetry is a property of the mesh, not a solver switch.** `Symmetry = xy` requires the
   *cut* quarter mesh (`bem_quarter.msh`, nothing in the x=0 / y=0 planes). With it: 640
   elements, ~17 s solve instead of 50 min. Tick it *before* solving.
4. **`Global → Meshing → Edge Length` stays empty** for the production run. `0.1 m`
   refines 640 → 1398 elements and costs 4 min instead of 17 s for no audible gain at 200 Hz.
5. **Driver terminals (Elec-Dyn Driver):** `s`/`t` = voice coil (source / GND),
   `u` = diaphragm **front** → `Rad1` → driven BEM group `Throat`, `v` = diaphragm **rear**
   → `Encl` (Vb = 0.028 m³). Acoustic pair on one edge, front above rear.
   An `Enclosure` has a single free pole (the other pole is implicitly ground —
   LEM-Part/Cmps/Enclosure.html: *"a two-pole, where one pole is always grounded"*).
6. **Couple the diaphragm to the mesh only once**: either `Rad1` (*Ref to BEM = Throat*) with
   `Diaph front`/`rear` = `- not referenced -`, **or** `Diaph front → Reference = Elements (mesh
   file) - Throat` with `Rad1` deleted. Never both.
7. **Status bar:** *"BE-Meshing, BE-Solving, LE-Solving, Ob Fields, Ob Spectra indicate the
   state of the calculation stack. **Green means done. Red means unfinished.**"*
   (Desktop/_Index.html). Red ⇒ just press that stage. The leftmost icon is *Result File
   Saving* — crossed = disabled (demo / no release code), which is why no `.akpbe` appears.
8. **AKABAK's dB is peak-referenced** (`p0 = √2·20 µPa`) → +3.01 dB above rms-referenced dB SPL.
   Its `Data_LevelType` in the `*.vips` files tells you which convention a curve uses
   (`Peak` / `SoundPressure` / `Impedance10`).
9. **Export setup** (set once): `Options → Preferences → VACS` = `File` + `Text format`,
   folder `Z:\home\alex\AI projects\horn-workflow\results\jbl_1200b\bem\export`.
   Observation stages only write files when they *run* — changing the preference
   afterwards re-emits nothing.
10. Known cosmetic issue: the driven element group is literally named **`Thoat`** (typo) and
    `RadImp1` references it. Harmless — leave it.

<!-- ======================= END FROZEN HEADER ======================= -->

---

# History

## 2026-09-18 → 19 — Stage 1, Stage 2, first AKABAK project
* Stage-1 model (`hornflow`) built and validated against Kolbrek horn theory; reports
  written to `results/jbl_1200b/`.
* Stage-2 mesh generator added: horn surface + throat source disk + mouth interface
  + 400 mm `baffle` flange ring. `bem.msh`: 2772 triangles. BEM mesh inside AKABAK:
  **2688 elements**, air volume 0.482367 m³.
* AKABAK project assembled by hand (BEM tree, LEM network). First full solve:
  **50:26** (`NUC = Dual Surface`, no symmetry).
* Observations added; first `*.vips` export (`Jbl1200B_horn_19Sept26`, 15:01).
  **Result: SPL 43 dB low and current 30× low** → the drive path was wrong;
  VACS-push, mesh scaling, fan/triangulation and coupling were checked one by one.

## 2026-09-21 — symmetry support, launcher, export plumbing
* `--bem-symmetry x|y|xy` in `hornflow/mesh.py` + `hornflow/bem.py`: emits `bem_half.msh` /
  `bem_quarter.msh` (same tags, no faces lying in the symmetry planes; arc ends snapped to
  exactly 0). Full mesh byte-identical (sha256 unchanged).
* Two new tests (`test_mesh_symmetry`, `test_bem_symmetry_files`) → **147 checks pass**.
* `akabak_recipe.md` section 11 added (symmetry rationale + click list).
* `AKABAK/akabak.sh`: registers the VACS COM server and starts AKABAK under
  `systemd-inhibit --what=idle:sleep` (a suspend during a 50-minute solve had cost 2 h).
* `Akabak.ini` → `SpectrumOutputFolder` = `…/results/jbl_1200b/bem/export`, File + Text.
* README / `run_workflow.py` updated (`--bem-import`, `--bem-symmetry`).

## 2026-09-22 — quarter mesh, symmetry xy, drive chase
* Mesh File object re-pointed to `bem_quarter.msh` (**Re-Open** keeps the tag filters),
  `Symmetry = xy`, `NUC = None`. Log: **640 elements, solve 00:17** (vs 50:26 = ~180×),
  volume 0.482062 m³ (0.06 % of full mesh).
* `Edge Length = 0.1 m` tested → 1398 elements, solve 04:01 (kept for one run, then dropped).
* Exports at 22:59 (`Rad1_22Sept26-LE1…LE6`): still **current 30× low**, SPL 43 dB low.

## 2026-09-23 — the drive is fixed, the model is validated
* Added the decisive observations (`LE3` current, `LE4` q, `LE5` p, `LE6` v, **`LE7` = `V_st`**).
* **`V_st` = 4.0022 V peak**, flat over 60–200 Hz ⇒ the source now drives the coil at the
  intended level (2.83 V rms).
* All internal relations close (60 Hz):

| check | value |
|---|---|
| `Z = V_st / I_s` | 4.0022 / 0.21393 = **18.71 Ω** = `LE2` 18.708 |
| `q_u` = `v_mo · Sd` | 0.013335 vs 0.25228 × 0.05286 = 0.013336 |
| `x · ω` = `v_mo` | 0.000669 × 377 = 0.2523 |
| `p_u0 / q_u` | **5158** vs the BEM's own `RadImp1` = **5157** Pa·s/m³ |

* Stage-1 vs BEM over all 24 frequencies: **excursion within ±2 dB** (ratio 0.77–1.61,
  typically 1.1–1.25 after correcting the rms/peak labelling), **current ≈1.0 above 110 Hz**
  (0.2–0.5 in the 60–90 Hz impedance-peak region), **SPL −4.2 … −11.6 dB** (mean −8.6).
* Interpretation of the SPL offset: Stage-1 assumes a **baffled mouth (half space)** — its own
  `di_db` at 60 Hz is **3.45 dB** — while the BEM models a **free-standing horn (full space)**.
  The offset shrinks with frequency (−11 dB @65 Hz → −4.5 dB @200 Hz), the signature of a
  radiation-space / ka effect, not a level error.
* Found a **bug in our own report**: `excursion_peak_mm` in `curves.csv` actually holds the
  **rms** excursion (proof: `I_abs` is rms, `v_rms = Bl·I_rms/Z_mech`, `x = v/ω` = the column).
  AKABAK's `LE1` is labelled `Peak`. ⇒ X_max / "power at Xmax" figures are 3 dB optimistic.

---

## Session close — `history.md` created
* This file created and installed at the repo root (`horn-workflow/history.md`):
  frozen header (commands, folder map, 10 ground rules) + session log + CURRENT STATE
  + NEXT STEP + OPEN ITEMS — the workflow can be resumed from this file alone.
* Session dates in this log follow the `.akp` / export file timestamps: 18–23 Sept 2026.
* A large external reference was supplied this session (1000+ pages) — logged under
  DEFERRED RESEARCH at the bottom; **not read yet**.

## 2026-10-03 — gated folded-horn pipeline (Milestone 0 + vertical slice)

* Added a 16-stage, state-driven design pipeline **on top of** the validated
  engine; the Webster/BEM core and the legacy `run_workflow.py` are untouched.
* New packages: `domain` (ids, evidence, limits, failures, geometry with
  AreaLaw/Centreline/RMF/AcousticMaster, versioned `state`), `io` (atomic
  content-addressed `artifacts`, `state_store`, JSONL `logs`), `physics`
  (feasibility + `solvers/webster` adapter + `solvers/akabak` contract),
  `architecture` (front-loaded, folded, sealed, reflex + registry + stubs),
  `fold` (straight/J/U generators, bend analysis, area-law report, packaging),
  `manufacturing` (swept cavity + watertight shell, additive, plywood, exporters),
  `viz` (stdlib GLB writer + offline Three.js viewer), `optimize` (sensitivity),
  `reporting`, `workflow` (16-stage DAG + gates + orchestrator), `critique`.
* **Milestone 0 baseline**: `tests/fixtures/baseline/` freezes the JBL reference
  numbers and a byte-identical `curves.csv`; `tools/capture_baseline.py` regenerates it.
* Ran the pipeline on the JBL example: best folded = U-fold (chosen by packaging
  efficiency), best overall = folded horn; areas preserved to RMS 0.0000; shell
  watertight (5 parts); plywood facet RMS 0.030, length error −1.7 %.
* Honest result surfaced by the pipeline: the U-fold bend is **high-risk** at
  200 Hz (phase skew ≈290°, transverse mode ≈380 Hz) — it needs a fold-aware/BEM
  check or a gentler radius. This is exactly the kind of judgement the old
  horn-only workflow could not make.
* 3-D BEM: inputs generated for the folded mesh; external solve `pending`
  (AKABAK GUI/Wine), stage `THREE_DIMENSIONAL_VERIFICATION` = skipped by design.
* Dependencies: pytest 9 + hypothesis 6 installed **for tests only**; production
  stays numpy/scipy/PyYAML/matplotlib. STEP/3MF/VTU are documented deferrals.
* Tests: legacy **147/147**; new pytest suite **60 passed**.
* Docs: `README.md` (pipeline section), `history.md`, `handoff.md`,
  `docs/adr.md`, `docs/migration-notes.md`.

## 2026-10-03 — manual AKABAK hand-over, `.vips` import and validation

* Took the AKABAK environment as **authoritative** and made the manual step a
  first-class, gated part of the workflow instead of a workaround:
  AKABAK Free **3.3.2 b144** under **Wine GUI**, **no usable head-less/CLI solve
  path**, the Free build **does not write `.akpbe`** (solved state stays in RAM),
  `.vips` spectra export manually.
* **Inputs are now fully automatic.** Both paths write, next to the mesh and the
  LE script, a **run manifest** (`bem_manifest.json`: run id, UTC stamp, solver
  and version, export dir, expected globs, SHA-256 of every input) and the
  **run-specific checklist** `akabak_recipe.md` (run id, exact paths, expected
  filenames, tick-as-you-go actions, troubleshooting, import command at the end).
* **`.vips` parsing** (closes OPEN ITEM 1): real format handled — CRLF, `//`
  header, `Key=Value` metadata, `Data … Data_End` block, `freq re im` rows, one
  pair per curve (polar rows carry one pair per `Param_Coord_x2` angle). Pressure
  columns are converted to rms-referenced dB SPL by removing the peak-rendering
  convention (3.0103 dB). **Golden check:** `Akabak-Rad1_23Sept26-Mic1.vips`
  @60 Hz = **87.73 dB**, matching the 87.7 dB recorded on 23 Sept.
* **Validation** of the returned export (8 checks): file exists, non-empty,
  belongs to the run, valid frequency grid, required pressure spectrum, numeric
  finite values, timestamp after input generation, manifest match. Hard failures
  do not advance the state; they say exactly what to fix.
* **Manual-solve state machine**: `INPUTS_GENERATED → GUI_REQUIRED →
  MANUAL_SOLVE_PENDING → MANUAL_SOLVE_COMPLETED → VIPS_IMPORTED →
  BEM_COMPARISON_COMPLETED → BEM_VALIDATED | BEM_REJECTED`, plus an explicit
  re-import edge from either decided state. **A candidate can never be
  `BEM_VALIDATED` before a `.vips` import plus comparison has run** — the
  pipeline leaves stage 10 at `GUI_REQUIRED`.
* **Resume**: `python3 -m hornflow.cli <yaml> --bem-import <export-dir>` detects
  a run directory and resumes it (state.json rewritten, `decision_log` appended,
  `deliverables/bem/bem_manual_report.md` written).
* **Live demo on the real exports** (Rad1_23Sept26 set): all 8 checks pass; the
  on-axis comparison gives **mean −8.68 dB, worst 11.64 dB** versus the 1-D
  model — i.e. exactly the documented **4π free-standing vs 2π baffled** mounting
  offset. So at the default 6 dB tolerance the candidate is `BEM_REJECTED`
  (correctly refusing to call it validated), and at `--bem-tolerance-db 12` it
  becomes `BEM_VALIDATED`. Re-importing supersedes the earlier decision.
  * The pipeline also correctly refuses the *superseded* multi-session exports:
    files older than the freshly generated manifest fail
    `export_timestamp_after_inputs`.
* Curve selection from a folder: pressure first, then a **point mic** (over a
  richer polar), then table size, then the newest file.
* Tests: legacy **147/147**; pytest suite **60 → 94 passed** (new
  `tests/test_bem_manual.py`, 34 tests incl. Hypothesis properties and an
  end-to-end run → synth-export → validate → resume flow).
* Docs: `docs/migration-notes.md`, this file, `README.md`, `handoff.md`, and the
  reason preserved in `hornflow/physics/solvers/akabak.py`.

## 2026-10-03 — local-first UI, M1–M3 (viewer becomes the app shell)

* **Direction decision (ADR-0011).** The UI is **local-first**: the existing viewer
  *is* the app shell, extended into a three-tab single-page app. No Jira and no
  Forge — Forge resolvers cannot run a shell or touch a filesystem, so the pipeline
  would need a separate runner service before one run exists. The Jira/Forge design
  docs are kept (their field/question/gate work carries over) with "superseded
  (hosting only)" banners.
* **M1 — the view model.** `hornflow/app/view.py` derives
  `deliverables/viewer/app_view.json` from `state.json`, `logs.jsonl`, the BEM
  manifest and the export folder. `to_json()` sorts keys and every timestamp is
  injectable, so two emissions of the same state are **byte-identical** (golden
  test against a trimmed real JBL state). Includes the `first_run` fixture
  (`run: null` + the five required questions), the ordered next-action rule table,
  the gate table, the manual-BEM block, the import panel, the outcome block and the
  viewer annotations.
* **M2 — the shell.** `hornflow/viz/viewer/index.html` gained the tab strip, the
  three `<section>` panes, `__APP_VIEW__`, and two additive buttons (`Dimensions`,
  `m`/`mm`, **default metres** per the decision). New `viewer/ui/{app.js,app.css}`.
  `write_viewer(..., app_view=…, annotations=…, glb_source=…)` fills and copies
  them. **The viewer's own markup and script are untouched** — a test asserts the
  original markers survive, and a run without `app_view` renders only the Viewer
  tab. Inactive panes use `visibility: hidden`, so the canvas never measures zero.
* **M3 — the Workflow tab.** W1–W8 rendered from the embedded model only: current
  state, next action, gates, the five questions, the manual AKABAK checkpoint
  (chain tracker + the verbatim "why manual" + nine checklist items with
  browser-local ticks), the `.vips` import panel, the validation outcome (8-check
  table + comparison + verdict) and the rerun panel. **No mutating action**: every
  state-changing button is disabled with a reason and paired with a `Copy command`.
  The Results tab is a labelled placeholder.
* **One write, after the state is saved.** `stage_report()` now only records the
  expected viewer paths; `_finalize()` writes `viewer.html` + `app_view.json`
  *after* `save_state` and `log.flush`, so the embedded snapshot and `state.json`
  cannot disagree (asserted).
* **`--emit-ui [RUN_DIR]`** re-renders the shell of an existing run from the saved
  state and the existing `scene.glb`, without re-running the pipeline and without
  touching `state.json` — this is how the pre-existing validated JBL run got the
  UI (`mode: review`, `BEM_VALIDATED`).
* Fixed a **flaky test I had written** in the previous session:
  `test_vips_roundtrip_preserves_finite_levels` sampled float frequencies that both
  format to `20` under `%.10g`, producing a legitimate duplicate grid point.
  Hypothesis found it; the strategy now uses integer Hz.
* Tests: legacy **147/147**; pytest **94 → 122 passed** (new
  `tests/test_app_view.py`, 28 tests).
* Docs: `docs/app-local-multitab.md` §20.1 (status + implementation notes),
  `docs/adr.md` ADR-0011, `docs/ui-two-tab-mvp.md` D3 (metres), `README.md`.

## 2026-10-04 — the project becomes a git repository

* `git init -b main`; the whole tree is now versioned except what is generated.
* **Ignore policy** (`.gitignore`): `runs/` and `results/` (both generated),
  `AKABAK/` (426 MB of third-party Windows binaries — RDTeam's distribution, not
  ours), `.hypothesis/`, `.pytest_cache/`, `__pycache__/`, editor noise. The
  tracked tree is **130 files / 3.0 MB**. `AKABAK/` stays on disk; the pipeline
  only needs its path.
* **Moved the `.vips` test data** from `results/jbl_1200b/bem/export/` to
  `tests/fixtures/bem_export/` (21 files, 288 KB) and pointed
  `tests/test_bem_manual.py` at the new path, so `results/` can be ignored
  wholesale. This is the one behaviour-free refactor in the change.
* **`.gitattributes`**: `tests/fixtures/**` and `*.vips` are `-text`, because
  `tests/test_baseline.py` asserts the sha256 of the frozen `curves.csv` and the
  AKABAK exports are CRLF by construction.
* **Branch rules** (`CONTRIBUTING.md`): `main` is read-only; every change starts
  on `<type>/<slug>` and lands through a PR; Conventional Commits; one logical
  change per commit; both suites must pass on the branch tip; the four working
  documents (`history.md`, `handoff.md`, `docs/adr.md`, `docs/migration-notes.md`)
  move in the same PR as the change they describe.
* **Enforcement**: `.githooks/pre-commit` refuses to commit while `HEAD` is
  `main` (override `HORNFLOW_ALLOW_MAIN_COMMIT=1`, used once for the baseline
  import). Enabled with `git config core.hooksPath .githooks`. A PR template
  (`.github/pull_request_template.md`) asks for the two test result lines, the
  honest cost, and the deferrals.
* **CI**: `.github/workflows/ci.yml` runs the legacy checks, the frozen baseline,
  the pytest suite and both CLI entry points on Python 3.10–3.12, and asserts the
  generated viewer shell is self-contained.
* The baseline import is commit `c421f86` on `main`; the repository-process change
  is on the branch `chore/repo-process-and-ci`, ready to push.
* Remote: `origin = git@github.com:AlleeCabral/horn-workflow.git` (SSH auth
  verified: `Hi AlleeCabral!`). The GitHub repository does not exist yet —
  `gh` is not installed and there is no token in this environment, so the remote
  has to be created before the first push.
* Tests: legacy **147/147**; pytest **122 passed** (unchanged by the fixture move).

## 2026-10-04 — Phase 1: the excursion convention, and the W4 completion contract

Branch `fix/excursion-rms-and-workflow-contract` (2 commits, local; the remote
repository still does not exist).

### 1a — rms vs peak excursion (a real data error, in the unsafe direction)

* **Proved the convention from the generating calculation**, not from the label:
  `response.simulate()` drives the lumped-element network with `sim.voltage` in
  **volts rms**, so `current = V/Ze`, `velocity = Bl·I/Zm` and
  `excursion = velocity/(jω)` are all rms phasors (cross-check: `I_abs` = 0.6937 A
  = 2.83/4.079 exactly).
* Therefore the `curves.csv` column named `excursion_peak_mm` held **rms**. Every
  "Xmax is reached at …" figure was optimistic by √2 in voltage and **2× in power**:
  the report said **~59 V / ~952 W**, the truth is **~41 V rms / ~476 W**. The hard
  gate also compared rms travel against a one-way-peak Xmax.
* **`hornflow/domain/excursion.py` is new and is the single source of truth**:
  `RMS_TO_PEAK`, the Xmax convention (`one_way_peak` default, `peak_to_peak`
  converted by /2, validated — never guessed), `summarize()` and `excursion_gate()`.
  `driver.Xmax_convention` is now a validated field with `Xmax_one_way_peak`.
* **curves.csv v2**: `… I_abs, excursion_rms_mm, excursion_peak_mm, p_abs_Pa …`.
  New `report.read_csv()` detects the v1 header, migrates **in memory** with an
  explicit note, and never reinterprets the numbers.
* **state.json 1.0 → 1.1** with a registered migration that renames
  `simulation_runs[].excursion_m` → `excursion_rms_m`, derives `excursion_peak_m`,
  and **records itself** in the new `state.migrations` list (explicit, not silent).
* Updated: `report.py` (CSV, guidance, `excursion_power_text` now takes the summary),
  `plots.py`, `advise.py` (also fixed the `×7.07` "100 W" fudge to `√(100·Re)/V₀`
  = 6.74), `gates.py`, `sweep.py`, `sensitivity.py`, `webster.py` (both columns in
  the normalized run schema), `reporting/markdown.py`, `orchestrator.py`.
* **Baseline regenerated once, deliberately.** Every physical metric is unchanged
  (104.5344 dB, 8.0293 dB, Zmin 4.0424 Ω); the manifest now carries
  `excursion_rms_max_mm` 0.54858 **and** `excursion_peak_max_mm` 0.77581.
* The corrected report line now reads: *"0.55 mm rms / 0.78 mm one-way peak at
  33 Hz with 2.83 V rms – the peak travel is 7 % of the driver's 11.4 mm Xmax
  (one-way peak) … about 41 V rms (~476 W)"*.

### 1b — W4 could say "wave A complete" with required values blank

* **Root cause:** `app.js` computed group and wave completion itself (counting any
  non-null value as answered, and marking a group blocking only on a *first run*).
  A **path-less required field could never be answered at all**, so the old model's
  numbers were doubly wrong.
* **Fix:** `app/view.py` now emits `completion` (per-field `accepted`, per-group
  `complete`/`required_answered`/`blocked_by`/`first_unanswered`, per-wave
  `complete`, and a flat `blockers` list with `next_required_field`). Acceptance
  requires present + not-UNKNOWN + provenance + confidence; optional blanks never
  block; `app.js` renders and no longer computes.
* Field resolution order is now brief-by-path → brief-by-key → run-state-by-path,
  which is what makes the path-less required fields answerable.
* Human labels + help text moved into the model (`FIELD_LABELS`, `FIELD_HELP`,
  `OPTIONAL_FIELDS`); the internal key survives only as a tooltip.
* **Honest numbers on the real JBL run:** 7 of 20 required answers, 13 blockers,
  wave A **incomplete**, next required = "What is it for?" — where the old UI said
  the opposite. 20 required of 22 declared fields (2 optional).
* `view_schema` 1.0 → 1.1. W4's field rows are now label-once / value-once /
  provenance-below, with a left rule on the fields that actually need input.

### Tests

legacy **147/147**; pytest **122 → 159 passed** (new `test_excursion_convention.py`,
27 tests; 10 new completion tests in `test_app_view.py`). One old test that encoded
the *wrong* behaviour ("no group is blocking when a run exists") was replaced with
the honest contract. A real pipeline run still produces a viewer with
`view_schema 1.1` and the corrected excursion wording.


# CURRENT STATE
**Model (GUI, `~/AI projects/horn design/Saved/`):**

| item | value |
|---|---|
| current project | **`Rad1_23Sept26.akp`** (23 Sept 23:50) — the validated state |
| fallback | `Rad1_22Sept26.akp`, `Jbl1200B_horn_19Sept26.akp` (full mesh), `Jbl1200B_horn.akp` (18 Sept) |
| mesh | Mesh File object → **`bem_quarter.msh`** (640 tri) |
| `Global → Dim, Sym and BEM` | Dimension 3D, **Symmetry = xy**, NUC = None |
| `Global → Meshing` | Edge Length **empty** |
| frequencies | 60–200 Hz, logarithmic, N = 24 |
| Level of Driving | 2.83 V, *Is rms* ✓ (⇒ V_pk = 4.0 V) |
| BEM tree | `Throat` = Driven, `Hornwall`, `Mouth` interface (Interior↔Exterior); `baffle` unused |
| LEM | `S1` (Electric/Potential/Weight 1) → `Dyn1` (`s`), `GND` (`t`), `Dyn1 u` → `Rad1` (Ref to BEM = Thoat), `Dyn1 v` → `Encl` Vb = 0.028 m³ |
| Diaphragms | `Diaph front` = `Diaph rear` = 259.43 mm, **not referenced** |
| observations | `Mic1` (0,0,2.499 m), `H 0-90`, `RadImp1`, `LE1` x-mo, `LE2` Z-in, `LE3` I_s, `LE4` q_u, `LE5` p_u0, `LE6` v_mo, **`LE7` V_st** |
| measured at 60 Hz | V_st 4.0022 V, I_s 0.2139 A, v 0.2523 m/s, x 0.669 mm, q 0.0133 m³/s, p_u0 68.8 Pa, Ze 18.71 Ω, SPL 87.7 dB (rms-ref) |

**Verdict:** the electrical drive, the mechanical chain, the diaphragm areas and the
LE↔BEM coupling are **verified correct**. The remaining difference to Stage 1 is
**mounting condition** (free-standing 4π vs baffled 2π), not an error.

# NEXT STEP — the infinite-baffle test (≈4 min)

Goal: reproduce Stage-1's half-space assumption and prove the remaining SPL offset.

1. In AKABAK: `File → Save As…` → `Jbl1200B_horn_19IB.akp` (keeps the free-standing state).
2. Page **`BEM`** → `Edit → New Component…` → **`Infinite Baffle`** → `Apply`.
3. Position its plane **at the mouth**: `(0, 0, 1.499) m`, normal into the radiating
   half-space (**+z**), rotations 0. (The IB is a special Green's function —
   `vn = 0` on the plane — *"there is no need to model the infinite plane"*.)
4. The IB is the **home** of the exterior subdomain (BEM-Part/Form-Infinite-Baffle):
   check the tree shows `Exterior` nested under the IB; if not, assign it there.
5. `Processing → Calculate All` (changing the radiation condition ⇒ full BEM re-solve, ~1–4 min).
6. Read: `Log Calc` (`Elements (total)` ≈ 1398), then `Ob Spectra` / `Ob Fields`.

| expected | why |
|---|---|
| on-axis SPL up **~3.5 dB** | half-space concentrates the power into 2π (Stage-1 `di_db` = 3.45) |
| excursion **down** | the mirror image doubles the mouth's air-mass loading |
| current / Ze move toward Stage 1 | the mouth boundary condition changes the horn's input impedance |

If SPL lands within a couple of dB of Stage 1 and the excursion ratio → 1.0, the model is
fully validated. If the horn will be built **into a wall or corner**, the IB is also the
*realistic* model — keep it; if it stands free, keep `Rad1_23Sept26.akp` and expect the −8 dB.

# OPEN ITEMS
1. ~~`--bem-import` cannot read the `*.vips` files yet~~ **DONE (2026-10-03)**: the
   `.vips` parser, the 8-check validation, the manifest and the manual-solve state
   machine are implemented; `compare.md` / `compare.png` are generated by the
   importer. Remaining: run the infinite-baffle re-solve (see NEXT STEP) so the
   −8.7 dB offset closes and the folded candidate can be `BEM_VALIDATED` at the
   default tolerance.
2. `excursion_peak_mm` in `curves.csv` is rms (mislabelled) → rename to `excursion_rms_mm` or
   ×√2; also affects the X_max statements in the report.
3. Optional: `Mic Field (Mesh File)` with the **`interface`** tag → colour map painted *on the
   mouth plane* (no gap, by construction); use `Edge Length 0.1 m` there (→ trustworthy to 1715 Hz).
4. Optional: `--to-csv` / `--plot-field` converters so exported curves/fields can be plotted
   in REW, gnuplot, ParaView or matplotlib.
5. Optional: a `--bem-import` golden test against a stored `.vips` pair is in place
   (`tests/test_bem_manual.py`); further coverage could add a stored *current-project*
   `.vips` snapshot once the IB re-solve is done.

# DEFERRED RESEARCH — *read later, do not run now*
* **ATH4 thread / horn-design simulator knowledge base**
  <https://www.diyaudio.com/community/threads/acoustic-horn-design-the-easy-way-ath4.338806>
  1000+ pages of practical horn design and simulator know-how (ATH4, ABEC/AKABAK,
  Hornresp, meshing and observation practice). To be **scraped/read after the current
  verification run**, primarily for:
  1. cross-checking our BEM settings (mesh frequency, symmetry, NUC) against
     experienced users;
  2. the free-standing vs baffled (4π / 2π) question — the origin of the remaining
     SPL offset;
  3. observation practice: directivity normalisation, field vs balloon output,
     throat-adaptor geometry.
  Not required for the infinite-baffle test.
