# horn-workflow

A horn design **workflow**, not a GUI: you edit one text file of numbers, run one
command, and read a report that tells you what the horn will do, how big it will
be, and which of several options is worth building.

> **Contributing.** `main` is read-only: every change starts on a short-lived
> branch (`feat/…`, `fix/…`, `docs/…`) and lands through a pull request. See
> **[`CONTRIBUTING.md`](CONTRIBUTING.md)** — a `pre-commit` hook enforces it.

You do **not** need to know loudspeaker engineering to use it. You do need to know
two things about your situation: **how big a box you can live with** and **which
frequency range you care about**. The tool derives the mouth, the depth, the throat
and the flare from those.

Everything the model uses is taken from one reference:

> B. Kolbrek, *Horn Theory: An Introduction*, Parts 1 & 2, audioXpress 2008
> (`docs/an-introduction-to-horn-theory.pdf`, shipped in the parent folder)

> **Resuming this project?** Read **[`history.md`](history.md)** first: it holds the
> AKABAK + manual commands, the folder map, the ground rules (demo limits, symmetry,
> wiring, exports) and the current state / next step of the Stage-2 verification.


---

## Quick start

```bash
cd '/home/alex/AI projects/horn-workflow'

# 1. One design: everything in the definition file is simulated and reported
python3 run_workflow.py params/horn_jbl_1200b.yaml

# 2. Advice: derive the geometry from a size budget (mouth + depth for each cut-off)
python3 run_workflow.py params/horn_jbl_1200b.yaml --advise --advise-depth 1500

# 3. Comparison: run a grid over any two parameters and rank the results
python3 run_workflow.py params/horn_jbl_1200b.yaml --sweep

# 4. Build package: profile, slice stack, STL solid, BEM mesh, build sheet
python3 run_workflow.py params/horn_jbl_1200b.yaml --build

# 5. Stage 2: the AKABAK inputs (BEM mesh, LE driver script, run manifest, run checklist)
python3 run_workflow.py params/horn_jbl_1200b.yaml --stage 2

# 5b. ... optionally with a cut half/quarter mesh for `Symmetry = x|y|xy` (minutes
#     instead of hours per solve - the demo cannot cache a BEM solution)
python3 run_workflow.py params/horn_jbl_1200b.yaml --stage 2 --bem-symmetry xy

# 6. ... and after the manual GUI solve, validate + compare the exported .vips
python3 run_workflow.py params/horn_jbl_1200b.yaml --bem-import ~/akabak_export

# 7. Self-check the physics (147 checks against the paper)
python3 tests/test_theory.py
```

### Gated folded-horn pipeline (new)

The same YAML now also drives a full **gated, state-driven** design pipeline that
prefers a folded horn but honestly reports when another architecture wins:

```bash
python3 -m hornflow.cli params/horn_jbl_1200b.yaml --out runs
#     or:  python3 run_pipeline.py params/horn_jbl_1200b.yaml
```

It runs 16 stages (input audit → limit-impact → feasibility → architecture
screening → ideal reference → fold generation → fold validation → 1-D simulation
→ fold-aware → 3-D BEM inputs → structural screen → manufacturing → sensitivity
→ independent critique → final comparison → report) and writes, per run:

* `runs/<run_id>/state.json` — the versioned design state;
* `runs/<run_id>/deliverables/report.md` — the 20-section report (input audit,
  limit-impact table, architecture comparison, best folded horn **and** best
  overall design, fold/bend tables, sensitivity, evidence labels, critic);
* `runs/<run_id>/deliverables/viewer/viewer.html` — a self-contained,
  **offline** interactive 3D view (orbit/zoom, transparent + cutaway,
  centreline, area stations) plus `scene.glb`;
* `deliverables/printed.stl` (watertight shell) and a faceted plywood variant
  schedule; `step`/`3mf`/`vtu` are documented deferred stubs.

Nothing in the legacy workflow changed: `run_workflow.py` and all of its outputs
are byte-for-byte as before. See `docs/adr.md` and `docs/migration-notes.md`.
The planned first UI layer is specified in `docs/app-local-multitab.md` — the
existing viewer becomes the app shell with **Viewer**, **Workflow** and (placeholder)
**Results** tabs, local-first and run-centred, with no new dependencies. Earlier
design passes (a Jira issue panel, then a Forge-oriented two-tab MVP) are kept in
`docs/jira-issue-flow.md` and `docs/ui-two-tab-mvp.md`; their hosting decisions are
superseded (see ADR-0011), but their field/question/gate work carries over.

```bash
python3 -m pytest tests/ -q      # new suite (baseline, domain, fold, pipeline, bem_manual)
```

### The manual AKABAK round trip (inputs → GUI → validated import)

AKABAK runs under **Wine through its GUI** (Free 3.3.2 b144), there is **no
usable head-less/CLI solve path** here, and the Free/demo build **does not write
the solved BEM state** (`.akpbe`) - it stays in RAM. So HornFlow generates
*every* input automatically, and the human does the documented GUI actions:

```bash
# 1. generate the inputs, the run manifest and the run checklist
python3 -m hornflow.cli params/horn_jbl_1200b.yaml --out runs
#    deliverables/bem/{bem.msh, driver_le.txt, bem_manifest.json, akabak_recipe.md}

# 2. do the manual GUI solve (follow the checklist), then export the .vips
#    spectra into  runs/<run_id>/deliverables/bem/export/

# 3. validate + compare; the run is resumed and its state updated
python3 -m hornflow.cli params/horn_jbl_1200b.yaml \
        --bem-import runs/<run_id>/deliverables/bem/export \
        [--bem-tolerance-db 6]
```

The importer checks all eight required properties (exists, non-empty, belongs to
the run, valid frequency grid, required pressure spectrum, numeric finite values,
newer than the generated inputs, manifest match), then compares the on-axis curve
with the 1-D reference. **A candidate is never marked `BEM_VALIDATED` before that
import *plus* comparison has run**; the state machine
(`INPUTS_GENERATED → GUI_REQUIRED → MANUAL_SOLVE_PENDING → MANUAL_SOLVE_COMPLETED
→ VIPS_IMPORTED → BEM_COMPARISON_COMPLETED → BEM_VALIDATED | BEM_REJECTED`) is
recorded in `state.json` and `bem_manual_report.md`.

### The local UI: three tabs, one file (M1–M3)

Every run now writes a small **single-page app** beside the report. It is the same
offline viewer, extended with a tab strip — no server, no accounts, no build step,
no new dependency:

| tab | what it is |
|---|---|
| **Viewer** | the geometry, unchanged, plus a `Dimensions` overlay (default **m**, `mm` toggle) |
| **Workflow** | a persistent current-state summary, then the nine process stages as **accessible accordions** — each showing its own answers and gates, with the current stage open by default. Locked stages stay visible, collapsed, with the reason. Includes the manual AKABAK checkpoint, the `.vips` import panel, the validation outcome and the rerun panel. Everything is read from the model: the browser never computes completion. |
| **Results** | a labelled placeholder for the next milestone |

Screenshots of the redesign (and of the tab it replaced) are in
[`docs/ui/`](docs/ui/README.md); regenerate them with `tools/shoot_ui.sh <run_dir>`.

The nine Workflow stages are: Project and deployment · Driver and provenance ·
Safety and electrical limits · Acoustic target · Envelope and manufacturing ·
Architecture selection · Acoustic and folded design · Verification and AKABAK ·
Final decision.

```bash
python3 run_pipeline.py params/horn_jbl_1200b.yaml --out runs
# open the newest run's UI (offline; the GLB is embedded, so file:// works)
firefox runs/<run_id>/deliverables/viewer/viewer.html
# or over http (recommended - no browser file:// restrictions)
python3 -m http.server 8765 --directory runs/<run_id>/deliverables

# refresh the UI of a run that already exists (e.g. after --bem-import),
# without re-running the pipeline and without touching state.json:
python3 -m hornflow.cli params/horn_jbl_1200b.yaml --out runs --emit-ui [RUN_DIR]
```

The page renders a **HornFlow-emitted view model** (`deliverables/viewer/app_view.json`,
also embedded in the HTML): `hornflow/app/view.py` derives it from `state.json`,
`logs.jsonl`, the BEM manifest and the export folder. The UI never reads `state.json`
and never computes anything — it is a renderer plus copy-command buttons until M4
adds the local host. Every run made before this change still opens as a plain viewer.

Outputs land in `results/<project>/` (`report.md`, `curves.csv`, five figures) and,
depending on the mode, in `results/<project>/build/`, `results/<project>/bem/`,
`results/<project>/advise/` and `results/<project>/sweep/`.

## The five modes

| mode | you supply | you get |
|---|---|---|
| **single** (`run_workflow.py file.yaml`) | a complete geometry (or a mix of fixed + `auto`) | `report.md`: size, cut-off, SPL, impedance, excursion, plain-language verdicts, warnings |
| **advice** (`--advise`) | band + **depth limit** (+ mouth aspect) | which cut-offs fit, the mouth (W x H) and depth for each, the lowest cut-off your depth allows, ranked candidates, and **how much the horn beats the same driver without it** |
| **sweep** (`--sweep`) | two parameters to vary | a table of every combination, shortlists (smoothest / smallest / deepest / best covering your band), heat map and overlay curves |
| **build** (`--build`) | slice thickness + wall thickness | `profile.csv`/`.dxf`, `slices.csv`/`.dxf` (one outline + frame per slice), `horn.stl` (closed solid), `horn.msh` (BEM mesh), `build_sheet.md` with dimensions, material estimate and the verification table |
| **stage 2** (`--stage 2`) | nothing | `bem.msh` (MSH 2.2, groups: source / wall / interface / baffle), `driver_le.txt` (your measured T/S values in ABEC/AKABAK syntax), `bem.geo`, `bem_manifest.json`, `akabak_recipe.md` (run-specific checklist) |

`--bem-symmetry x|y|xy` writes an extra cut mesh (`bem_half.msh` / `bem_quarter.msh`,
same tags, areas 1/2 or 1/4, nothing crossing the plane) to go with
`Global → Dim, Sym and BEM → Symmetry`: the help quotes the system matrix shrinking to
**1/4** (one plane) or **1/8** (two), which turns a multi-hour full-model solve into
minutes - and the demo cannot cache BEM results, so every solve pays it again.

`--bem-import <folder>` closes the loop: it **validates** the returned export
(eight checks - exists, non-empty, belongs to the run, valid frequency grid,
required pressure spectrum, numeric finite values, newer than the generated
inputs, manifest match), reads AKABAK's `.vips` / VACS text export(s), writes
`bem/curves_stage2.csv`, `bem/compare.md`, `bem/compare.png` and
`bem/bem_manual_report.md`, and shows where the 1P model and the 3D solve
disagree. `--bem-tolerance-db N` sets the `BEM_VALIDATED` threshold (default 6 dB).

### The build package in practice

The mouth of the locked design is 1.60 m across, so it is built as a **stack of
100 mm slices**: `slices.dxf` has every slice outline (the hole) and its frame
(outline + 18 mm wall), laid out in a grid with the z range in the layer name.
`profile.dxf` is the wall curve for a lofted/fibreglass build, and `horn.stl` is a
closed solid for printing or CNC'ing a mould. `build_sheet.md` also reports what
the material costs you: **57 litres of wall (~43 kg MDF)** for this design.

One detail to know: the *nominal* mouth (1599 x 1000 mm) and the *built* outline
(1641 x 1025 mm, soft corners) differ because a rounded rectangle needs slightly
larger extremes to enclose the same 1.60 m² area. The report quotes the nominal
rectangle, the build sheet quotes both, and both are 1.60 m².

`gmsh` is optional: if it is installed the workflow also writes `horn.geo` and
meshes it (`horn_from_geo.msh`/`.stl`) as a cross-check. `horn.stl` and `horn.msh`
never depend on it.

## Your locked design (JBL 1200B, sealed 28 L chassis)

Derived, not guessed:

| item | value | why |
|---|---|---|
| throat | **260 mm** | 1.00 x the driver's Sd (direct coupled, no compression) |
| flare cut-off | **62 Hz** | the sweet spot your 1500 mm depth allows |
| mouth | **1599 x 1000 mm** rectangular, 1.60 m², 1.6 : 1 (built outline 1641 x 1025 with soft corners) | k*rm = 0.81 at the cut-off (paper: 0.7-1 for bass horns) |
| depth | **1500 mm** | your limit, fully used |
| predicted band | **60-200 Hz, 104.5 dB mean, 8.0 dB p-p** at 2.83 V / 1 m | Stage-1 model |
| gain over the same driver direct-radiating | **+13 dB average** in 60-200 Hz | why the horn is worth building |
| excursion | 0.55 mm **rms** / 0.78 mm **one-way peak** at 2.83 V rms = **7 % of the 11.35 mm Xmax** | Xmax would be reached at ~41 V rms / ~476 W, so it is thermally limited, not travel limited |

**Hard limit from physics:** with 260 mm throat and 1500 mm depth, the lowest cut-off
that still meets the mouth criterion is **58.7 Hz**. Lower than that needs a deeper
horn or a bigger mouth.

---

## The definition file: what you may change

Units: length mm, area cm², volume cm³, mass g, compliance m/N, force T·m,
inductance mH, resistance ohm, frequency Hz, voltage Vrms, distance m, angle deg.

| item | meaning | notes |
|---|---|---|
| `target.f_low` / `f_high` | the band you care about | everything is judged inside it |
| `target.fc` | flare cut-off | a number (Hz) **or `auto`** = derived from the mouth and the depth |
| `target.krm_target` | mouth criterion when the mouth is `auto` | paper: 0.7-1 bass, ≥1 mid/tweeter |
| `horn.profile` | `exponential` / `hyperbolic` / `conical` / `os` / `tractrix` | exponential is the classic bass horn |
| `horn.throat_diameter` | throat = 2 × throat radius | for a cone driver use ≈ 0.6-1.0 × the cone diameter |
| `horn.length` | depth | a number (mm) or `auto` |
| `horn.mouth_radius` | half the mouth width (equal-area circle) | mm, or `auto` |
| `horn.mouth_area` | mouth area (alternative to `mouth_radius`) | cm² (16000 = 1.6 m²) |
| `horn.mouth_shape` | `round` or `rectangular` | rectangular needs `mouth_aspect` |
| `horn.mouth_aspect` | width / height for a rectangular mouth | 1.0-4.0; > 1 = wider than tall |
| `driver` | a filename (e.g. `jbl_1200b.yaml`) or an inline block | the file lives in `params/drivers/` |
| `simulation.voltage` | drive level for the SPL plots | 2.83 V = 2 W into 4 ohm |
| `simulation.mouth_termination` | `infinite_pipe` / `piston_infinite_baffle` / `sphere` | how the mouth radiates |
| `sweep:` | dotted keys → list of values | used by `--sweep` |

**Rules:** at most one of `length` / `mouth_radius` / `mouth_area` may be `auto`; with
`target.fc: auto` you must give the mouth **and** the depth so the flare can be
derived. Wrong combinations are rejected with a message that says what to change.

## How to read the reports

* `results/<project>/report.md` - one design:
  1. design summary, 2. **what this means in plain language**, 3. how big a horn
  has to be for a range of cut-offs, 4. resolved geometry, 5. driver used,
  6. settings, 7. notes/warnings, 8. files, 9. what is and is not modelled.
* `results/<project>/advise/advise_report.md` - the size-budget answer: the lowest
  cut-off your depth allows, the mouth (W x H) and depth for every candidate, the
  gain over the direct radiator, and the ranking.
* `results/<project>/sweep/sweep_report.md` - grid comparison with shortlists and
  the trend ("a larger depth gives a flatter response", "where the cut-off lands
  matters more than any single dimension").

## What the model does and does not do

**Modelled** (Stage 1): driver loading including the mouth reflection (segmented
two-port line, exact conical segments), electrical impedance, diaphragm excursion,
on-axis SPL from the mouth volume velocity, directivity index of the mouth, rear
chamber, plus the design checks from the paper (flare constant, cut-off, k·rm mouth
criterion, 1P validity limit, the "how big for which cut-off" table).

**Not modelled**: diffraction at the mouth and edges, off-axis polars, higher-order
modes, 3D geometry, baffle/ground/room, phase plug and front cavity detail. Those
need the 3D solve: `--stage 2` writes the BEM model and the driver script, you run
AKABAK, and `--bem-import` brings the curves back into the report.

**Rectangular mouths**: the low-frequency model uses the **equal-area round horn**,
which is accurate for loading and on-axis response. The rectangle's directivity
(wide horizontally, narrower vertically) is a Stage-2 question.

## Where the physics comes from (paper → code)

| paper | code |
|---|---|
| Webster horn equation, 1P assumption | `theory.py` module docstring; the segmented two-port line |
| exponential flare `S = St e^(m x)`, `m = 4 pi fc / c` | `Design.m`, `solve_design()` |
| conical / hyperbolic / OS / tractrix contours | `Design.radius()`, `derive_fc()` |
| infinite throat impedance, Eqs. (7) and (9) | `infinite_throat_impedance()` (validated against the numeric line) |
| finite horn two-port, Eqs. (14)-(16) | `horn_abcd()`, `finite_throat_impedance()` (exact conical segments) |
| mouth terminations (pipe, piston in a baffle, sphere) | `mouth_impedance()` |
| mouth criterion `k·rm` (0.7-1 bass, ≥1 mid) | `Design.derived()`, all warnings |
| 1P validity limit `k·rt = 1` | `derived()["f_1P_validity_hz"]` |
| directivity `Q = 180²/(α·β)`, intercept `f_I` | `coverage_q()`, `intercept_frequency()`, `piston_q()` |
| cut-off ↔ mouth ↔ length relations | `derive_fc()`, `size_requirements()`, `advise.py` |
| rectangular mouth (equal-area round model) | `Design.derived()`, `mesh.section_outline()` |
| (build) section morphing, slice stack, solid | `mesh.py`, `build.py` |
| (stage 2) MSH 2.2, LE script, export parsing | `mesh.write_msh22()`, `bem.py` |

The driver side is the AKABAK lumped-element model, taken verbatim from the AKABAK
help file: `Re(f) = Re(1 + f/fre)^ExpoRe`, `Xe = w Le (1 + ExpoLe q²)/(1 + q²)`,
`q = w Le / Re`, plus `Mms`, `Cms`, `Rms`, `Bl`, `Sd` and the rear chamber volume —
exactly the parameters the ATH/ABEC LE scripts use, so Stage 2 can reuse them.

## Glossary (plain language)

| term | what it means here |
|---|---|
| **throat** | the small end of the horn, bolted to the driver |
| **mouth** | the big open end that radiates into the room |
| **flare** | the curve of the horn wall; its shape sets how the horn behaves |
| **cut-off (fc)** | the frequency below which the horn stops helping the driver |
| **k·rm** | mouth circumference measured in wavelengths at the cut-off; below ~0.7 the response gets peaky |
| **1P / Webster model** | the simple one-dimensional theory this tool uses (plane wave-fronts) |
| **BEM** | the 3D numerical method AKABAK uses for the full picture (Stage 2) |
| **excursion** | how far the diaphragm moves. The solver drives the network in **volts rms**, so its excursion column is **rms**; the report states both rms and one-way peak, and the **peak** figure is the one to compare with the driver's Xmax (data sheets quote Xmax one-way peak) |
| **variation** | peak-to-peak wobble of the on-axis response inside your band; smaller = flatter |
| **DI** | directivity index: how much the horn concentrates sound forward |
| **rear chamber** | the box behind the driver (your fixed 28 L chassis) |

## Driver data: measured vs estimated

`params/drivers/jbl_1200b.yaml` holds the **measured** Thiele-Small set (Sd 529 cm²,
Mmd 154 g, Cms 1.63e-4 m/N, Bl 13.6 T·m, Re 3.6 Ω, Rms 4.63, Le 2.3 mH, Fr 31.7 Hz,
Xmax 11.35 mm) plus the JBL data-sheet ratings. The model checks itself against the
measured `Fr`: the fs implied by `Mms`/`Cms` comes out **31.77 Hz vs 31.70 Hz
(+0.2 %)**, so the electrical and mechanical sets are consistent.

`Xmax` is optional but useful: when it is present the report says what fraction of
it the predicted excursion uses and at what drive voltage/power Xmax would be
reached (for this design: 0.55 mm rms / 0.78 mm one-way peak at 2.83 V rms, and
Xmax at ~41 V rms ~ 476 W - so it is
thermally limited, not travel limited).

## Tests

`python3 tests/test_theory.py` → **147 checks**, including: the paper's own OS-waveguide
example (1" throat, 60° → 862 Hz), the exponential/hyperbolic identities, the
numeric two-port line reproducing the analytic infinite-horn impedance (Eqs. 7/9)
to <1%, passivity of the throat impedance, mouth-impedance limits, ripple
decreasing with horn length, the AKABAK voice-coil model, the cut-off ↔ depth ↔
mouth relations used by `--advise`, end-to-end runs of the shipped projects, and
the Stage-2 side: section areas (the superellipse area formula), MSH 2.2 round trip,
the closed/oriented solid volume against the exact nested-body volume, DXF
structure, the LE script reproducing the measured fs, and the AKABAK export parser
(labels, comma/semicolon/tab separators, comments, unsorted rows, bad input).

`pytest` is optional; the file runs standalone and prints PASS/FAIL either way.

`python3 -m pytest tests/ -q` → **122 checks** on top of those: the frozen JBL
baseline, the versioned design state, fold topology + bend analysis + packaging,
the manufacturing transformers, Hypothesis properties, the whole 16-stage pipeline
end-to-end, and the manual-BEM layer (`tests/test_bem_manual.py`): the
manual-solve state machine and its legal transitions, manifest round trip and
determinism, the real `.vips` golden (87.73 dB at 60 Hz), each of the eight
validation checks, the `.vips` ↔ dB round trip property, the point-mic/newest
chooser, and a full run → synthetic export → validate → resume flow.

## Stage 2: AKABAK (3D BEM + lumped element)

ATH is deliberately **not** in the loop: it builds OS-SE and circular-arc profiles
only, while this design is exponential. Instead the workflow meshes its own
geometry (exact exponential contour, superellipse mouth) into MSH 2.2 and hands
AKABAK:

| file (in `results/<project>/bem/`) | used for |
|---|---|
| `bem.msh` | the BEM model: `source` (throat disk), `wall`, `interface` (mouth plane), `baffle` (optional ring) |
| `bem_quarter.msh` / `bem_half.msh` | the same model cut to a quarter / half (`--bem-symmetry xy|x|y`) for `Global → Dim, Sym and BEM → Symmetry` - 4x-64x faster solves, see step 11 of the recipe |
| `driver_le.txt` | the lumped-element driver in ABEC/AKABAK syntax (your measured values + the 28 L rear chamber), coupled to the source group |
| `bem.geo` | the same geometry as a Gmsh script (optional) |
| `bem_manifest.json` | the run manifest: run id, UTC stamp, solver + version, the expected export folder and globs, and the SHA-256 of every input handed over (used to validate provenance on import) |
| `akabak_recipe.md` | the **run-specific checklist** (run id, exact paths, expected filenames, tick-as-you-go BEM-tree/LEM/drive/solve/export steps, troubleshooting) followed by the detailed click-by-click recipe: start the project, load the mesh (Mesh File object, **Scaling = 1**), build the BEM tree + the LEM network (terminal map `s`/`t`/`u`/`v`), solve, **export the curves (VACS, or Preferences-VACS → Files)**, send them back |

The recipe uses the files already downloaded in `AKABAK/` (AKABAK Free 3.3.2 b144 is
unpacked into `AKABAK/free/`; start it with `AKABAK/akabak.sh`, which also registers
`VacsViewer.exe` as the COM server - without that registration the AKABAK-to-VACS link
pops up an error dialog on every recalculation). The free demo has the full solvers but
**does not write a solved-state file** and has **no head-less/CLI solve path** - hence
the manual GUI solve and the `.vips` export. Then:

```bash
python3 run_workflow.py params/horn_jbl_1200b.yaml --bem-import ~/akabak_export
```

validates the export against the manifest, writes `bem/curves_stage2.csv`,
`bem/bem_manual_report.md` (the eight-check table + the state), `bem/compare.md`
(a difference table at 60/70/80/100/125/150/200 Hz) and `bem/compare.png` (Stage 1
against every exported angle), and warns rather than guesses if it cannot parse your
export. The `.vips` reader handles CRLF, the `Data … Data_End` block, complex
`freq re im` rows, one pair per curve (polar angles from `Param_Coord_x2`), and
converts pressure to **rms-referenced** dB SPL by removing AKABAK's peak-rendering
convention (3.01 dB) - verified against the recorded 87.7 dB at 60 Hz.

**Until you run Stage 2, treat off-axis behaviour and the low end as indicative** -
the 1P model assumes plane wave-fronts, a baffled piston mouth and no diffraction.


