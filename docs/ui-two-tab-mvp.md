# Two-tab MVP UI — Viewer + Workflow

> **⚠️ SUPERSEDED (hosting only).** The project went **local-first**: the existing
> viewer *is* the app shell (no separate shell page, no iframe, no Forge). See
> **[`app-local-multitab.md`](app-local-multitab.md)** — the design now being built
> — and **ADR-0011** in `adr.md`.
>
> Kept because most of it still applies: the `workflow_view.json` contract, the
> W1–W9 layout (there W1–W8, plus Results), the five questions, the exact button
> labels, the eight-state transition table, and the edit/read-only matrix. The
> viewer's additive features (D1–D9, dimensions + side-by-side) are **carried over
> unchanged**.

Companion to `jira-issue-flow.md` (which defines the issue fields, the process
state machine and the Jira/HornFlow split). This document defines the **minimum
viable UI** that lets one real run be executed end to end: two tabs, no app shell.

## 0. Scope

**In:** the two tabs, the view-model contract, the first-run screen, the first five
questions, gate/transition rules, exact button labels, the manual AKABAK
checkpoint block, the imported-result block, the pass/fail block, the rerun flow,
and the Forge Custom UI plan.

**Out:** geometry editing, solver parameter editing, cost/scheduling, multi-user
locking, colouring by field data (needs per-vertex attributes — deferred).

## 1. Product brief

> **HornFlow UI v0** is a two-tab page generated per run. **Geometry** shows the
> chosen folded candidate in 3D (the existing viewer, unchanged in behaviour).
> **Workflow** shows where the run is in the process, what is still missing from
> the user, what the one next action is, and the manual AKABAK checkpoint with its
> returned-and-validated result. The UI is a **dumb renderer of a HornFlow-produced
> view model**: it never computes, never decides, and never invents state.

Goals: (1) one real run executed once, end to end; (2) the manual BEM step made
obvious; (3) zero new dependencies; (4) a shape that ports to Forge without a
rewrite.

Non-goals: replacing `run_workflow.py`/`hornflow.cli`; a Jira clone; live solver
control; dashboards for many runs.

## 2. Decisions on extra geometry features

These extend the existing viewer **additively**: everything is feature-detected, so
a scene without the extra data looks and behaves exactly as it does today.

| # | decision | implementation | fallback when data is absent |
|---|---|---|---|
| **D1** | **Dimensions are a toggle button**, not always-on. | New `Dimensions` button; overlay labels projected from 3D to screen-space DOM (crisp at any zoom). | button hidden |
| **D2** | Dimension figures come from a HornFlow-injected `annotations` JSON (second template placeholder, like the GLB). | `__ANNOTATIONS__` script block; values taken from `reference_profiles[0]`, `fold_candidates[i].packaging`, `bends`. | button hidden |
| **D3** | Dimension overlay has a **m/mm toggle**, default **m** (later decision — the earlier draft said mm). | viewer-local; state stays SI. | — |
| **D4** | **Side by side is a view mode**, not a second viewer: `Candidate` · `Reference` · `Side by side`. | embed up to **two** GLBs; `Side by side` puts both in one group, offsets the reference along X by its own bbox width + 10 %, refits the camera. | `Reference`/`Side by side` disabled; only `Candidate` shown |
| **D5** | The compare pair is **ideal straight reference vs chosen folded candidate**. | `scene.glb` (candidate) + `scene_reference.glb` (straight master). | as D4 |
| **D6** | Camera is **linked** across both by default, with a `Link cameras` toggle. | one `OrbitControls` drives the shared camera in `Side by side`. | — |
| **D7** | **No colour-by-field in v0.** Area-law error / bend severity / velocity need per-vertex colours in the GLB, i.e. a change to `gltf.py`. | deferred to the next UI layer; listed as `D7-deferred`. | n/a |
| **D8** | The viewer stays **read-only**; no geometry editing. | consistent with the panel design. | — |
| **D9** | The viewer remains a **generated artifact per run**, and gains a thin shell, not a framework. | `write_viewer()` gains two optional args; the shell is a separate generated page. | — |

The existing `Transparent`, `Cutaway`, `Reset view` buttons and the per-part
visibility legend are unchanged.

## 3. Two-tab information architecture

Deliberately two tabs and one shared strip — no app shell, no routing framework,
no state management library.

```
┌──────────────────────────────────────────────────────────────────────────┐
│ STRIP   jbl_1200b_horn_60-200Hz · run_2026…173ee0 · [Awaiting manual BEM]│
│         next: Do the GUI solve → export → Import   · assumptions: 2      │
├───────────────────────────┬──────────────────────────────────────────────┤
│  ● Geometry   ○ Workflow  │   (tab content)                              │
├───────────────────────────┴──────────────────────────────────────────────┤
│ TAB 1  Geometry  = the existing viewer, in an <iframe>, unchanged          │
│ TAB 2  Workflow  = the process UI rendered from workflow_view.json         │
└──────────────────────────────────────────────────────────────────────────┘
```

| element | source | notes |
|---|---|---|
| Project / run id | `workflow_view.json` | read-only |
| Status chip | projection of `stages` + `ManualSolveState` | §8 |
| Next action (strip) | same object as W2 | duplicated so it is visible from both tabs |
| Assumption count | brief leaves with `provenance ∈ {DEFAULT, ESTIMATED}` | clicking jumps to W4 |
| Tab switch | `?tab=geometry\|workflow` (default `geometry`) | deep-linkable, survives reload |

**Hosting decisions**

* Tab 1 is an **`<iframe src="viewer/viewer.html">`** so the existing viewer stays
  the single source of truth for geometry (no duplication, no rewrite).
* Serve the UI over **http on localhost** (the run's `deliverables/` directory).
  Browsers restrict `file://` sub-frames; Forge serves over https so the primary
  target is unaffected. If a `file://` user is blocked, the shell shows
  `Open geometry in a new tab` instead of the iframe.
* No build step, no bundler: the shell is a generated static HTML file using the
  same vendored assets already shipped with the viewer.

## 4. The view-model contract (the key engineering decision)

The UI is a **dumb renderer**. HornFlow emits one file, `workflow_view.json`, from
`state.json` + the brief. Nothing in the browser decides anything: if a button is
disabled, the *reason* is in the JSON.

```jsonc
{
  "view_schema": "1.0",
  "generated_utc": "2026-10-03T17:29:19+00:00",
  "mode": "first_run | running | manual_bem | review | decided | blocked",
  "project": { "name": "…", "author": "…" },
  "issue":   { "key": "HORN-123", "url": null },
  "run":     { "run_id": "…", "input_path": "…", "brief_revision": 3,
               "input_hash": "sha256:…" },                  // null in first_run
  "header":  { "status": "Awaiting manual BEM", "chips": [...],
               "assumptions": 2, "warnings": 0 },
  "next_action": { "id": "act.bem.export", "label": "Import & validate (.vips)",
                   "why": "The GUI solve is done when the .vips files exist.",
                   "owner": "Builder",
                   "cta": { "kind": "copy_command", "value": "python3 -m hornflow.cli …" },
                   "blockers": [] },
  "gates":       [ { "stage": "INPUT_AUDIT", "status": "passed", "detail": "…",
                     "blocked_by": [], "evidence": "…" } ],
  "questions":   [ { "id": "Q-DRV-04", "prompt": "…", "type": "number",
                     "unit": "mm", "enum": null, "wave": "A", "required": true,
                     "status": "UNKNOWN", "why": "…" } ],
  "manual_bem":  { "state": "GUI_REQUIRED", "solver": "AKABAK Free 3.3.2 b144",
                   "solver_version": "3.3-demo", "export_dir": "…",
                   "manifest": "…", "recipe": "…",
                   "checklist": [ { "text": "…", "done": false } ] },
  "import_result": { "state": "BEM_COMPARISON_COMPLETED", "source": "…Mic1.vips",
                     "checks": [ { "name": "…", "passed": true,
                                   "severity": "hard", "detail": "…" } ],
                     "metrics": { "curve": "Mic1", "n_points": 24,
                                  "mean_diff_db": -8.68, "worst_diff_db": 11.64,
                                  "tolerance_db": 6.0, "ok": false },
                     "evidence": "BEM_SIMULATION" },
  "pass_fail":   { "bem": "BEM_REJECTED", "hard_gates": true,
                   "critic": [ { "check": "…", "severity": "warn", "passed": true } ],
                   "exit": "re_export_or_relax_tolerance" },
  "rerun":       { "available": true, "from_stage": null,
                   "keeps": ["brief", "issue links"],
                   "regenerates": ["run_id", "all artifacts"] },
  "artifacts":   [ { "name": "report.md", "path": "…", "sha256": "…",
                     "evidence": "…" } ],
  "viewer":      { "html": "viewer/viewer.html", "title": "…",
                   "features": { "dimensions": true, "compare": true,
                                 "reference_glb": "viewer/scene_reference.glb" } }
}
```

Rules:

* **One emission point**: written at `REPORT_AND_EXPORT`, and re-emitted after a
  `--bem-import` so the Workflow tab reflects the new state without a re-run.
* **Deterministic**: same state → same JSON (sorted keys), so it can be golden-tested.
* **No computed numbers in the UI**: every figure is a pass-through with its
  evidence label.
* The **brief** is separate (`brief.json`): the view model is read-only, the brief
  is the only writable thing.


## 5. Workflow tab layout

Nine sections, always in this order. A section is **visible but collapsed/locked**
rather than hidden, so the user can see the whole process. Each header carries one
chip: `locked` · `ready` · `running` · `passed` · `failed` · `blocked` · `stale`.

| # | section | content | source | locked by |
|---|---|---|---|---|
| **W1** | Run header | project, run id, brief revision, solver + version, evidence bar, warnings count, `↻` refresh | `header`, `run`, `project` | — |
| **W2** | **Next action** | one primary button + `why` + owner + blockers (links) | `next_action` | — |
| **W3** | Gates | the 16 stages as a compact list: status chip, one-line detail, `blocked_by`, duration, evidence label; optional stages show `skipped (optional)` | `gates` | — |
| **W4** | Questions | wave A/B/C; unanswered wave-A rows on top, each with the *why*; completeness meter; "assumptions to confirm" | `questions`, `header.assumptions` | — |
| **W5** | **Manual AKABAK checkpoint** | §10 | `manual_bem` | `FOLD_AWARE_SIMULATION` passed |
| **W6** | **Imported result** | §11 | `import_result` | `VIPS_IMPORTED` |
| **W7** | **Pass / fail** | §12 | `pass_fail`, `gates` | `BEM_COMPARISON_COMPLETED` |
| **W8** | Rerun | §13 | `rerun` | — |
| **W9** | Evidence & artifacts | artifact list with `sha256`, evidence label, download links; critic findings; decision log | `artifacts`, `pass_fail.critic` | `REPORT_AND_EXPORT` |

Right rail (narrow): run list (previous runs for this brief, newest first), each
linking to its own generated UI (runs are immutable, so each keeps its own page).

## 6. The first-run screen

When `mode == "first_run"` (`run` is `null`) the Workflow tab **replaces W3–W9**
with a focused intake screen. Nothing else is shown — an empty gate list beside a
blank question form is noise.

```
┌──────────────────────────────────────────────────────────────────────┐
│ No run yet · brief revision 0                                        │
│ Answer 5 questions to freeze the brief.            [ 0 / 5 answered ]│
├──────────────────────────────────────────────────────────────────────┤
│ Q1  What is this for, and where will it stand?            [required] │
│ Q2  Which driver — and where do its numbers come from?    [required] │
│ Q3  Driver limits: Xmax (+ convention), thermal, amp load [required] │
│ Q4  Band and SPL target                                   [required] │
│ Q5  Envelope and manufacturing method                     [required] │
├──────────────────────────────────────────────────────────────────────┤
│ [ Save draft ]  [ Download brief.yaml ]  [ Copy run command ]        │
│    (Copy run command unlocks at 5/5)                                 │
└──────────────────────────────────────────────────────────────────────┘
```

Behaviour: `Save draft` persists to `localStorage` in the static build and to the
issue property in the Forge build. **Nothing runs from this screen** — the static
build hands out a file and a command; the Forge build sends the brief to the
runner. Wave B and C questions are revealed *after* freeze, inside W4.

## 7. The first five questions

Exactly five, because these are the ones that make architecture selection possible.
Everything else is either revealed later (wave B) or defaulted (wave C).

| # | id | question (prompt text) | inputs | required because |
|---|---|---|---|---|
| 1 | `Q-PRJ-01` | **What is this for, and where will it stand?** | deployment (text), boundary (`free` / `wall` / `corner`), operating orientation, transport orientation | the boundary condition changes mouth loading, path length and the whole feasibility verdict — and it is the single most common reason a design "doesn't work in situ" |
| 2 | `Q-DRV-01/02` | **Which driver — and where do its numbers come from?** | manufacturer, model, `data_source` (`measured` / `datasheet` / `estimated`), then paste or confirm the T/S set | provenance sets the confidence on every downstream number; the T/S set *is* the model |
| 3 | `Q-DRV-04/05 + Q-ELE-02` | **Driver limits: Xmax (and its convention), thermal rating, and the amp's minimum safe impedance.** | `Xmax` + `xmax_convention` (one-way / peak-to-peak), `thermal_power_w`, `min_safe_impedance_ohm` | the only **safety-critical** questions: without them excursion and thermal margins cannot be trusted and the impedance gate cannot be enforced |
| 4 | `Q-TGT-01/02` | **Band and SPL target.** | `f_min_hz`, `f_max_hz`, `spl_continuous_db`, `measurement_distance_m` | sets the required path length and mouth area, i.e. whether the box is even physically plausible |
| 5 | `Q-PHY-01/02 + Q-MFG-01` | **Envelope and manufacturing method.** | `max_width_mm`, `max_height_mm`, `max_depth_mm` (or `max_external_volume_m3`), `max_mass_kg`, `method` (`print` / `plywood` / `either`) | the hard size gate, the hard mass gate, and the branch that selects the manufacturing transformer |

Freezing requires all five. `Q2` without a T/S set is *allowed to save as a draft*
but blocks freeze, because the pipeline cannot run on an incomplete driver.


## 8. Gate and transition rules

### 8.1 The process gates (existing 16 stages — unchanged)

The UI renders `gates[]` verbatim; it does not re-implement `workflow/stages.py`.

| stage | passes when | blocks |
|---|---|---|
| `INPUT_AUDIT` | all wave-A answers present, units valid, brief frozen | everything |
| `LIMIT_IMPACT_ANALYSIS` | a `LimitImpact` exists per user limit (`QUALITATIVE` is acceptable) | `ARCHITECTURE_SCREENING` |
| `PHYSICAL_FEASIBILITY` | wavelengths/quarter-wave/mouth/compression computed; impossible combos explicitly rejected | `ARCHITECTURE_SCREENING` |
| `ARCHITECTURE_SCREENING` | ≥1 feasible architecture scored; `SCREENING_ONLY` labelled | `IDEAL_ACOUSTIC_OPTIMIZATION` |
| `IDEAL_ACOUSTIC_OPTIMIZATION` | an `AcousticMaster` with a first-class `S_target(s)` exists | fold work |
| `FOLD_TOPOLOGY_GENERATION` | ≥1 fold candidate per viable master | fold validation |
| `FOLD_GEOMETRY_VALIDATION` | area-law RMS within tolerance; length preserved; no self-intersection | `FOLD_AWARE_SIMULATION`, structural, manufacturing |
| `ONE_DIMENSIONAL_SIMULATION` | a `SimulationRun` with the full column set | fold-aware, sensitivity |
| `FOLD_AWARE_SIMULATION` | reference vs folded compared | W5 unlocks |
| `THREE_DIMENSIONAL_VERIFICATION` | **optional** — `skipped` by design (GUI solver); W5 takes over | nothing |
| `STRUCTURAL_SCREENING` | first-order screen reported as `STRUCTURAL_SCREENING` | manufacturing |
| `MANUFACTURING_TRANSFORMATION` | a variant is watertight / faceted valid, or the conflict is reported | critique |
| `CONSTRAINT_SENSITIVITY` | stricter + relaxed case per active limit | critique |
| `INDEPENDENT_CRITIQUE` | critic ran; findings attached | final comparison |
| `FINAL_COMPARISON` | best folded **and** best overall reported | report |
| `REPORT_AND_EXPORT` | report + artifacts + view model written | — |

A stage that cannot pass returns a **typed failure** (`domain/failures.py`):
`category`, `failed_checks`, `affected_candidates`, `recoverable`,
`recommended_upstream_revision`, `evidence`. W3 renders it and W2 turns
`recommended_upstream_revision` into the primary action. Engineering
infeasibility is never an exception.

### 8.2 The BEM sub-machine (the eight states, exactly as implemented)

```
INPUTS_GENERATED ─▶ GUI_REQUIRED ─▶ MANUAL_SOLVE_PENDING ─▶ MANUAL_SOLVE_COMPLETED
                                                                    │
                          ┌─────────────────────────────────────────┘
                          ▼
                    VIPS_IMPORTED ─▶ BEM_COMPARISON_COMPLETED ─┬─▶ BEM_VALIDATED
                                                               └─▶ BEM_REJECTED
     BEM_VALIDATED / BEM_REJECTED ──(re-import)──▶ VIPS_IMPORTED
```

| from | to | trigger (exactly) | UI effect |
|---|---|---|---|
| `INPUTS_GENERATED` | `GUI_REQUIRED` | `THREE_DIMENSIONAL_VERIFICATION` ran: mesh + LE script + manifest + checklist written | W5 opens; W2 = *Copy AKABAK checklist* + *Open export folder* |
| `GUI_REQUIRED` | `MANUAL_SOLVE_PENDING` | user reports the GUI work has started (`I exported the files` is **not** accepted here) | checklist ticks become live |
| `MANUAL_SOLVE_PENDING` | `MANUAL_SOLVE_COMPLETED` | user asserts the `.vips` export exists | W2 = *Import & validate (.vips)* enabled |
| `MANUAL_SOLVE_COMPLETED` | `VIPS_IMPORTED` | import ran **and all hard validation checks passed** (files exist, non-empty, belong to the run, valid grid, pressure spectrum present, finite, newer than inputs, manifest match) | W6 opens with the 8-check table |
| `VIPS_IMPORTED` | `BEM_COMPARISON_COMPLETED` | the on-axis curve was compared with the 1-D reference | W6 shows mean/worst Δ and tolerance |
| `BEM_COMPARISON_COMPLETED` | `BEM_VALIDATED` | `worst |Δ| ≤ bem_tolerance_db` | W7 green |
| `BEM_COMPARISON_COMPLETED` | `BEM_REJECTED` | `worst |Δ| > tolerance` | W7 amber + two exits |
| decided state | `VIPS_IMPORTED` | a **new** import of a **new** export (the old decision stays in `decision_log`) | W6 re-opens |

**Hard rule carried into the UI:** a candidate is never shown as `BEM_VALIDATED`
unless both the import **and** the comparison happened. A hard validation failure
does not advance at all — the state stays `MANUAL_SOLVE_PENDING` and W6 lists
exactly which check failed.

**One implementation detail worth stating**, because it changes what the UI must
ask for: in the pipeline, `--bem-import` walks the legal chain itself
(`workflow/bem_import.py::_walk_to`) — `GUI_REQUIRED → MANUAL_SOLVE_PENDING →
MANUAL_SOLVE_COMPLETED → VIPS_IMPORTED → BEM_COMPARISON_COMPLETED → …`. So the
middle two states are *bookkeeping* that the import traverses, not gates the user
must satisfy separately. The UI's `I exported the files` click is a **convenience**
that enables `Import & validate (.vips)` early; it never sets state on its own. The
only two transitions a real import cannot skip are the last two.

### 8.3 What gates each button

A button is **disabled with a visible reason** (from `next_action.blockers`) when
its precondition is not met — never hidden, so the process stays legible.

| precondition | unlocks |
|---|---|
| all 5 answers saved | `Download brief.yaml`, `Copy run command` (now) / `Start run` (Forge) |
| a run exists | W3–W9, tab badge, `Download report.md` |
| `FOLD_AWARE_SIMULATION` passed | `Copy AKABAK checklist`, `Open export folder` |
| `manual_bem.state ∈ {GUI_REQUIRED…MANUAL_SOLVE_COMPLETED}` | `I exported the files` |
| `manual_bem.state == MANUAL_SOLVE_COMPLETED` | `Import & validate (.vips)` |
| import passed | W6, `Accept as unvalidated`, `Re-export and retry` |
| `pass_fail.bem == BEM_REJECTED` | `Re-export and retry`, `Accept as unvalidated` |
| `pass_fail.hard_gates == true` and critic has no `reject` | `Mark decided` |
| decision recorded | `Download artifacts`, `Re-run (new revision)` |
| a typed failure names a stage | `Re-run from <STAGE>` |


## 9. Action buttons — exact labels

**Now** = works in the zero-dependency static build. **Forge** = needs a resolver.
One primary button per screen; the rest are secondary and appear in the section
they belong to.

### Geometry tab (existing viewer, additive)

| label | kind | enabled when | effect |
|---|---|---|---|
| `Transparent` | toggle | always | existing |
| `Cutaway` | toggle | always | existing |
| `Reset view` | action | always | existing |
| **`Dimensions`** | toggle | `viewer.features.dimensions` | show/hide the annotation overlay (D1) |
| **`mm` / `m`** | toggle | `Dimensions` is on | switch overlay units (D3) |
| **`Candidate`** | view | always | show the chosen folded candidate (D4) |
| **`Reference`** | view | `viewer.features.compare` | show the straight ideal reference (D5) |
| **`Side by side`** | view | `viewer.features.compare` | both, offset along X (D4/D5) |
| **`Link cameras`** | toggle | `Side by side` active | pan/zoom both together (D6) |

### Workflow tab

| label | where | kind | Now/Forge |
|---|---|---|---|
| `Save draft` | W4 / first-run | action | Now (`localStorage`) / Forge (issue property) |
| `Download brief.yaml` | first-run, W4 | action | Now |
| `Copy run command` | first-run, W2 | action | Now |
| `Start run` | W2 | action | Forge |
| `Open geometry tab` | strip, W1 | action | Now |
| `Refresh` | W1 | action | Now (re-fetch `workflow_view.json`) |
| `Download report.md` | W9 | action | Now |
| `Copy AKABAK checklist` | W5 | action | Now |
| `Open export folder` | W5 | action (`copy_path`) | Now |
| `I exported the files` | W5 | action | Now (sets the flag) / Forge |
| `Import & validate (.vips)` | W5 / W6 | **primary** | Forge |
| `Copy import command` | W5 | action | Now |
| `Re-export and retry` | W7 | action | Now (reopens W5) |
| `Accept as unvalidated` | W7 | action + **required reason** | Forge (records a decision) |
| `Re-run from <STAGE>` | W8 | action | Forge |
| `Re-run (new revision)` | W8 | action | Now (copy command) / Forge |
| `Download artifacts` | W9 | action | Now |
| `Mark decided` | W2 | action | Forge (Jira transition) |

Two label rules: verbs first (`Import & validate (.vips)`, not `.vips import`), and
anything that consumes a file names the file type in the label, because it is the
step people forget.

## 10. Manual AKABAK checklist block (W5)

Opens when `manual_bem` exists; renders `manual_bem.state` as a four-step tracker:

```
GUI_REQUIRED ──▶ MANUAL_SOLVE_PENDING ──▶ MANUAL_SOLVE_COMPLETED ──▶ VIPS_IMPORTED
```

Content:

* **Why this is manual** — one line, verbatim from HornFlow: *"AKABAK Free 3.3.2
  b144 runs under Wine through its GUI; there is no usable head-less/CLI solve
  path, and the Free build does not write the solved BEM state (`.akpbe`) — it
  stays in RAM."* This is why the block exists; it must not be paraphrased into
  "automation pending".
* **Solver + version** — `AKABAK Free 3.3.2 b144` (`3.3-demo`).
* **Exact paths** — inputs dir, **export dir** (highlighted), manifest.
* **The checklist** — the run-specific items from `akabak_recipe.md`, as tick boxes
  (`Start AKABAK` → `open/build the project` → `verify the BEM tree` → `verify the
  LEM network` → `set the drive level` → `solve` → `export the spectra` →
  `confirm the folder is non-empty` → `send it back`). Ticks are **UI-local**; they
  are a memory aid, never state.
* **Buttons** — `Copy AKABAK checklist`, `Open export folder`,
  `I exported the files` (enabled only once `MANUAL_SOLVE_PENDING`),
  `Copy import command` (now) / `Import & validate (.vips)` (forge).
* **Troubleshooting** — collapsed `<details>`, the same six rows as the recipe.

The block is **read-only against state**: ticking a box does not change
`ManualSolveState`. Only an import does.

## 11. Imported-result block (W6)

Shown from `VIPS_IMPORTED` onwards. Two halves:

1. **Validation table** — one row per check with `pass`/`FAIL`, `hard`/`soft`
   severity, and the verbatim detail (e.g. *"21 importable file(s) under …"*).
   A hard failure is what keeps the state at `MANUAL_SOLVE_PENDING`.
2. **Comparison** — the curve used (`Mic1`), the overlapping band and point count,
   **mean Δ**, **worst |Δ|**, the tolerance, and the evidence label
   (`BEM_SIMULATION`). Plus the standing note that the +3.01 dB peak convention
   has already been removed, so the numbers are rms-referenced and directly
   comparable with the 1-D model.
3. **Soft warnings** — provenance items (`belongs_to_run` met only by timestamp,
   `run_manifest_matches` absent) shown as amber, explicitly *not* failures.

Nothing here is edited by the user. `Accept as unvalidated` lives in W7, not here,
because it is a decision about the result, not part of it.

## 12. Pass / fail block (W7)

A single verdict line, then the reasons:

| state | banner | what is shown | the two exits |
|---|---|---|---|
| `BEM_VALIDATED` | green · **"Validated against the 1-D reference"** | worst Δ vs tolerance, curve, evidence | `Mark decided` · `Re-run (new revision)` |
| `BEM_REJECTED` | amber · **"Compared, but outside tolerance"** | the measured Δ (e.g. mean −8.68 dB, worst 11.64 dB, tolerance 6 dB) **and the likely cause** (here: the documented free-standing 4π vs baffled 2π mounting offset) | `Re-export and retry` · `Accept as unvalidated` (with reason) |
| hard gate failed | red · **"Hard limit violated"** | which `FIXED` limit, by how much, and the smallest relaxation that clears it | `Re-run (new revision)` with the limit changed |
| critic `reject` | red · **"Recommendation rejected by the critic"** | the finding, the affected candidates, the stage to return to | `Re-run from <STAGE>` |

`Accept as unvalidated` records a **decision with a mandatory reason** — it is the
only way an amber result proceeds, and it is visible in `decision_log` forever.


## 13. Rerun flow

Two distinct reruns, never conflated:

| | `Re-run from <STAGE>` | `Re-run (new revision)` |
|---|---|---|
| available when | a **typed failure** names `recommended_upstream_revision` | always (after the first run) |
| what it changes | nothing upstream of that stage | the brief |
| what it reuses | cached stages/artifacts before that stage | nothing |
| what it produces | a new run id, linked to the same brief revision | a new **brief revision** + new run |
| why separate | the engineering answer is wrong downstream of a known-good input | the *question* changed |

Flow:

1. Pressing a rerun button **never overwrites** anything. HornFlow mints a new
   `run_id`; the old run directory stays and remains addressable from the run list.
2. `Re-run (new revision)` first requires an edit in W4, then re-freezes the brief:
   `revision+1`, a new `input_hash`. Everything the user cannot see (fold
   candidates, meshes, spectra) is regenerated; the brief and the issue links are
   preserved; the decision record is preserved but marked `superseded`.
3. Stages before `from_stage` are served from the cache **keyed by the hash of
   normalized inputs + geometry + grid + solver settings** — so a rerun that only
   changes the BEM tolerance reuses every 1-D result and re-runs nothing but the
   comparison.
4. After a rerun the UI reloads the newest `workflow_view.json` and shows a
   `stale` chip on any section whose run id differs from the header's.

## 14. Edit / read-only / computed / Jira / HornFlow-only

| thing | user can edit | read-only in UI | computed by HornFlow | stored in Jira | only in HornFlow |
|---|---|---|---|---|---|
| the 5 answers + wave B/C | **yes** (until freeze; after freeze only via a new revision) | — | validation + SI normalization | yes (`hornflow.brief`) | the brief's schema + migrations |
| `workflow_view.json` | no | **yes** | **yes** | no (projection only) | yes |
| gate statuses | no | yes | yes | mirrored as one status | **authoritative** |
| `ManualSolveState` | no (ticks are UI-local) | yes | yes | mirrored (`hornflow.manual_state`) | **authoritative** |
| validation checks + comparison | no | yes | yes | no | yes |
| `BEM_VALIDATED` / `BEM_REJECTED` | no | yes | yes | shown, never set | **authoritative** |
| every SPL / impedance / excursion / mass | no | yes | yes | no | yes |
| geometry, meshes, GLB, STL, spectra | **no** (D8) | yes (3D) | yes | links + `sha256` only | yes |
| decision + reason | **yes** (human) | shown | copied by reference | **authoritative** | reference in `decision_log` |
| priority, assignee, links, notifications | **yes** (human) | — | no | **authoritative** | no |
| run list, artifact hashes, caches | no | part | yes | no | yes |

The one-line rule: **if HornFlow computed it, the UI only displays it; if a human
decided it, HornFlow only cites it.**


## 15. Minimal Forge Custom UI implementation plan

Constraint to be honest about first: **Forge resolvers cannot run a shell or touch
a filesystem.** They are sandboxed Node. So the pipeline must run *somewhere*, and
the MVP plan puts it behind a tiny HTTP runner.

```
Jira issue
  └─ Custom UI (static bundle: the two tabs)
       ├─ viewer/…            (unchanged viewer + vendor + GLBs + annotations)
       └─ workflow/…          (renders workflow_view.json)
             │  @forge/bridge → invoke('getView' | 'startRun' | 'importVips')
             ▼
       Forge resolvers (sandboxed)
             │  @forge/api requestJira()      → issue properties
             │  invokeRemote()                → the HornFlow runner
             ▼
       HornFlow runner (our host; wraps the CLI)
             └─ python3 -m hornflow.cli …  → runs/<run_id>/deliverables/…
```

| piece | detail |
|---|---|
| `manifest.yml` | `jira:issuePanel` (or `jira:issueContext`) module → the Custom UI resource; scopes `read:jira-work`, `write:jira-work` |
| Custom UI resources | `static/` holds the two-tab bundle **plus** the viewer and its vendored three.js — served by Forge over https, so the `file://` iframe concern disappears |
| resolvers | `getView({issueKey})` → read the issue property + `hornflow.latest_run_id`, fetch `workflow_view.json` from the runner, return it; `startRun({issueKey, brief})` → validate, write the property, POST to the runner; `importVips({issueKey, runId})` → POST to the runner, return the import result |
| storage decision | **issue properties, not custom fields** — `PUT /rest/api/3/issue/{key}/properties/hornflow.brief`. No admin, no custom-field quotas, per-issue JSON, and it matches decision **J1** (one versioned JSON blob). Custom fields stay optional *mirrors* for board filters (**J8**); if unavailable, fall back to a label |
| geometry tab | `<iframe src="viewer/viewer.html">` from the same static origin. Verify the app CSP allows `frame-src 'self'`; if not, the fallback is to import the viewer's script into the bundle (~60 lines) and mount it into a div |
| auth | resolvers act as the invoking user; the runner authenticates with a shared secret from Forge environment variables. Never bake the secret into the frontend |
| what Forge must **not** do | compute anything, transition to `Decided`, edit human comments, or store a computed number as truth |
| migration from the static build | the view model and the brief JSON are already the contract; `Download brief.yaml` / `Copy run command` become `Start run`. No UI rewrite — only the transport swaps from "download a file" to "POST to a resolver" |

## 16. Shortest path to a first runnable version

Five milestones; M1–M4 need **no Forge, no new dependency**, and M4 is the goal
("one real run executed once").

| # | milestone | deliverable | done when |
|---|---|---|---|
| **M1** | **View-model emitter** | `hornflow/reporting/ui_view.py` → `workflow_view.json` (+ `brief.json`); deterministic, sorted keys | a golden test diffs two emissions of the same state; `first_run` mode emits the 5 questions with `run: null` |
| **M2** | **Viewer features (D1–D6)** | `write_viewer()` gains `annotations=` and `reference_candidate=`; the template gains `Dimensions`, the unit toggle and the view selector, all feature-detected | runs that pass neither arg render exactly as today; a test asserts the annotation block and the second GLB appear only when passed |
| **M3** | **Two-tab shell** | `hornflow/reporting/ui_shell.py` → `deliverables/ui/index.html`: strip + tab switch + iframe + a plain-DOM renderer for `workflow_view.json` | opening it over localhost shows both tabs; `?tab=workflow` deep-links; the first-run screen renders from a null run |
| **M4** | **Wire it up + one real run** | `REPORT_AND_EXPORT` also writes `ui/`; `--bem-import` re-emits the view model; run the JBL example once and open the page | `python3 -m hornflow.cli params/horn_jbl_1200b.yaml --out runs`, then open `runs/<id>/deliverables/ui/index.html` — **one real run executed once**, the manual BEM step visible, the result imported and shown |
| **M5** | **Forge app (optional)** | `manifest.yml` + resolvers + the runner endpoint (§15) | the same page renders inside a Jira issue panel |

Order matters: M1 first, because it is the contract and is testable with no UI at
all. M3 is then ~200 lines of DOM code against a frozen schema.

## 17. Risks and open decisions

| risk | mitigation |
|---|---|
| the iframe is blocked by CSP in Forge | verify `frame-src 'self'` early; fallback = inline the viewer script (~60 lines) |
| `file://` users cannot see the iframe | the shell detects it and offers `Open geometry in a new tab`; recommend localhost http |
| the view model drifts from `state.json` | it is *derived* and golden-tested; the UI never reads `state.json` directly |
| the manual step gets "automated" by accident | W5 states the reason verbatim; no button can set `VIPS_IMPORTED` without a real import |
| Forge cannot run the pipeline | accepted and explicit: the runner is a separate service (§15); Forge is the *panel*, not the *engine* |
| two GLBs double the page weight | ~28 KB each here; gate the second one behind `viewer.features.compare` |

Open: (1) should the dimension overlay default to `mm` (proposed) or `m`?
(2) does the strip's next action need to be visible on the geometry tab, or is the
tab badge enough? (3) for `Accept as unvalidated`, is a free-text reason enough, or
must the user pick from a fixed list?

