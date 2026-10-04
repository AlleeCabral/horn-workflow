# Local multi-tab app — Viewer + Workflow (+ Results)

> **Current direction.** HornFlow's UI is **local-first and run-centred**: the
> existing viewer becomes the app shell, and a Workflow tab is added beside it.
> **No Jira, no Forge.** `docs/jira-issue-flow.md` and `docs/ui-two-tab-mvp.md` are
> kept for the field/schema work that carries over, but their hosting decisions are
> superseded by this document.

## 0. The one rule

**HornFlow stays authoritative; the UI is a renderer.**

The app never computes a number, never decides a gate, and never invents state. It
renders a view model that HornFlow emits from `state.json`, and the only things it
writes back are (a) the *brief* — the answers to the questions — and (b) commands
that call the same functions the CLI calls. `state.json` remains the single source
of truth.

## 1. Product brief

> **HornFlow App v0** is the existing offline viewer plus a tab strip. **Viewer**
> is unchanged: the folded geometry in 3D. **Workflow** shows where the run is, the
> gates, what is still missing from the user, the single next action, the manual
> AKABAK checkpoint, the `.vips` import, and the validation outcome. **Results** is
> a placeholder for the numbers.
>
> It runs with **zero new dependencies**: a static page that works from `file://`,
> plus an optional `python3 -m hornflow.app` local server that enables the buttons
> which actually mutate state.

Goals: (1) one real run executed end to end from the UI; (2) the manual BEM step
made obvious and hard to skip; (3) no new dependencies and no build step; (4) the
viewer's existing behaviour byte-for-byte preserved.

Non-goals: geometry editing, solver parameter editing, multi-run dashboards, user
accounts, remote hosting.

## 2. Tab architecture

Three tabs, one shared strip, one HTML file. No framework, no bundler, no router.

```
┌────────────────────────────────────────────────────────────────────────────┐
│ STRIP   jbl_1200b_horn_60-200Hz · run_…173ee0 · [Awaiting manual BEM] · ⟳  │
│         next: Import & validate (.vips)          assumptions: 2   ● ◐ ○     │
├───────────────┬───────────────┬────────────────────────────────────────────┤
│   Viewer      │   Workflow    │   Results                                  │
├───────────────┴───────────────┴────────────────────────────────────────────┤
│ <section id="pane-viewer">   the existing viewer, unchanged                │
│ <section id="pane-workflow"> W1…W8, rendered from app_view.json            │
│ <section id="pane-results">  placeholder (see §18)                         │
└────────────────────────────────────────────────────────────────────────────┘
```

**The shell *is* `viewer.html`.** `hornflow/viz/viewer/index.html` gains exactly
four things, and the geometry code is not touched:

| added | detail |
|---|---|
| `<nav id="tabs">` | three buttons; `data-pane` attributes |
| `<section id="pane-viewer">` | **wraps the existing `<div id="wrap">` verbatim** |
| `<section id="pane-workflow">`, `<section id="pane-results">` | empty, filled by JS |
| `<script id="app_view" type="application/json">__APP_VIEW__</script>` + `ui/app.js`, `ui/app.css` | the view model, embedded exactly like the GLB already is |

Everything else — the three `vendor/` scripts, the base64 GLB block, and the
viewer's own `<script>` (lines 43–104 today) — stays **byte-identical**. The
viewer still initialises on load, so the geometry tab behaves exactly as it does
now.

**Backward compatibility.** `__APP_VIEW__` empty ⇒ `app.js` hides the Workflow and
Results tabs and shows only the Viewer: every run generated before this change
keeps working, and `write_viewer()` called without the new argument reproduces
today's page.

**Two hosts, one page, graceful degradation**

| host | how it runs | what works |
|---|---|---|
| **Static** (default) | open `viewer.html` from disk or any static server | everything read-only; mutating buttons become `Copy command` or are disabled with a reason |
| **Local** (`python3 -m hornflow.app --run-dir runs/<id>`) | stdlib `http.server` on `127.0.0.1`, serving the run folder **plus** `/api/*` | all buttons live: freeze brief, run, import, rerun |

`app.js` tries `GET /api/view` on load. If it fails it falls back to the embedded
snapshot — the same "detect and degrade, never fabricate" pattern as the AKABAK
`pending_external` contract.

## 3. What the app loads from local run files

All paths are relative to `runs/<run_id>/`. Nothing is fetched from the network.

| source | read for |
|---|---|
| `state.json` | **everything authoritative**: `run`, `project`, `requirements`, `driver`, `constraints`, `limit_impacts`, `feasibility`, `architecture_candidates`, `fold_candidates`, `simulation_runs`, `sensitivity_runs`, `manufacturing_variants`, `validation`, `critic_findings`, `decision_log`, `final_recommendations`, `stages` |
| `logs.jsonl` | per-stage duration, cache status, severity, artifact locations (W3 rows) |
| `deliverables/bem/bem_manifest.json` | run id, generated time, expected export globs, the export dir, input `sha256`s (W5/W6) |
| `deliverables/bem/akabak_recipe.md` | the human checklist text mirrored into W5 |
| `deliverables/bem/export/*.vips` | **presence only** (count + newest mtime) — content is parsed by HornFlow, not the browser |
| `deliverables/bem/bem_manual_report.md` | the validation/comparison table text (W6/W7) |
| `stages/<STAGE>/…`, `deliverables/report.md`, `deliverables/printed.stl`, `deliverables/viewer/scene.glb` | links only (W8, Viewer tab) |
| `params/*.yaml`, `params/drivers/*.yaml` | the seed for the brief when there is no run yet |

The app reads **`app_view.json`**, never `state.json` directly. That is deliberate:
one translation point, golden-testable, and the UI can never drift into
re-interpreting state.

### 3.1 `app_view.json` (schema `1.0`)

Emitted by `hornflow/app/view.py` from `state.json` (+ the brief). Sorted keys, so
the same state always produces byte-identical JSON.

```jsonc
{
  "view_schema": "1.0",
  "generated_utc": "…",
  "host": "static | local",                     // which host produced this file
  "mode": "first_run | running | manual_bem | review | decided | blocked",
  "project": { "name": "…", "author": "…" },
  "run":  { "run_id": "…", "input_path": "…", "brief_revision": 3,
            "input_hash": "sha256:…", "runs_available": ["run_…"] },   // null in first_run
  "current_state": {                            // W1
    "brief_revision": 3, "stages_total": 16, "stages_passed": 16,
    "bem_state": "GUI_REQUIRED", "bem_status": "pending_external",
    "solver": "akabak-bem", "solver_version": "3.3-demo",
    "solver_label": "AKABAK Free 3.3.2 b144",
    "evidence_bar": "MINIMUM", "assumptions": 2, "warnings": 0
  },
  "next_action": { "id": "act.bem.import", "label": "Import & validate (.vips)",
                   "why": "…", "owner": "Builder", "blockers": [],
                   "cta": { "kind": "api|copy_command|open_url|none", "value": "…" } },
  "gates": [ { "stage": "INPUT_AUDIT", "status": "passed", "optional": false,
               "detail": "…", "blocked_by": [], "duration_s": 0.03,
               "cache": "miss", "artifacts": ["…"] } ],
  "questions": [ { "id": "Q-DRV-04", "prompt": "…", "wave": "A", "required": true,
                   "type": "number", "unit": "mm", "enum": null,
                   "status": "UNKNOWN", "provenance": null, "confidence": null,
                   "value": null, "why": "…", "blocking": true } ],
  "manual_bem": {                               // W5
    "state": "GUI_REQUIRED", "reason": "…verbatim…",
    "export_dir": "…", "manifest": "…", "recipe": "…",
    "checklist": [ { "text": "…", "key": "start" } ],
    "exported_files": 0, "newest_export_utc": null
  },
  "import_panel": {                             // W6
    "available": false, "last_source": null, "last_utc": null,
    "command": "python3 -m hornflow.cli params/… --bem-import …/export"
  },
  "outcome": {                                  // W7
    "bem": "GUI_REQUIRED", "hard_gates": true,
    "checks": [ { "name": "…", "passed": true, "severity": "hard", "detail": "…" } ],
    "metrics": { "curve": "Mic1", "n_points": 24, "mean_diff_db": -8.68,
                 "worst_diff_db": 11.64, "tolerance_db": 6.0, "ok": false },
    "evidence": "BEM_SIMULATION",
    "critic": [ { "check": "…", "severity": "warn", "passed": true } ],
    "exit": "re_export_or_relax_tolerance"
  },
  "rerun": { "from_stage": null, "reason": null,
             "keeps": ["brief", "decision record"],
             "regenerates": ["run_id", "all artifacts"] },
  "artifacts": [ { "name": "report.md", "path": "deliverables/report.md",
                   "sha256": "…", "evidence": "…" } ],
  "viewer": { "title": "…", "features": { "dimensions": true, "compare": true,
                                          "reference_glb": "viewer/scene_reference.glb" } }
}
```


## 4. Workflow tab — wireframe in words

One column, eight bands, top to bottom. Every band is **visible**; a band whose
precondition is unmet renders collapsed with a `locked` chip **and the reason**,
never hidden. The band header shows: title · one chip
(`locked|ready|running|passed|failed|blocked|stale`) · `▾`.

```
W1 CURRENT STATE      brief rev 3 · hash sha256:… · 16/16 stages
                      BEM GUI_REQUIRED · solver AKABAK Free 3.3.2 b144
                      evidence MINIMUM · 2 assumptions · 0 warnings
W2 NEXT ACTION        [ Import & validate (.vips) ]
                      why: the .vips export is the last manual step
                      owner: Builder · blockers: none
W3 GATES              ✓ INPUT_AUDIT  ✓ LIMIT_IMPACT_ANALYSIS
                      ✓ PHYSICAL_FEASIBILITY  ✓ ARCHITECTURE_SCREENING
                      ✓ IDEAL_ACOUSTIC_OPTIMIZATION  ✓ FOLD_TOPOLOGY_GENERATION
                      ✓ FOLD_GEOMETRY_VALIDATION  ✓ ONE_DIMENSIONAL_SIMULATION
                      ✓ FOLD_AWARE_SIMULATION
                      – THREE_DIMENSIONAL_VERIFICATION (optional: manual GUI → W5)
                      ✓ STRUCTURAL_SCREENING  ✓ MANUFACTURING_TRANSFORMATION
                      ✓ CONSTRAINT_SENSITIVITY  ✓ INDEPENDENT_CRITIQUE
                      ✓ FINAL_COMPARISON  ✓ REPORT_AND_EXPORT
W4 BLOCKING QUESTIONS 5 wave-A rows: prompt · value · status chip · provenance
                      wave B: 3/9 answered · wave C: 2 defaults to confirm
                      [ Save draft ]  [ Freeze brief ]
W5 MANUAL AKABAK      (opens at GUI_REQUIRED)
   CHECKPOINT         GUI_REQUIRED → MANUAL_SOLVE_PENDING → MANUAL_SOLVE_COMPLETED
                      → [VIPS_IMPORTED comes from the import, not from here]
                      why manual (verbatim) · solver · exact paths
                      ☐ start AKABAK  ☐ build the project  ☐ verify BEM tree
                      ☐ verify LEM network  ☐ set drive level  ☐ solve
                      ☐ export .vips  ☐ confirm folder non-empty  ☐ send it back
                      [ Copy AKABAK checklist ] [ Open export folder ]
                      [ I exported the files ]
W6 .VIPS IMPORT       (opens at MANUAL_SOLVE_PENDING)
                      export dir (highlighted) · expects *.vips · found 0
                      [ Import & validate (.vips) ]  [ Copy import command ]
W7 VALIDATION         (opens at BEM_COMPARISON_COMPLETED)
   OUTCOME            checks: 6/6 hard pass, 2 soft warnings
                      comparison: Mic1 · 24 pts · mean −8.68 dB
                                  worst |Δ| 11.64 dB · tolerance 6.0 dB
                      ◆ BEM_REJECTED — measured, not fatal; exits below
                      [ Re-export and retry ]  [ Accept as unvalidated ]
W8 RERUN              [ Re-run from <STAGE> ]  [ Re-run (new revision) ]
                      keeps: brief, decision record
                      regenerates: run id, all artifacts
```

## 5. W1 — current-state block

Rendered from `current_state` + `run`. Read-only, one line each:

| line | content | empty / pre-run |
|---|---|---|
| identity | `project.name` · `run.run_id` (short) · `input_path` | "No run yet — brief revision 0" |
| progress | `stages_passed / stages_total` stages · `count(stages with status failed)` failed | "—" |
| BEM | `bem_state` chip + `bem_status` (`pending_external` ≠ failure) | "not started" |
| solver | `solver_label` (`3.3-demo`) | "—" |
| evidence | `evidence_bar` (`MINIMUM`/`HIGH`) | from the brief |
| assumptions | count of brief leaves with `provenance ∈ {DEFAULT, ESTIMATED}`; clicking jumps to W4 | "—" |
| staleness | `stale` chip when `app_view.json` was emitted from a different run than the header | — |

## 6. W4 — blocking-questions block

Three sub-lists, in this order:

1. **Wave A (required).** The five questions in §8. Each row: prompt, input
   widget, unit, `status` chip (`FIXED|PREFERRED|RANGE|OPTIMIZABLE|UNKNOWN`),
   `provenance` chip, and a one-line *why it matters*. Unanswered rows float to the
   top with a `blocking` chip.
2. **Wave B (asked).** The nine questions that change architecture (path budget,
   rear rejection, coverage, mouth limits, bend radius, fold count, service access,
   weather, must-beat-alternative). Only asked once the brief is frozen.
3. **Wave C (defaulted).** Shown as *"2 defaults to confirm"* — collapsed rows the
   user can accept with one click.

A completeness meter (`5/5 required`) sits in the header, and
`Save draft` / `Freeze brief` at the foot. **Freeze is the line between draft and
run**: it writes the brief, computes `input_hash`, and unlocks `Start run`.


## 7. Editable vs read-only

| field / block | editable | notes |
|---|---|---|
| the five wave-A answers | **yes**, until freeze | after freeze, editing requires `Re-run (new revision)` |
| wave B / C answers | **yes**, until freeze | wave B is asked after freeze; a later change is a new revision |
| `bem_tolerance_db` | **yes** | a run parameter, not a limit; changing it is a *new revision* but a cheap rerun (cache reuse) |
| checklist ticks in W5 | **yes, UI-local only** | a memory aid; they never touch `ManualSolveState` |
| the "I exported the files" flag | **yes, UI-local** | convenience only; the import is what advances state |
| decision reason (`Accept as unvalidated`) | **yes**, mandatory free text | appended to `decision_log` |
| tab, camera, `Dimensions`/`Cutaway`/`Transparent` state, overlay unit | **yes, UI-local** | `localStorage`, never state |
| everything else in W1/W3/W6/W7 | **no** | rendered from `app_view.json` |

Rule: **the app may edit the brief and its own view preferences — nothing else.**
Even the decision reason is written *through* HornFlow (so it lands in
`decision_log` with a timestamp and an author), not by the browser touching files.

## 8. The first five required user questions

Exactly five, because these are what make architecture selection possible. Order
is deliberate: context → driver → safety → target → envelope.

| # | id | prompt | inputs | why it is required |
|---|---|---|---|---|
| 1 | `Q-PRJ-01` | **What is this for, and where will it stand?** | deployment, boundary (`free`/`wall`/`corner`), operating + transport orientation | the boundary condition changes mouth loading and the whole path-length budget; it is the most common reason a design "works" but not *in situ* |
| 2 | `Q-DRV-01/02` | **Which driver — and where do its numbers come from?** | manufacturer, model, `data_source` (`measured`/`datasheet`/`estimated`), then paste or confirm the T/S set | provenance sets the confidence on every downstream number; the T/S set *is* the model |
| 3 | `Q-DRV-04/05`+`Q-ELE-02` | **Driver limits — Xmax (and its convention), thermal rating, amp's minimum safe impedance** | `Xmax` + `xmax_convention` (`one-way`/`peak-to-peak`), `thermal_power_w`, `min_safe_impedance_ohm` | the only **safety-critical** questions: without them excursion/thermal margins are untrustworthy and the impedance gate cannot be enforced |
| 4 | `Q-TGT-01/02` | **Band and SPL target** | `f_min_hz`, `f_max_hz`, `spl_continuous_db`, `measurement_distance_m` | sets the required path length and mouth area — i.e. whether the box is physically plausible at all |
| 5 | `Q-PHY-01/02`+`Q-MFG-01` | **Envelope and manufacturing method** | `max_width_mm`, `max_height_mm`, `max_depth_mm` (or `max_external_volume_m3`), `max_mass_kg`, `method` (`print`/`plywood`/`either`) | the hard size gate, the hard mass gate, and the branch that selects the manufacturing transformer |

**Storage decision.** The brief is written as a YAML **definition file** that the
*existing* `config.load()` already understands (extra keys live in an ignored
`brief:` block), and `Freeze` derives a plain `params/generated/<slug>.yaml` from
it. This means `config.py` and the pipeline stay **completely unchanged**, and the
brief's per-value `status`/`provenance`/`confidence` ride along in the `brief:`
block.

Draft location: `localStorage` in the static host; `ui/brief.yaml` on disk in the
local host (so it survives a browser wipe).

## 9. Gate logic

The UI **renders** gate state; it never evaluates it. `workflow/stages.py` and
`gates.py` remain authoritative, and `ready(stage, stages)` already decides
whether a prerequisite set is satisfied.

| gate | passes when | blocks |
|---|---|---|
| `INPUT_AUDIT` | wave-A answers present, units valid, brief frozen | everything |
| `LIMIT_IMPACT_ANALYSIS` | one `LimitImpact` per user limit (`QUALITATIVE` allowed) | architecture screening |
| `PHYSICAL_FEASIBILITY` | wavelengths / quarter-wave / mouth / compression computed; impossible combinations explicitly rejected | architecture screening |
| `ARCHITECTURE_SCREENING` | ≥1 feasible architecture scored; `SCREENING_ONLY` labelled | ideal optimisation |
| `IDEAL_ACOUSTIC_OPTIMIZATION` | an `AcousticMaster` with a first-class `S_target(s)` | fold work |
| `FOLD_TOPOLOGY_GENERATION` | ≥1 fold candidate per viable master | fold validation |
| `FOLD_GEOMETRY_VALIDATION` | area-law RMS within tolerance, length preserved, no self-intersection | fold-aware, structural, manufacturing |
| `ONE_DIMENSIONAL_SIMULATION` | a `SimulationRun` with the full SI column set | fold-aware, sensitivity |
| `FOLD_AWARE_SIMULATION` | reference vs folded compared | **W5 unlocks here** |
| `THREE_DIMENSIONAL_VERIFICATION` | **optional** — `skipped` by design (GUI solver); its inputs are W5's | nothing |
| `STRUCTURAL_SCREENING` | first-order screen, labelled `STRUCTURAL_SCREENING` | manufacturing |
| `MANUFACTURING_TRANSFORMATION` | a variant is watertight/faceted-valid, or the conflict is reported | critique |
| `CONSTRAINT_SENSITIVITY` | stricter + relaxed case per active limit | critique |
| `INDEPENDENT_CRITIQUE` | critic ran; findings attached | final comparison |
| `FINAL_COMPARISON` | best folded **and** best overall reported | report |
| `REPORT_AND_EXPORT` | report + artifacts + `app_view.json` written | — |

A stage that cannot pass returns a **typed failure** (`domain/failures.py`):
`category`, `failed_checks`, `affected_candidates`, `recoverable`,
`recommended_upstream_revision`, `evidence`. W3 renders it; W2 turns
`recommended_upstream_revision` into the primary button. Engineering infeasibility
is never an exception and never a red banner without a route forward.


## 10. W2 — next-action panel

One primary button, one line of *why*, one owner, and the blockers. Ordered rules,
first match wins (the same table as `jira-issue-flow.md` §7, minus the Jira rows):

| # | condition | label | owner |
|---|---|---|---|
| 1 | a wave-A question is unanswered | `Answer the required questions` | Requester |
| 2 | wave A complete, brief not frozen | `Freeze brief` | Requester |
| 3 | a blocking field has `provenance ∈ {DEFAULT, ESTIMATED}` | `Confirm the N assumed values` | Acoustics |
| 4 | no run for the current `input_hash` | `Start run` | Acoustics |
| 5 | a stage failed, `recoverable: false` | `Review the failure` | Acoustics |
| 6 | a stage failed, `recoverable: true` | `Re-run from <STAGE>` | Acoustics |
| 7 | `bem_state == GUI_REQUIRED` | `Copy AKABAK checklist` + `Open export folder` | Builder |
| 8 | `bem_state ∈ {MANUAL_SOLVE_PENDING, MANUAL_SOLVE_COMPLETED}` | `Import & validate (.vips)` | Builder |
| 9 | `outcome.bem == BEM_REJECTED` | `Re-export and retry` *or* `Accept as unvalidated` | Builder → Owner |
| 10 | critic has a `reject` finding | `Re-run from <STAGE>` | Acoustics |
| 11 | validated + `hard_gates` true, no decision | `Mark decided` | Owner |
| 12 | decision recorded | `Open the report` | Builder |

Non-negotiables: exactly **one** primary; every button is **idempotent**
(`Start run` mints a new run id and never overwrites; `Import` re-validates from
scratch); the panel is a **pure function of `app_view.json`**, so a reload
reproduces it.

## 11. W5 — manual AKABAK checklist panel

Opens when `manual_bem` exists. Content:

* **State tracker** — `GUI_REQUIRED → MANUAL_SOLVE_PENDING → MANUAL_SOLVE_COMPLETED`
  with the current one highlighted, plus the note that the next hop,
  `VIPS_IMPORTED`, comes from the import in W6 — **not** from this panel.
* **Why this is manual** — verbatim from HornFlow: *"AKABAK Free 3.3.2 b144 runs
  under Wine through its GUI; there is no usable head-less/CLI solve path, and the
  Free build does not write the solved BEM state (`.akpbe`) — it stays in RAM."*
  Never paraphrased into "automation pending".
* **Solver** — `AKABAK Free 3.3.2 b144` (`3.3-demo`).
* **Exact paths** — inputs dir, **export dir** (highlighted), manifest path.
* **Checklist** — the nine items from `akabak_recipe.md` as tick boxes:
  `start AKABAK` · `build the project` · `verify the BEM tree` ·
  `verify the LEM network` · `set the drive level` · `solve` ·
  `export the .vips spectra` · `confirm the folder is non-empty` · `send it back`.
  **Ticks are UI-local.** They live in `localStorage` and are never written to
  state — the single most important rule in the panel, because it is the one place
  a UI shortcut could fake progress.
* **Troubleshooting** — collapsed `<details>`, the six rows from the recipe
  (no window → `winecfg`; VACS dialog → harmless; flat curve → not *Driven*; model
  tiny/huge → Scaling = 1; empty export folder → tick *Text format*).
* **Live hint** — `exported_files` and `newest_export_utc`, so the user can see the
  app has noticed the files appear, *before* pressing Import.

## 12. W6 — `.vips` import panel

Opens at `MANUAL_SOLVE_PENDING`. Shows:

* the **export dir**, highlighted, with a copy button (the path is what people get
  wrong);
* the **expected glob** (`*.vips`) and the required spectrum (`Mic1` / `H 0-90`);
* **what is there now** — `exported_files` count and newest mtime, or *"no `.vips`
  files yet"*;
* the **buttons** — `Import & validate (.vips)` (local host) or
  `Copy import command` (static host);
* on failure, the **hard-validation detail** verbatim — e.g. *"older than the
  generated inputs"* — because that is a real trap (a stale export folder left over
  from a previous session).

Import runs HornFlow's own `bem_import.import_into_run()`, so the eight checks and
the comparison are the same code the CLI uses. The browser parses nothing.


## 13. W7 — validation outcome panel

Opens at `BEM_COMPARISON_COMPLETED`. Three parts:

1. **Validation table** — one row per check: name, `pass`/`FAIL`, `hard`/`soft`,
   verbatim detail (`"21 importable file(s) under …"`). Soft provenance items
   (`belongs_to_run` met only by timestamp, `run_manifest_matches` absent) are amber
   and explicitly *not* failures.
2. **Comparison** — curve used (`Mic1`), overlapping band and point count,
   **mean Δ**, **worst |Δ|**, tolerance, evidence label (`BEM_SIMULATION`), plus the
   standing note that the +3.01 dB peak-rendering convention has already been
   removed, so the numbers are rms-referenced and directly comparable with the
   1-D model.
3. **Verdict banner** — one of four:

| verdict | banner | exits |
|---|---|---|
| `BEM_VALIDATED` | green · **"Validated against the 1-D reference"** | `Mark decided` · `Open the report` |
| `BEM_REJECTED` | amber · **"Compared, but outside tolerance"** + the measured Δ and the likely cause (here: the documented free-standing 4π vs baffled 2π mounting offset) | `Re-export and retry` · `Accept as unvalidated` |
| hard validation failure | amber · **"The export did not pass validation"** — state stays `MANUAL_SOLVE_PENDING` | `Re-export and retry` |
| hard gate violated | red · **"Hard limit violated"** — which `FIXED` limit, by how much, and the smallest relaxation that clears it | `Re-run (new revision)` |

`Accept as unvalidated` is the only route past an amber result; it requires a reason
and is written into `decision_log` with author + UTC.

## 14. W8 — rerun behaviour

Two distinct reruns, never conflated:

| | `Re-run from <STAGE>` | `Re-run (new revision)` |
|---|---|---|
| enabled when | a typed failure names `recommended_upstream_revision` | always, after the first run |
| changes | nothing upstream of that stage | the brief |
| reuses | cached stages before that stage | nothing |
| produces | new run id, same brief revision | new **brief revision** + new run |

1. A rerun **never overwrites**: HornFlow mints a new `run_id`; the old run
   directory stays and remains addressable from the run picker.
2. `Re-run (new revision)` requires an edit in W4 first, then re-freezes:
   `revision+1`, new `input_hash`. The brief and the decision record are kept (the
   decision is marked `superseded`); everything else is regenerated.
3. Caching is keyed on the hash of **normalized inputs + geometry + grid + solver
   settings**, so changing only `bem_tolerance_db` reuses every 1-D result and
   re-runs nothing but the comparison.
4. After a rerun the app reloads `app_view.json`; any band whose run id differs from
   the header's shows a `stale` chip.

## 15. Button labels — exact strings

**Viewer tab** (existing first three are unchanged):

| label | enabled when | note |
|---|---|---|
| `Transparent` · `Cutaway` · `Reset view` | always | **unchanged** |
| `Dimensions` | `viewer.features.dimensions` | toggle; hidden when no annotations exist |
| `mm` / `m` | `Dimensions` is on | overlay unit, default `mm` |
| `Candidate` · `Reference` · `Side by side` | `viewer.features.compare` | view mode; falls back to `Candidate` alone |
| `Link cameras` | `Side by side` active | pan/zoom both together |

**Workflow tab:**

| label | band | mutates state |
|---|---|---|
| `Save draft` | W4 | no (localStorage / `ui/brief.yaml`) |
| `Freeze brief` | W4 | **yes** (writes the brief + `input_hash`) |
| `Start run` | W2 | **yes** (new run id) |
| `Import & validate (.vips)` | W2, W6 | **yes** (validation + comparison into `state.json`) |
| `Accept as unvalidated` | W7 | **yes** (a `decision_log` entry, needs a reason) |
| `Re-run from <STAGE>` | W2, W8 | **yes** (new run id) |
| `Re-run (new revision)` | W8 | **yes** (new revision + run) |
| `Mark decided` | W2 | **yes** (decision record) |
| `Copy AKABAK checklist` | W5 | no |
| `Open export folder` | W5 | no (copies the path) |
| `I exported the files` | W5 | no (UI-local flag) |
| `Copy import command` | W5, W6 | no |
| `Open the report` | W2, W7 | no |
| `Download artifacts` | W8 | no |
| `Refresh` | strip | no (re-fetch `app_view.json`) |

Two label rules: verbs first (`Import & validate (.vips)`, not `.vips import`), and
any button that consumes a file names the file type — that is the step people forget.


## 16. Transition rules (the eight states)

```
INPUTS_GENERATED ─▶ GUI_REQUIRED ─▶ MANUAL_SOLVE_PENDING ─▶ MANUAL_SOLVE_COMPLETED
                                                                      │
                        ┌─────────────────────────────────────────────┘
                        ▼
                  VIPS_IMPORTED ─▶ BEM_COMPARISON_COMPLETED ─┬─▶ BEM_VALIDATED
                                                             └─▶ BEM_REJECTED
     BEM_VALIDATED / BEM_REJECTED ──(re-import)──▶ VIPS_IMPORTED
```

| from | to | triggered by | UI effect |
|---|---|---|---|
| `INPUTS_GENERATED` | `GUI_REQUIRED` | `THREE_DIMENSIONAL_VERIFICATION` wrote mesh + LE script + manifest + checklist | W5 opens; W2 → `Copy AKABAK checklist` |
| `GUI_REQUIRED` | `MANUAL_SOLVE_PENDING` | the import attempt begins | W6 opens |
| `MANUAL_SOLVE_PENDING` | `MANUAL_SOLVE_COMPLETED` | import reached the files | — |
| `MANUAL_SOLVE_COMPLETED` | `VIPS_IMPORTED` | import ran **and all hard validation checks passed** | W7 opens with the 8-check table |
| `VIPS_IMPORTED` | `BEM_COMPARISON_COMPLETED` | the on-axis curve was compared with the 1-D reference | W7 shows mean/worst Δ vs tolerance |
| `BEM_COMPARISON_COMPLETED` | `BEM_VALIDATED` | `worst |Δ| ≤ bem_tolerance_db` | green banner |
| `BEM_COMPARISON_COMPLETED` | `BEM_REJECTED` | `worst |Δ| > tolerance` | amber banner + two exits |
| decided state | `VIPS_IMPORTED` | a **new** import of a **new** export | W6/W7 reopen; old decision kept in `decision_log` |

**Implementation note the UI must respect.** `--bem-import` walks the legal chain
itself (`workflow/bem_import.py::_walk_to`): `GUI_REQUIRED → MANUAL_SOLVE_PENDING →
MANUAL_SOLVE_COMPLETED → VIPS_IMPORTED → BEM_COMPARISON_COMPLETED → …`. So the
middle two states are *bookkeeping the import traverses*, not steps the user must
satisfy separately. The `I exported the files` click is a **convenience** that
enables the Import button early; it never sets state. The only transitions a real
import cannot skip are the last two.

**Forbidden, enforced by HornFlow (not the UI):**

* reaching `VIPS_IMPORTED` without a hard-validation pass;
* reaching `BEM_VALIDATED` without a completed comparison;
* skipping from a decided state anywhere other than back to `VIPS_IMPORTED`.

## 17. What mutates state

The **local host** exposes four endpoints; the static host degrades each to a
copy-command. All of them call the *same* HornFlow functions the CLI calls.

| action | static host | local host (`python3 -m hornflow.app --run-dir runs/<id>`) | writes |
|---|---|---|---|
| `Freeze brief` | writes `ui/brief.yaml`, user runs the command | `POST /api/brief` | `ui/brief.yaml` + `params/generated/<slug>.yaml` + `input_hash` |
| `Start run` | `Copy run command` | `POST /api/run` → `workflow.run_pipeline()` in-process | a new `runs/<run_id>/` |
| `Import & validate (.vips)` | `Copy import command` | `POST /api/import` → `bem_import.import_into_run()` | `state.json` (validation block), `bem_manual_report.md`, `compare.*` |
| `Accept as unvalidated` | — | `POST /api/decision` | a `decision_log` entry |
| `Re-run from <STAGE>` / `Re-run (new revision)` | `Copy run command` | `POST /api/run` with `from_stage` / a new brief | a new `runs/<run_id>/` |
| open report / download artifacts / `Refresh` | same | same | **nothing** (read-only) |
| `I exported the files`, checklist ticks, tab/camera/overlay state | localStorage | localStorage (+ optional `ui_flags.json`) | **nothing authoritative** |

Because every mutation goes through HornFlow, `state.json` stays the single source
of truth and the app cannot drift it. After any mutation the host re-emits
`app_view.json`, and the page re-renders from it.

## 18. Viewer tab vs Workflow tab — what goes where

| content | Viewer | Workflow |
|---|---|---|
| 3D geometry (duct, centreline, stations, throat, mouth) | **yes** | no |
| part legend, bbox readout | **yes** | no |
| `Transparent` / `Cutaway` / `Reset view` | **yes** | no |
| `Dimensions`, `mm`/`m`, `Candidate`/`Reference`/`Side by side`, `Link cameras` | **yes** | no |
| gate board, stage durations | no | **yes** |
| current state (BEM state, solver, evidence, assumptions) | status chip only (strip) | **yes** (W1) |
| questions / brief | no | **yes** (W4) |
| next action | one line in the strip | **yes** (W2, full) |
| manual AKABAK checklist, export path | no | **yes** (W5) |
| `.vips` import | no | **yes** (W6) |
| validation outcome, comparison numbers | no | **yes** (W7) |
| rerun | no | **yes** (W8) |
| SPL / impedance / excursion curves, limit impacts, best-folded vs best-overall, artifacts | no | no → **Results** (§19) |

The one overlap is the **strip**, which is shared so the current state and next
action are visible from either tab.

## 19. Results tab (placeholder)

Generated as an empty pane with a labelled, honest placeholder. Reserved content —
so the placeholder does not become a dumping ground later:

| block | source |
|---|---|
| Executive decision: best folded horn **and** best overall | `final_recommendations` |
| Limit-impact table (per limit: +, −, physical reason, most-affected outputs, state, suggested relaxation) | `limit_impacts` |
| Architecture comparison table (mean SPL, variation, excursion, Z, volume; `SCREENING_ONLY` badges) | `architecture_candidates` + `simulation_runs` |
| Sensitivity (stricter/relaxed per active limit, Δ, benefit-per-unit) | `sensitivity_runs` |
| Curve plots (SPL, Zin, excursion, group delay) | `simulation_runs` |
| Artifact list with `sha256` + evidence labels | artifact store |

Placeholder text: *"Results will render here in the next milestone. Until then,
open `deliverables/report.md`."*


## 20. Shortest path to a first runnable local version

Four milestones to the goal ("one real run executed end to end"), plus one optional.
M1–M3 need **no server and no new dependency**, and the app is inspectable in a
browser at every step.

| # | milestone | deliverable | done when |
|---|---|---|---|
| **M1** | **View model** | `hornflow/app/view.py` → `app_view.json` from `state.json` (+ `brief.json` when there is no run, `mode: first_run`) | a golden test emits twice from the same state and asserts byte-identical JSON; a `first_run` fixture emits the five questions with `run: null` |
| **M2** | **Shell + tabs (static)** | `hornflow/viz/viewer/index.html` gains the tab strip, the three `<section>` panes, `ui/app.js`, `ui/app.css`, and the `__APP_VIEW__` placeholder; `write_viewer(..., app_view=…)` fills it and copies `viewer/ui/` | an existing run's `viewer.html` is regenerated and the **geometry tab is byte-identical in behaviour**; a run with no `app_view` still opens with only the Viewer tab |
| **M3** | **Workflow tab (static, read-only)** | W1–W8 rendered from the embedded `app_view.json`; mutating buttons degrade to `Copy … command` | opening `viewer.html` from `file://` shows the gate board, the current state, and the correct single next action for the real JBL run |
| **M4** | **Local host = end-to-end run** | `python3 -m hornflow.app --run-dir runs/<id>` (stdlib `http.server`): serves the folder + `GET /api/view`, `POST /api/brief|run|import|decision`; `REPORT_AND_EXPORT` writes `app_view.json`; `--bem-import` re-emits it | **the goal:** answer the 5 questions → `Freeze brief` → `Start run` → see the gate board → do the manual AKABAK solve → `Import & validate (.vips)` → read the outcome, **all from the UI, on one real run** |
| **M5** | *(optional)* **Results tab**, `Re-run from <STAGE>`, run picker across `runs/` | the §19 blocks | the placeholder is replaced and reruns are one click |

Order matters: **M1 first**, because the view model is the contract and is testable
with no UI at all. M3 is then a few hundred lines of plain DOM against a frozen
schema. M4 is the smallest change that makes the buttons real, because it reuses
`bem_import.import_into_run()` and `workflow.run_pipeline()` **in-process** — no
subprocess, no shell, no new dependency.

### 20.1 Status — M1–M3 are built

| milestone | status | what landed |
|---|---|---|
| **M1** | **done** | `hornflow/app/view.py` (the deterministic view model + `FIRST_RUN_QUESTIONS`), `hornflow/app/__init__.py`, `tests/test_app_view.py`. `to_json()` sorts keys and every timestamp is injectable (`now=`), so two emissions of the same state are byte-identical — asserted against a trimmed *real* JBL state (`tests/fixtures/app_view/jbl_state_trimmed.json`). |
| **M2** | **done** | `hornflow/viz/viewer/index.html` gained the tab strip, the three panes, `__APP_VIEW__`, and two additive buttons (`Dimensions`, `m`/`mm`); `hornflow/viz/viewer/ui/{app.js,app.css}` are new; `write_viewer(..., app_view=…, annotations=…, glb_source=…)` fills them and copies `ui/`. The viewer's own markup and script are untouched. |
| **M3** | **done** | W1–W8 rendered from the embedded model only. No mutating action: every state-changing button is disabled with a reason and paired with a `Copy command`. Opens from `file://` and over http. |
| **M4** | next | the local host (`/api/*`) and the writable brief. |
| **M5** | later | the Results tab contents, `Re-run from <STAGE>`, the run picker. |

Implementation notes worth keeping:

* **One write, after the state is saved.** `Pipeline.stage_report()` only records
  the *expected* viewer paths; `_finalize()` writes `viewer.html` + `app_view.json`
  **after** `save_state` and `log.flush`, so the embedded snapshot and `state.json`
  can never disagree. A test asserts the two are equal.
* **`--emit-ui [RUN_DIR]`** re-renders the shell of an already-finished run from
  the saved state and the *existing* `scene.glb` (via `glb_source=`), without
  re-running the pipeline and without touching `state.json`. This is how a run that
  predates the shell gets one, and it is the M1–M3 half of "`--bem-import`
  re-emits the model".
* **Hidden panes keep their layout.** Inactive panes use `visibility: hidden`, not
  `display: none`, so the viewer's canvas never measures zero and the geometry tab
  behaves identically whichever tab opens first.
* **The initial tab follows the mode** (`?tab=` → saved → `first_run ? Workflow :
  Viewer`), per the "first run defaults to Workflow" decision.
* **`Dimensions` reads what it can.** The overlay needs no new data: the bbox comes
  from the loaded GLB, and the path length / throat / mouth / bend figures come from
  the `annotations` block in the view model.
* **Read-only by construction.** The view model is derived; the UI never reads
  `state.json`, and `import_panel.available` is `false` in the static host so the
  Import button cannot even appear actionable.

## 21. Risks and open decisions

| risk | mitigation |
|---|---|
| a `file://` page cannot `fetch('/api/view')` | it falls back to the embedded snapshot; the local host is started with one command and prints the URL |
| the embedded view model goes stale after a CLI import | `--bem-import` re-emits `app_view.json` **and** the app shows a `stale` chip when the run id in the JSON differs from the strip's |
| tabs break the existing viewer | the viewer's own script and markup are untouched; a run without `app_view` renders exactly as today (M2's acceptance test) |
| checklist ticks get mistaken for state | ticks are `localStorage`-only and W5 states that `VIPS_IMPORTED` comes from the import |
| the app grows into another engine | the "one rule" (§0): the UI renders and calls; it never computes or decides |
| two GLBs double the page weight | ~28 KB each; gate the second behind `viewer.features.compare` |

Open: (1) should the dimension overlay default to `mm` (proposed) or `m`?
(2) default tab — Viewer (proposed) or Workflow on a first run?
(3) does `Start run` stream progress (a `GET /api/log` tail of `logs.jsonl`) or just
block and refresh? (4) for `Accept as unvalidated`, free text only, or a fixed list?

