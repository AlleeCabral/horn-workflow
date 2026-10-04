# Migration notes — Milestone 0 + vertical slice

## What was added (all additive; nothing validated was removed)

A gated, state-driven folded-horn design pipeline sits **on top of** the
existing HornFlow engine. The legacy `run_workflow.py` command and every file it
produces are unchanged.

New packages (all under `hornflow/`):

| package | layer | contents |
|---|---|---|
| `domain/` | 1 | `ids`, `evidence`, `limits`, `failures`, `geometry` (AreaLaw, Centreline, RMF, AcousticMaster), `state` (versioned) |
| `io/` | 2, 15 | `artifacts` (content-addressed, atomic), `state_store`, `logs` (JSONL) |
| `physics/` | 3, 6 | `feasibility`, `solvers/{base,webster,akabak}` |
| `architecture/` | 4 | `base`, `front_loaded`, `folded`, `sealed`, `reflex`, `box_models`, `registry` |
| `fold/` | 7, 8 | `base`, `paths`, `generators`, `evaluate`, `bends`, `packaging` |
| `manufacturing/` | 10 | `base`, `meshbuild`, `additive`, `plywood`, `exporters` |
| `viz/` | 11 | `gltf` (GLB writer), `export`, `viewer/` (offline Three.js) |
| `optimize/` | 12 | `sensitivity` |
| `reporting/` | 13 | `limit_impact`, `markdown` |
| `workflow/` | 14 | `stages` (16-stage DAG), `gates`, `orchestrator` |
| `critique/` | 14 | `critic` |
| `cli.py` | — | new pipeline CLI |

## How to run

```bash
# legacy (unchanged)
python3 run_workflow.py params/horn_jbl_1200b.yaml
python3 run_workflow.py params/horn_jbl_1200b.yaml --build

# new gated pipeline
python3 -m hornflow.cli params/horn_jbl_1200b.yaml --out runs
# or
python3 run_pipeline.py params/horn_jbl_1200b.yaml
```

Outputs land in `runs/<run_id>/`:

```
runs/<run_id>/
  state.json            # the authoritative versioned design state
  logs.jsonl            # structured stage log
  stages/<STAGE>/…      # intermediate artifacts
  deliverables/
    report.md           # the 20-section report
    limit_impact? (also under stages/LIMIT_IMPACT_ANALYSIS/)
    printed.stl         # watertight printed shell
    viewer/viewer.html  # offline interactive 3D (open in a browser)
    viewer/scene.glb    # glTF 2.0 binary
    step.DEFERRED.txt   # deliberate stub + reason
    3mf.DEFERRED.txt
    vtu.DEFERRED.txt
    bem/…               # AKABAK-compatible inputs for the folded mesh
```

## State schema

`schema_version = "1.0"`. Top level (see `domain/state.py::STATE_FIELDS`):
`run, project, requirements, driver, constraints, limit_impacts, feasibility,
architecture_candidates, acoustic_candidates, reference_profiles, fold_candidates,
simulation_runs, sensitivity_runs, manufacturing_variants,
visualization_artifacts, validation, critic_findings, decision_log,
final_recommendations, stages`.

Loading a state file whose `schema_version` is not the current one and has no
registered migration raises — the system never silently reinterprets old state.
Migrations are registered in `domain/state.py::MIGRATIONS` (currently empty;
1.0 is the first schema).

## Evidence labels

Every number is labelled `USER_INPUT`, `MEASURED`, `ANALYTICAL_ESTIMATE`,
`ONE_DIMENSIONAL_SIMULATION`, `BEM_SIMULATION`, `FEM_SIMULATION` or
`STRUCTURAL_SCREENING`. The report states the label per section.

## Dependency policy (per-milestone)

* Production (`requirements.txt`): numpy, scipy, PyYAML, matplotlib.
* Test-only (`requirements-dev.txt`): pytest 9, hypothesis 6.
* Optional, requires approval (`requirements-optional.txt`): pyarrow, trimesh,
  meshio, gmsh, pyvista, vtk, CadQuery — **none installed yet**.

## Deliberately deferred (not faked)

* **STEP** / **3MF** / **VTU** — need a CAD kernel / dedicated writer; stubs write
  a `.DEFERRED.txt` with the reason.
* **3-D BEM solve** — AKABAK runs under Wine via its GUI; the pipeline generates
  the complete BEM input (mesh + LE script + manifest + checklist) and marks the
  external solve `pending`. Stage `THREE_DIMENSIONAL_VERIFICATION` is `skipped`
  by design. See the dedicated section below.
* **Spiral / serpentine / 3-D folds** — extension points exist
  (`fold/generators.py`, `fold/paths.py`); straight, J and U are wired.

## Manual AKABAK solve: inputs, hand-over, validation (added this milestone)

The AKABAK step stays **manual by design** - this is not an unimplemented
feature. Verified environment (authoritative, do not re-litigate):

| fact | value |
|---|---|
| solver | AKABAK **Free 3.3.2 build 144** (`AKABAK_Demo_64r.exe`) |
| host | Linux, executed through the **Wine GUI** |
| head-less solve | **none usable** in this setup - unattended solving is not implemented |
| solved BEM state | the Free/demo build **does not write `.akpbe`**; it stays in RAM |
| exportable artifact | `.vips` spectra, exported manually, imported + validated by HornFlow |

### What HornFlow generates automatically

`deliverables/bem/` (pipeline) or `results/<project>/bem/` (legacy) receives:

* `bem.msh` - MSH 2.2 surface mesh (fold-aware cavity for the pipeline);
* `driver_le.txt` - the lumped-element driver script;
* `bem_manifest.json` - **run manifest**: run id, UTC timestamp, project, solver
  and version, the expected `export_dir`, the expected export globs, and the
  SHA-256 + size of every input handed over;
* `akabak_recipe.md` - the **run-specific checklist** (run id, exact paths,
  expected filenames, tick-as-you-go manual actions, troubleshooting, and the
  import command printed at the end).

### New modules

| module | responsibility |
|---|---|
| `physics/solvers/manual.py` | `ManualSolveState` + legal transitions + `RunManifest` I/O + the checklist builder |
| `physics/solvers/bem_manual.py` | the eight validation checks, the 1-D comparison, the import report |
| `workflow/bem_import.py` | `--bem-import` resume: validate, compare, advance the state machine, rewrite `state.json` |
| `bem.py` (extended) | real `.vips` parser, `parse_any` dispatch, shared folder/ranking/comparison helpers |

### Manual-solve state machine

```
INPUTS_GENERATED -> GUI_REQUIRED -> MANUAL_SOLVE_PENDING -> MANUAL_SOLVE_COMPLETED
  -> VIPS_IMPORTED -> BEM_COMPARISON_COMPLETED -> BEM_VALIDATED | BEM_REJECTED
```

The two decided states may only return to `VIPS_IMPORTED` (an explicit
**re-import** edge: a fresh export supersedes an earlier decision, and the old
decision stays in `decision_log`). A candidate can **never** be
`BEM_VALIDATED` before a `.vips` import *plus* comparison has run - the pipeline
leaves stage 10 at `GUI_REQUIRED`.

### The eight import checks

`expected_file_exists`, `files_non_empty`, `frequency_grid_valid`,
`required_spectrum_present`, `values_numeric_finite`,
`export_timestamp_after_inputs` (hard) and `belongs_to_run`,
`run_manifest_matches` (soft/provenance). A hard failure leaves the state at
`MANUAL_SOLVE_PENDING` and says what to fix; only a full pass reaches
`VIPS_IMPORTED`.

### The `.vips` parser

Real AKABAK 3.3.2 format: CRLF, `//` header, `Key=Value` metadata, a `Data` …
`Data_End` block. Complex rows are `freq re im` (one pair per curve; polar
observations carry one pair per angle from `Param_Coord_x2`). Pressure columns
(`Data_BaseUnit=Pa`) are converted to **rms-referenced** dB SPL by removing the
peak-rendering convention (3.0103 dB) - verified against the documented
checkpoint `Rad1_23Sept26 Mic1 @60 Hz = 87.73 dB`.

### Commands

```bash
# generate the inputs + the run checklist (also writes the manifest)
python3 run_workflow.py params/horn_jbl_1200b.yaml --stage 2

# after the manual GUI solve, validate + compare the exported .vips
python3 run_workflow.py params/horn_jbl_1200b.yaml --bem-import <export-dir>
python3 -m hornflow.cli params/horn_jbl_1200b.yaml --bem-import <export-dir> \
        [--bem-tolerance-db 6]
```

The pipeline CLI detects an export folder that lives inside a run directory and
**resumes that run** instead of starting a new one.

## Regression status at the end of this milestone

* legacy `tests/test_theory.py`: **147/147**
* pytest suite: **122 passed** (baseline, domain, fold/mfg, properties, pipeline,
  bem_manual, app_view)
* JBL baseline `curves.csv`: byte-identical to the frozen fixture

## Still deliberately deferred (not faked)

* **STEP** / **3MF** / **VTU** - need a CAD kernel / dedicated writer; stubs write
  a `.DEFERRED.txt` with the reason.
* **Unattended 3-D BEM solve** - not possible in this environment (see above).
  Inputs, the manifest and the checklist are generated; the GUI solve is human.
* **Spiral / serpentine / 3-D folds** - extension points exist
  (`fold/generators.py`, `fold/paths.py`); straight, J and U are wired.

## Schema migrations applied in this milestone

### curves.csv v1 -> v2 (header-based, in memory)

v1 header: `... I_abs, excursion_peak_mm, p_abs_Pa, spl_db, di_db` (11 columns).
The column called `excursion_peak_mm` held **rms** displacement.

v2 header: `... I_abs, excursion_rms_mm, excursion_peak_mm, p_abs_Pa, spl_db, di_db`
(12 columns). `excursion_peak_mm = sqrt(2) x excursion_rms_mm`.

`report.read_csv()` returns a `CurveTable` with `schema`, `migrated_from` and
`notes`. A v1 file is renamed in memory — **the numbers are never reinterpreted and
the file on disk is never rewritten**. `tests/test_excursion_convention.py` covers
detection, the values, and v1/v2 agreement.

### state.json 1.0 -> 1.1 (registered migration)

`simulation_runs[].excursion_m` (rms values under a peak-sounding name) becomes
`excursion_rms_m` plus a derived `excursion_peak_m`. The applied migration is
recorded in the new `state.migrations` list, so it is explicit and inspectable
rather than silent. `hornflow/domain/state.py` refuses any version with no
registered path forward.

### Deliberate baseline regeneration (once)

`tests/fixtures/baseline/{manifest.json,jbl_1200b_curves.csv}` were regenerated for
the header change. Every physical metric is unchanged (`spl_band_mean_db` 104.5344,
`spl_band_variation_db` 8.0293, `ze_min_ohm` 4.0424, ...); the manifest now records
`excursion_rms_max_mm` = 0.54858 alongside `excursion_peak_max_mm` = 0.77581
(= 0.54858 x sqrt(2)), plus the `curves_schema` and `state_schema` it belongs to.

