# Handoff prompt — paste into a fresh Cline session (Act mode)

> Companion to `history.md`. Copy everything below the `---` into a new session.

---

Continue the horn-workflow project: a horn subwoofer, verified in two stages.

ENVIRONMENT
- Working dir: /home/alex/AI projects/horn-workflow  (Linux, python3, no venv needed)
- READ FIRST, in this order — this is the whole context:
  1. history.md   <- the run-book. Frozen header = commands / paths / ground rules;
     below the divider: session history, then CURRENT STATE, NEXT STEP and OPEN ITEMS
     at the bottom. Jump straight to CURRENT STATE.
  2. README.md    <- what the workflow is and how to run it.
  3. results/jbl_1200b/bem/akabak_recipe.md  <- the AKABAK GUI procedure, click by click.
  4. params/horn_jbl_1200b.yaml + params/drivers/jbl_1200b.yaml  <- the design inputs.
- AKABAK 3.3 demo runs under Wine; I drive its GUI and you cannot see the screen.
  Launch: ./AKABAK/akabak.sh   Manual: AKABAK/free/Akabak.chm (extract with 7z; see §0
  of history.md). Exported data land in results/jbl_1200b/bem/export/ as plain-text *.vips
  files — parse those to verify anything I report.

FINAL GOAL
A parameterised workflow: I enter the horn/driver parameters in the YAML files, run one
command, and the horn is simulated end-to-end, with the two stages cross-checked:
- Stage 1: 1-D plane-wave (Webster) theory model, seconds, gives SPL / excursion /
  impedance / throat-impedance curves -> results/jbl_1200b/
- Stage 2: full 3-D BEM in AKABAK with a lumped-element driver network (files generated
  by hornflow/bem.py; the model is assembled in the GUI)
- Comparison: compare.md / compare.png between the two.
Stage 1 works today. Stage 2 is validated but still assembled by hand in the GUI;
reducing that manual work is part of the goal.

WHERE WE ARE (end of last session)
- Design: 480 L bass horn, ~80-250 Hz, JBL 1200B 12" driver, mouth 1599 x 1824 mm,
  axial length 1499 mm, 2.83 V rms drive.
- Stage 2 with symmetry xy (quarter mesh bem_quarter.msh, 1398 elements at Edge Length
  0.1 m): BEM solve 4 min instead of 50 (full mesh, 2688 elements).
- Everything in the model is verified: electrical drive (V_st = 4.0022 V peak = the
  intended 2.83 V rms), mechanical chain (q_u = v_mo*Sd, v_mo = x*w), diaphragm areas,
  and the LE<->BEM coupling (computed throat impedance 5158 vs 5157 Pa*s/m^3, 0.02 %).
- vs Stage 1: excursion within +/-2 dB; on-axis SPL is -4 ... -12 dB low (mean -8.6 dB).
- That residual is attributed to the mounting condition: Stage 1 assumes a baffled mouth
  radiating into 2*pi (its own DI = 3.45 dB); the BEM model is free-standing in 4*pi.
  Not an error — the thing to prove next.
- GUI project to resume from: ~/AI projects/horn design/Saved/Rad1_23Sept26.akp
  (symmetry xy, bem_quarter.msh, Rad1 = the LE<->BEM coupling, 7 LE observations).

THE NEXT STEP
The infinite-baffle test (~4 min) — full procedure in history.md -> NEXT STEP: add an
Infinite Baffle BEM component at the mouth plane (0, 0, 1.499) m, normal +z, with the
exterior subdomain nested under it; Calculate All; expect on-axis SPL up ~3.5 dB,
excursion down, and the input impedance to move toward Stage 1. If the offset collapses,
the model is fully validated.

OPEN ITEMS
1. --bem-import NOW reads the *.vips files (parser + 8-check validation + run manifest +
   manual-solve state machine + resume). What is left is on the AKABAK side: run the
   infinite-baffle re-solve below so the -8.7 dB offset closes and the folded candidate
   passes BEM_VALIDATED at the default 6 dB tolerance. The importer already reports
   mean -8.68 dB / worst 11.64 dB on the Rad1_23Sept26 export.
2. ~~excursion_peak_mm in curves.csv actually holds rms values~~ **DONE (2026-10-04)**.
   Proven from the generating calculation (drive is volts rms), fixed in
   hornflow/domain/excursion.py (single source of truth), curves.csv v2 carries
   excursion_rms_mm + excursion_peak_mm, report.read_csv() migrates v1 in memory,
   state.json is 1.1 with a recorded migration, and the gate compares peak travel
   against one-way peak Xmax. The X_max statement is corrected from "~59 V / ~952 W"
   to "~41 V rms / ~476 W" (it was optimistic by sqrt(2) in voltage, 2x in power).
3. Optional: Mic Field (Mesh File) + the "interface" tag -> colour map painted on the
   mouth plane; Edge Length 0.1 m there.
4. Optional: --to-csv / --plot-field converters for REW / ParaView / matplotlib.
5. DEFERRED RESEARCH, do NOT run yet: the ATH4 thread, 1000+ pages of practical horn and
   simulator know-how —
   https://www.diyaudio.com/community/threads/acoustic-horn-design-the-easy-way-ath4.338806

HARD CONSTRAINTS (see §2 of history.md)
- The demo cannot save the BEM solution (*.akpbe is never written), so BEM-Meshing /
  BEM-Solving are expensive: do not re-run them unless the acoustic boundary conditions
  change. LE-Solving, Ob Spectra, Ob Fields are cheap.
- File -> Save As... before every experiment.
- Symmetry xy only with the CUT mesh (bem_quarter.msh); Edge Length left empty normally.
- Terminal map: s/t = voice coil, u = diaphragm front -> horn, v = diaphragm rear ->
  enclosure. Couple the diaphragm to the BEM ONCE (Rad1 or the mesh reference, never both).
- AKABAK's dB display is peak-referenced (p0 = sqrt(2)*20 uPa) = +3.01 dB vs rms-referenced SPL.

WORKING STYLE
- Guide me with exact, ordered clicks, then verify by parsing the exported files (and the
  .akp project, which is a plain parameter dump) — don't trust my screenshots.
- /didactic <topic> = explain that topic from first principles (physics + analogy, then
  the concrete clicks).
- Keep history.md current: append a session entry and rewrite CURRENT STATE / NEXT STEP.

---

# NEW — gated folded-horn pipeline (added on top; legacy workflow unchanged)

HornFlow now also runs a **16-stage, state-driven** design pipeline that prefers a
folded horn but reports honestly when another architecture wins.

Run it:

```bash
cd '/home/alex/AI projects/horn-workflow'
python3 -m hornflow.cli params/horn_jbl_1200b.yaml --out runs   # or run_pipeline.py
python3 -m pytest tests/ -q                                     # 60 new tests
python3 tests/test_theory.py                                    # 147 legacy checks
```

What it produces (per run, under `runs/<run_id>/`):

- `state.json` — versioned design state (schema 1.0), `logs.jsonl` — stage log;
- `deliverables/report.md` — 20 sections incl. limit-impact table, architecture
  comparison, **best folded horn AND best overall**, fold/bend tables, sensitivity,
  evidence labels, and the independent-critic appendix;
- `deliverables/viewer/viewer.html` + `scene.glb` — offline interactive 3D;
- `deliverables/printed.stl` (watertight) + plywood variant; `step/3mf/vtu` are
  documented deferred stubs (`.DEFERRED.txt`), not faked.

Key facts to know:
- New packages: `hornflow/{domain,io,physics,architecture,fold,manufacturing,viz,
  optimize,reporting,workflow,critique}` + `hornflow/cli.py`. The validated core
  (`theory.py`, `response.py`, `mesh.py`, `bem.py`, `build.py`, `report.py`) is
  untouched and wrapped, never rewritten.
- The new report package is `hornflow.reporting` (NOT `report`) — `report.py`
  already existed and must not be shadowed.
- Folded-horn preference is a scoring bonus applied only after the hard gates; the
  critic fails the run if the folded horn wins *only* because of the bonus.
- 3-D BEM: the pipeline writes AKABAK-compatible inputs for the folded mesh and
  marks the external solve `pending` (GUI/Wine); stage 10 is `skipped` by design.
  **The manual step is now a first-class part of the workflow:** the pipeline also
  writes `bem_manifest.json` (run id, stamps, input SHA-256s, expected export
  dir/globs) and a run-specific `akabak_recipe.md` checklist; `--bem-import`
  validates the returned `.vips` (8 checks), compares with the 1-D reference and
  advances the manual-solve state machine
  (`INPUTS_GENERATED → GUI_REQUIRED → MANUAL_SOLVE_PENDING → MANUAL_SOLVE_COMPLETED
  → VIPS_IMPORTED → BEM_COMPARISON_COMPLETED → BEM_VALIDATED | BEM_REJECTED`).
  A candidate can never be `BEM_VALIDATED` without that import *plus* comparison.
- Dependencies: production = numpy/scipy/PyYAML/matplotlib; test = pytest+
  hypothesis (installed); pyarrow/trimesh/meshio/gmsh/pyvista/vtk/CadQuery are
  approval-gated and NOT installed.
- Docs: `docs/adr.md` (decisions), `docs/migration-notes.md` (layout + run map +
  the manual AKABAK section).

# NEXT STEP
0. **Phases 1 and 2 are done** on the branch
   `fix/excursion-rms-and-workflow-contract` (3 commits, not yet pushed — the
   GitHub remote still has to be created).
   * Phase 1 fixed a real data error (rms vs peak excursion, in the unsafe
     direction) and the W4 completion contract.
   * Phase 2 made the Workflow tab nine progressive accordion stages driven by
     `app/view.py`; before/after screenshots are in `docs/ui/`, regenerable with
     `tools/shoot_ui.sh <run_dir>`.
   Remaining phases of the current programme, in order:
   **3** the M4 local host (`python3 -m hornflow.app --run-dir runs/<id>`,
   `GET /api/view`, `POST /api/brief|run|import|decision`, `/api/progress`) — this
   is what makes the disabled buttons real and is the stated goal ("one real run
   end to end"); **4** the architecture tournament (a real tapped-horn model
   validated against a reference before it may win) and the three recommendation
   lanes; **5** two-candidate viewer comparison; **6** fold risk (the chosen U-fold
   is flagged ~290° path skew at 200 Hz); **7** one real JBL run end to end.
1. Read `docs/migration-notes.md`, then run the pipeline and read the report.
2. **Run the app** (M1–M4, local-first, no Jira):
   `python3 -m hornflow.app --run-dir runs/<run_id>` (or, with no run yet,
   `python3 -m hornflow.app --base params/horn_jbl_1200b.yaml --open`).
   It binds `127.0.0.1` only. Three tabs: **Viewer** (geometry + a `Dimensions`
   overlay, default metres), **Workflow** (nine accordion stages, the current state,
   the single next action, the manual AKABAK checkpoint, the `.vips` import panel,
   the validation outcome, the run box) and **Results** (placeholder).
   Editable fields, `Save draft`, `Freeze brief`, `Start run`,
   `Import & validate (.vips)` and `Accept as unvalidated` are **live** in this mode;
   opened from disk without a server the same page is a read-only snapshot and every
   mutating action becomes a `Copy command`.
3. A brief can now be answered entirely in the UI:
   five groups -> `Save draft` -> `Freeze brief` (writes
   `.hornflow/generated/<slug>.yaml`, *verified with the real `config.load()`*) ->
   `Start run` -> the pipeline runs in-process. **Verified on the real JBL project
   on 2026-10-05**: 20/20 answers, 15/16 gates, run
   `run_20261005T081734+0000_39db2c`, then the honest stop at `GUI_REQUIRED` with
   "Copy AKABAK checklist" as the next action.
4. Milestone next: **Phase 4 — the architecture tournament** (three recommendation
   lanes; a tapped horn needs a validated model before it may win), then **Phase 6 —
   fold risk** (the U-fold bend is flagged high-risk at 200 Hz), then **Phase 5 — the
   two-candidate Viewer comparison** and the Results tab.
5. Manual BEM loop, now supported end to end (from the UI, or from the CLI):
   `python3 -m hornflow.cli params/horn_jbl_1200b.yaml --out runs` generates the
   inputs + manifest + checklist; after the GUI solve, export the `.vips` into
   `runs/<run_id>/deliverables/bem/export/` and run
   `python3 -m hornflow.cli params/horn_jbl_1200b.yaml --bem-import <that dir>`
   (or press `Import & validate (.vips)` in the app). The importer picks the
   point-mic curve, removes the +3.01 dB peak convention and reports the difference;
   `--bem-tolerance-db N` sets the validated threshold, and the tolerance is never
   changed silently.

