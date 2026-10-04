# Jira issue panel flow — HornFlow's first UI layer

> **⚠️ NOT THE CURRENT DIRECTION.** The project went **local-first**: the existing
> viewer becomes the app shell and a Workflow tab is added beside it, with **no
> Jira and no Forge**. See **[`app-local-multitab.md`](app-local-multitab.md)** for
> the design now being built, and **ADR-0011** in `adr.md` for why.
>
> This document is kept because its *field, question, gate and transition* work
> carries over unchanged — only the hosting decision (Jira issue panel) is
> superseded. The brief schema (§3.3), the question waves (§4), the gate rules
> (§5), the twelve next-action rules (§7) and the authority split (§8) are all
> still referenced by the local design.

Scope of this document: **the issue panel only** — issue fields, required
questions, the state machine, screen sections, next-action logic, and the
Jira/HornFlow split. Geometry editing and solver internals are explicitly out of
scope.

## 0. The one rule

**Jira holds the request and the decision. HornFlow holds the physics and the
evidence.**

The panel is a *projection* of `state.json` (schema `1.0`), never a second copy of
it. If a number was computed, it lives in HornFlow and Jira only links to it. If
it was decided by a human, it lives in Jira and HornFlow only cites it.

## 1. Layer model

```
Jira issue  ──owns──▶  brief (intent)  ·  decision  ·  assignment  ·  notification
     │                                    ▲
     │ projects                           │ cites (comment id)
     ▼                                    │
HornFlow run ──owns──▶  SI inputs · geometry · simulations · evidence · artifacts
```

* One issue ↔ **N runs** (`run.jira_issue_key`; issue field `hornflow.run.latest_run_id`).
* The panel reads: `run`, `project`, `requirements`, `driver`, `constraints`,
  `limit_impacts`, `feasibility`, `architecture_candidates`, `fold_candidates`,
  `simulation_runs`, `sensitivity_runs`, `manufacturing_variants`, `validation`,
  `critic_findings`, `decision_log`, `final_recommendations`, `stages`.

## 2. Architecture decisions

| id | decision | consequence |
|---|---|---|
| **J1** | The brief is **one versioned JSON field** (`hornflow.brief`), not N custom fields. | HornFlow stays the schema owner; the repo's `MIGRATIONS` pattern applies; no 40-field drift. |
| **J2** | Jira never stores a computed number as truth. Rendered values are read-only snapshots carrying `run_id` + evidence label + source hash. | A stale snapshot can never be mistaken for a fresh result. |
| **J3** | The panel renders **exactly one primary next action**, derived from state (not from navigation). | Next-action logic is a pure function; reproducible after a refresh. |
| **J4** | Jira status is a **projection of `stages`** and may never be *ahead* of it. | Guards refuse `Running → Review` while a required stage is failed. |
| **J5** | The brief is **frozen** on run start (input hash). Edits make a new revision and a new run. | Runs stay immutable; the old run is never reinterpreted. |
| **J6** | Approvals live in Jira only; `decision_log` stores a *reference* to the Jira comment. | No decision is invented by automation. |
| **J7** | Automation is append-only and bounded: gated milestones + failures only. | Human comments, Priority, Assignee are never touched by HornFlow. |
| **J8** | Small mirrored fields (`next_action`, `manual_state`, `latest_run_id`, `evidence_bar`) exist for **search/board filters** only; the JSON is authoritative. | Filters work without turning Jira into a database. |

## 3. Issue fields

### 3.1 Native Jira fields (owned by Jira)

| field | type | notes |
|---|---|---|
| Project / Issue type | fixed | `HORN` / **Horn Design Request** |
| Key | auto | `HORN-123` — the human handle of the request |
| Summary | text | ``<driver model> <band> for <deployment>`` (templated) |
| Status | workflow | the 10 states in §5 |
| Priority | enum | Blocker / High / Medium / Low |
| Reporter / Assignee | user | requester / acoustics owner |
| Labels | set | `folded-preferred`, `cardioid-required`, `printable`, `plywood`, `weather-exposed`, `battery` |
| Components | set | `flow-brief`, `flow-pipeline`, `akabak-manual`, `manufacturing` |
| Fix Version | version | target build / deployment |
| Links | link | `blocks` / `is-blocked-by`; `relates to` the driver-data issue |
| Attachments | file | **rendered deliverables only**: `report.md`, viewer GLB, printed STL, plywood schedule |

### 3.2 HornFlow fields (mirrored, read-only projections)

| field | type | source | purpose |
|---|---|---|---|
| `hornflow.brief` | JSON text | HornFlow, from the panel form | **authoritative brief** (§3.3) |
| `hornflow.run` | JSON text | `run` + `final_recommendations` + `validation` | `latest_run_id`, `best_folded`, `best_overall`, `gates_passed`, `bem_status` |
| `hornflow.artifacts` | JSON text | artifact store | `name → {path, sha256, bytes, evidence}` |
| `hornflow.next_action` | short text | §7 | board filters / "my queue" views |
| `hornflow.manual_state` | enum | `ManualSolveState` | `GUI_REQUIRED` … `BEM_VALIDATED`/`BEM_REJECTED` |
| `hornflow.evidence_bar` | enum | `acceptance.evidence_bar` | `MINIMUM` / `HIGH` |

### 3.3 The brief (`hornflow.brief`, schema `1.0`)

Field groups mirror the pipeline's input groups exactly, so the panel maps 1:1 onto
`config.py` / `DesignState`. **Every leaf is an object, never a bare scalar** — that
is how `InputStatus`, provenance, confidence, range and uncertainty travel with each
value (the spec's per-input requirement, and the repo's `Constraint` record).

```json
{
  "brief_schema": "1.0",
  "revision": 3,
  "frozen": { "at_utc": "2026-10-03T17:29:19+00:00", "input_hash": "sha256:…" },
  "project":       { "name": {}, "deployment": {}, "operating_orientation": {},
                     "transport_orientation": {}, "boundaries": {} },
  "driver":        { "manufacturer": {}, "model": {}, "data_source": {},
                     "Re": {}, "Fs": {}, "Qes": {}, "Qms": {}, "Qts": {},
                     "Vas": {}, "Sd": {}, "Bl": {}, "Mms": {}, "Cms": {},
                     "Rms": {}, "Le": {}, "Xmax": {}, "xmax_convention": {},
                     "thermal_power_w": {}, "vc_diameter_mm": {},
                     "existing_enclosure": {}, "removable_driver": {} },
  "target":        { "f_min_hz": {}, "f_max_hz": {}, "passband_hz": {},
                     "flatness_pm_db": {}, "spl_continuous_db": {},
                     "spl_peak_db": {}, "measurement_distance_m": {},
                     "max_distortion_pct": {}, "rear_rejection_db": {},
                     "coverage_h_deg": {}, "coverage_v_deg": {},
                     "crossover_hz": {}, "dsp_allowed": {} },
  "electrical":    { "amp_voltage_v": {}, "amp_channels": {},
                     "min_safe_impedance_ohm": {}, "load_capability": {},
                     "battery_wh": {}, "dsp_capability": {} },
  "physical":      { "max_width_mm": {}, "max_height_mm": {}, "max_depth_mm": {},
                     "max_external_volume_m3": {}, "max_mass_kg": {},
                     "max_acoustic_path_mm": {}, "max_mouth_width_mm": {},
                     "max_mouth_height_mm": {}, "min_bend_radius_mm": {},
                     "max_fold_count": {}, "materials": {},
                     "material_thickness_mm": {}, "service_access": {},
                     "weather_resistance": {} },
  "manufacturing": { "method": {}, "printer_build_volume_mm": {}, "nozzle_mm": {},
                     "layer_height_mm": {}, "printable_wall_mm": {},
                     "available_materials": {}, "max_part_dim_mm": {},
                     "plywood_thickness_mm": {}, "cutting_processes": {},
                     "permitted_mitre_deg": {}, "curved_panel_techniques": {},
                     "fasteners": {}, "adhesives_sealants": {},
                     "assembly_tolerance_mm": {} },
  "acceptance":    { "prefer_folded": {}, "evidence_bar": {},
                     "bem_tolerance_db": {}, "must_beat_alternative": {} }
}
```

Each leaf:

```json
{ "value": 18.0, "unit": "mm",
  "status": "FIXED",                         // FIXED | PREFERRED | RANGE | OPTIMIZABLE | UNKNOWN
  "provenance": "USER_INPUT",                // USER_INPUT | MEASURED | DATASHEET | ESTIMATED | DEFAULT
  "confidence": 1.0,
  "range": null,                             // [lo, hi] when status == RANGE
  "uncertainty": null,
  "question_id": "Q-PHY-06",
  "answered_by": "alex", "answered_utc": "2026-10-03T17:20:00+00:00" }
```

### 3.4 Ownership per field group

| group | Jira declares | HornFlow computes / normalizes |
|---|---|---|
| `project`, `target`, `acceptance` | the intent | SI normalization, derived `fc`, `krm_target` |
| `driver` | the T/S set + data source | `Sd`, `fs`, `Qms/Qes/Qts`, `Vas` (recomputed and cross-checked) |
| `electrical` | amp + load limits | drive voltage/current, excursion, thermal margin |
| `physical` | envelope + mass + access | route length, bend radii, packaging efficiency, mass |
| `manufacturing` | method + machine limits | variant partition, panel schedule, deviations |


### 3.5 Brief group → `DesignState` path (exact mapping)

The brief is worded for humans; `state.json` uses the pipeline's own key names.
The panel maps them explicitly so there is exactly one translation point.

| brief group | `state.json` path | observed keys |
|---|---|---|
| `project` | `project`, `run` | `project.name`, `project.author`, `run.run_id`, `run.input_path` |
| `driver` | `driver` | `name`, `Re_ohm`, `Fs_hz`, `Qts`, `Vas_l`, `Sd_cm2`, `Xmax_mm`, `Xmax_convention` |
| `target` (band) | `constraints.acoustic` | `f_low_hz`, `f_high_hz` |
| `target` (rest) | `requirements` (currently `{}`) | filled by the panel on freeze |
| `electrical` | `constraints.electrical` | `voltage_vrms` |
| `physical` | `constraints.physical` | `depth_mm`, `mouth_area_cm2` |
| `manufacturing` | `constraints.manufacturing` | `method` |
| `acceptance` | `requirements` + panel-only | `evidence_bar`, `bem_tolerance_db`, `must_beat_alternative` |
| every leaf's `status`/`provenance` | `constraints.*` `Constraint{name,value,unit,status,hard,low,high,confidence,uncertainty,provenance}` | the brief leaf is the *declaration*; the `Constraint` is its *audit record* |

Two consequences worth stating:

* The panel **writes the brief only**; `constraints` are produced by
  `INPUT_AUDIT`, so a disagreement between them is a visible bug, not a silent one.
* The brief keeps values the pipeline does not yet consume (`battery_wh`,
  `permitted_mitre_deg`, …). They are stored under `requirements` so nothing is
  lost, and the panel marks them `UNKNOWN → not used by this milestone`.

## 4. Required questions

Questions are asked in **three waves**. The panel *stops* on wave A, *asks* wave B
only when it changes the architecture choice, and *defaults* wave C with a visible
`DEFAULT` label.

Every question row is `Q-<group>-<nn>` and records: prompt, type, unit, default
status, why it matters, and the state field it lands in.

### 4.1 Wave A — blocking (STOP; no run without these)

| id | question | unit | status | why it matters (feeds) |
|---|---|---|---|---|
| `Q-PRJ-01` | What is this for, and where will it stand? (free / wall / corner / vehicle) | text+enum | FIXED | boundary condition → `feasibility.boundary`, mouth loading |
| `Q-PRJ-02` | Operating orientation and transport orientation | enum | FIXED | fold choice, service access |
| `Q-DRV-01` | Driver manufacturer and model | text | FIXED | identity; pins the T/S set |
| `Q-DRV-02` | Where do the T/S numbers come from? (measured / datasheet / estimated) | enum | FIXED | **provenance + confidence** on every downstream number |
| `Q-DRV-03` | Re, Fs, Qes, Qms, Vas, Sd, Bl, Mms, Cms, Le | SI | FIXED | the entire 1-D model; `fs` self-check |
| `Q-DRV-04` | Xmax — value **and** convention (one-way vs peak-to-peak) | mm + enum | FIXED | **safety-critical**; displacement limit, SPL cap |
| `Q-DRV-05` | Thermal power rating and voice-coil diameter | W / mm | FIXED | thermal margin (never invent it) |
| `Q-TGT-01` | Lowest and highest frequency of interest | Hz | RANGE | `f_low/f_high` → mouth, path, size |
| `Q-TGT-02` | Required **continuous** SPL and at what distance | dB @ m | FIXED | SPL goal → displacement/thermal check |
| `Q-PHY-01` | Maximum external width, height, depth (or total volume) | mm / m³ | FIXED | hard size gate |
| `Q-PHY-02` | Maximum mass | kg | FIXED | hard mass gate; material choice |
| `Q-MFG-01` | Manufacturing method (3-D print / plywood / either) | enum | FIXED | **chooses the transformer**; panel branches |
| `Q-ELE-01` | Amplifier voltage and channels available | V / int | FIXED | drive level; excursion/thermal margin |
| `Q-ELE-02` | Minimum safe load impedance | Ω | FIXED | **safety-critical** hard gate |

### 4.2 Wave B — materially changes architecture (asked, not defaulted)

| id | question | feeds |
|---|---|---|
| `Q-PHY-03` | Maximum acoustic path / depth budget | path-limited vs mouth-limited diagnosis |
| `Q-TGT-03` | Is rear rejection required? how much? | cardioid / gradient branch |
| `Q-TGT-04` | Horizontal and vertical coverage targets | directivity feasibility |
| `Q-PHY-04` | Maximum mouth width / height | aperture → directivity |
| `Q-PHY-05` | Minimum bend radius and maximum fold count | fold topology feasibility |
| `Q-PHY-06` | Must the driver be removable / serviceable? | fold + panel layout |
| `Q-PHY-07` | Weather exposure | material + sealing |
| `Q-ACC-01` | Must the answer beat a stated alternative? | decision rule |

### 4.3 Wave C — defaulted, labelled `DEFAULT`, confirmable later

| id | question | default | note |
|---|---|---|---|
| `Q-TGT-05` | Passband flatness | ±4 dB | drives the flatness score |
| `Q-TGT-06` | Maximum distortion | 5 % | screening only |
| `Q-TGT-07` | Crossover frequency / DSP allowed | none / no | affects target band edges |
| `Q-ELE-03` | Battery energy budget | 0 Wh | only if `battery` label present |
| `Q-MFG-02` | Printer build volume, nozzle, layer height, wall | 250³ mm, 0.6, 0.25, 3× nozzle | print branch only |
| `Q-MFG-03` | Plywood thickness, cutting processes, permitted mitre | 18 mm, saw/CNC, 45° | plywood branch only |
| `Q-ACC-02` | BEM tolerance for `BEM_VALIDATED` | 6 dB | mirrors `--bem-tolerance-db` |

### 4.4 Stop conditions

The panel halts and asks the user only when:

1. a **wave-A** question is unanswered → status `Blocked`, listing exactly which;
2. two requirements conflict and no priority resolves them → `Blocked`, ask for a ranking;
3. a **safety-critical** parameter is unknown (`Q-DRV-04` convention, `Q-ELE-02`, thermal rating);
4. every feasible design would violate a `FIXED` constraint.

Otherwise it proceeds with `DEFAULT`/`ESTIMATED` values, each marked, and surfaces
them in an **"Assumptions to confirm"** list (count shown on the header strip).


## 5. State machine

Two coupled machines. The Jira workflow is a **projection** of the run state
(J4); the panel recomputes it, it never sets it by hand except for the
human-owned transitions marked ★.

### 5.1 Jira workflow — the issue

```
Draft ──▶ Briefing ──▶ Ready ──▶ Running ──▶ Awaiting manual BEM ──▶ Review ──▶ Decided ──▶ Archived
  │           │           ▲          │                │                  │                   
  └───────────┴───────────┘          ▼                ▼                  ▼                   
                            Blocked ─┘        Blocked ┘          Cancelled★ ────────────────┘
```

| status | meaning | entry guard |
|---|---|---|
| `Draft` | brief created, nothing answered | issue created |
| `Briefing` | ≥1 answer recorded, wave A incomplete | any answer present |
| `Ready` ★ | wave A complete; brief **frozen** (`input_hash`) | `ready_for_screening == ready` |
| `Running` | a run exists for the current `input_hash` and is in flight | run started |
| `Awaiting manual BEM` | all pre-BEM stages passed; GUI solve pending | see §5.2 |
| `Review` | pipeline finished; critic has run | `FINAL_COMPARISON` passed |
| `Decided` ★ | a human recorded accept-folded / accept-alternative / reject | decision record exists |
| `Blocked` | typed failure requiring a human, or a conflict | see §5.3 |
| `Archived` ★ | decision closed, artifacts frozen | `Decided` + archive |
| `Cancelled` ★ | abandoned | — |

### 5.2 The BEM interlock (the important guard)

`Running → Review` is **forbidden** while the manual BEM step is open. The panel
uses:

```
bem_open = state.validation.bem_status == "pending_external"
        or  hornflow.manual_state in {GUI_REQUIRED, MANUAL_SOLVE_PENDING, MANUAL_SOLVE_COMPLETED}
```

* `bem_open` → status `Awaiting manual BEM`.
* `Running → Review` requires `bem_status ∈ {validated, rejected}` **and** an
  import report on disk — i.e. a real validation + comparison happened. This is
  the Jira-level expression of *"never `BEM_VALIDATED` before a `.vips` import
  plus comparison"*.
* `BEM_REJECTED` does **not** unlock `Review`; it produces a next action (§7 rule 8).
  A reviewer may explicitly accept the result as *unvalidated* — that is a decision,
  not a status change, and is recorded as such.

### 5.3 Typed failure → status

Engineering infeasibility is data (`domain/failures.py::StageFailure`), not an
exception. The panel renders it:

| failure | next status | panel shows |
|---|---|---|
| `recoverable: true` | stays `Running`, next action = apply the revision | `category`, `failed_checks`, `recommended_upstream_revision`, evidence |
| `recoverable: false` | `Blocked` | the same, escalated, owner = Acoustics |
| wave-A gap | `Blocked` (from `Briefing`) | the missing question ids |
| conflict (no priority) | `Blocked` | the two requirements + a ranking prompt |
| all feasible designs violate a `FIXED` limit | `Blocked` | which `FIXED` limit, and the smallest relaxation that would clear it |

### 5.4 Illegal transitions the panel refuses

* `Ready → Running` unless the brief is frozen and `input_hash` is computed (J5).
* `Running → Review` while any **required** (non-optional) stage is `failed`/`blocked`
  → must go `Blocked`.
* `Running → Review` while `bem_open` (§5.2).
* `Review → Decided` unless the critic has run **and** `hard_gates_passed`; an
  override requires a written reason recorded on the decision.
* Any `Blocked → *` without an upstream revision or a human resolution comment.
* `Decided → Running` on the *same* brief revision — a changed brief is a new
  revision and therefore a new run (the old run stays linked and immutable).

### 5.5 Run-state side (unchanged, for reference)

The 16 stages (`workflow/stages.py`) with the existing prerequisite DAG, and the
eight-state `ManualSolveState`
(`INPUTS_GENERATED → GUI_REQUIRED → MANUAL_SOLVE_PENDING → MANUAL_SOLVE_COMPLETED
→ VIPS_IMPORTED → BEM_COMPARISON_COMPLETED → BEM_VALIDATED | BEM_REJECTED`, plus the
re-import edge). The panel never invents a ninth state on either side.


## 6. Screen sections

One vertical scroll, sticky verdict header, right rail. No tabs that hide gate
state — a section is *visible but locked* rather than absent, so the user always
sees what is coming.

Every section header carries a chip: `locked` (prerequisite not passed) ·
`ready` · `failed` · `stale` (state older than the current brief revision).

| # | section | reads from | content | empty state | blocked by |
|---|---|---|---|---|---|
| **S1** | Verdict strip (sticky) | `final_recommendations`, `validation`, `critic_findings` | best folded horn · best overall · hard gates ✓/✗ · BEM state · assumptions count · evidence bar | "No run yet" | — |
| **S2** | Next action | §7 | **one** primary CTA + one-line *why* + owner + blockers | "Answer the 4 blocking questions" | — |
| **S3** | Brief & questions | `hornflow.brief` | wave A/B/C accordion; answer widgets; completeness meter; "Assumptions to confirm" | blank form | — |
| **S4** | Input audit | `constraints`, `driver`, `run` | table: value · unit · status chip · provenance · confidence · permitted range · uncertainty | locked | S3 wave A |
| **S5** | Limit impact | `limit_impacts` | the required table: positive / negative / physical reason / most-affected outputs / constraint state / suggested relaxation; `QUALITATIVE` vs measured badge | locked | `LIMIT_IMPACT_ANALYSIS` |
| **S6** | Feasibility | `feasibility` | λ, quarter/half-wave, `k·rm` mouth, displacement- & thermal-limited SPL, compression, **limiting factors**, explicit rejections | locked | `PHYSICAL_FEASIBILITY` |
| **S7** | Architecture comparison | `architecture_candidates`, scores | ranked table with `WIRED` / `SCREENING_ONLY` / `SIMULATED` badges; folded-horn bonus shown separately from score | locked | `ARCHITECTURE_SCREENING` |
| **S8** | Candidate workspace | `reference_profiles`, `acoustic_candidates`, `fold_candidates`, `manufacturing_variants` | read-only: master `S_target(s)`, fold families, area-law error, bend table, packaging metrics; **viewer + export links** | locked | `FOLD_GEOMETRY_VALIDATION` |
| **S9** | Manual BEM hand-over | `validation.bem_manual`, manifest, recipe | the run checklist mirror, exact export path, "open AKABAK", "I exported" → **Import & validate**, then the 8-check table + Δ vs 1-D | locked | `FOLD_AWARE_SIMULATION` |
| **S10** | Sensitivity | `sensitivity_runs` | stricter/relaxed per active limit, deltas, benefit-per-unit ranking | locked / "not run" | `CONSTRAINT_SENSITIVITY` |
| **S11** | Validation & critic | `stages`, `critic_findings`, gates | gate table + critic findings (pass/warn/reject) with the affected stage | locked | `INDEPENDENT_CRITIQUE` |
| **S12** | Evidence & artifacts | artifact store, `decision_log` | every artifact with `sha256` + evidence label + download; decision log; run history | locked | `REPORT_AND_EXPORT` |
| **R** | Right rail | `run`, `project` | `run_id`, schema version, solver + version, git commit, warnings count, run list, "Diff vs previous run" | — | — |

Deliberately **not** in this first layer: geometry editing, solver parameter
editing, cost/scheduling, multi-user locking. S8 is a *reader* with export links.


## 7. Next-action logic

`next_action(brief, latest_run, decision) → Action` — an **ordered rule table**,
first match wins. It is a pure function of state (J3): no hidden UI state, so a
refresh reproduces it exactly.

```
Action := { id, label, why, gate, owner, cta, blockers[], evidence[] }
owner  ∈ { Requester, Acoustics, Builder, Owner }
```

| # | condition | action (label) | owner |
|---|---|---|---|
| 1 | wave-A question unanswered | **Answer `Q-…`** (lists them) | Requester |
| 2 | brief not frozen for the current answers | **Confirm & freeze the brief** | Requester |
| 3 | a blocking field has `provenance ∈ {DEFAULT, ESTIMATED}` | **Confirm the N assumed values** | Acoustics |
| 4 | no run for the current `input_hash` | **Run the pipeline** | Acoustics |
| 5 | `StageFailure.recoverable == false` | **Escalate: `<category>`** — human revision needed | Acoustics |
| 6 | `StageFailure.recoverable == true` | **Apply `<recommended_upstream_revision>` & re-run** | Acoustics |
| 7 | `bem_status == pending_external` | **Do the GUI solve, export `.vips`, then import** | Builder |
| 8 | `manual_state == BEM_REJECTED` | **Re-export, or relax `bem_tolerance_db`** (show measured Δ, e.g. mean −8.68 dB) | Builder → Acoustics |
| 9 | critic has a `reject` finding | **Resolve `<check>` and re-run from `<stage>`** | Acoustics |
| 10 | `Review` and no decision | **Record the decision** (accept folded / accept alternative) | Owner |
| 11 | decided, `best_overall != folded_horn` | **Review the alternative** — relaxing `<limit>` would recover `<Δ>` *(from `sensitivity_runs`, else labelled QUALITATIVE)* | Owner |
| 12 | decided | **Open / export the build package** | Builder |
| 13 | decided + artifacts frozen | **Archive** | Owner |

Rules:

* **Exactly one** action renders as the primary button; the rest appear under
  "also pending" so the user is never shown a menu of equals (J3).
* Actions are **idempotent**: *Run* mints a new `run_id` (never overwrites);
  *Import* re-validates from scratch; *Freeze* is a no-op if the hash is unchanged.
* Every action carries its `gate` so S2 can link straight to the blocking section.
* Rule 11 only quotes numbers that exist in `sensitivity_runs`; otherwise it says
  "expected benefit … (QUALITATIVE — no sensitivity run yet)".

### 7.1 Worked examples

| situation | panel shows |
|---|---|
| 4 blocking answers missing | primary **"Answer Q-TGT-01, Q-PHY-01, Q-MFG-01, Q-ELE-02"**; S3 open at wave A |
| brief complete, no run | **"Run the pipeline"** (est. seconds) |
| run done, BEM open | **"Do the GUI solve → export → Import"**; S9 expanded, checklist mirrored |
| imported, mean Δ −8.7 dB at 6 dB tolerance | **"Re-export or relax `bem_tolerance_db` to ≥ 12 dB"** + the measured table |
| critic rejected the folded-horn win | **"Resolve `fold_vs_reference` and re-run from FOLD_AWARE_SIMULATION"** |
| everything green | **"Record the decision"**, then **"Export the build package"** |

## 8. What stays in Jira vs HornFlow

### 8.1 Authority

| concern | authority | notes |
|---|---|---|
| Intent (band, SPL, size, mass, method) | **Jira** (`hornflow.brief`) | HornFlow normalizes to SI and cross-checks |
| Normalized SI inputs, `input_hash` | **HornFlow** | Jira stores the hash read-only |
| T/S identity & derived `Sd/fs/Qts/Vas` | **HornFlow** | recomputed and compared with the declared set |
| Every computed number (SPL, Zin, excursion, DI, area error, mass) | **HornFlow** | never editable in Jira |
| Evidence labels & validity flags | **HornFlow** | `ANALYTICAL_ESTIMATE` … `BEM_SIMULATION` |
| Geometry, meshes, spectra, binary artifacts | **HornFlow** | Jira gets links + `sha256` + small renders |
| Gate truth (`stages`, `critic_findings`) | **HornFlow** | Jira status is a projection (J4) |
| Priority, assignee, sprint, links, notifications | **Jira** | HornFlow never writes these |
| Decision & rationale | **Jira** (human comment) | `decision_log` copies `{jira_comment_id, author, utc}` — one-way (J6) |
| Schema migrations (`state.json`) | **HornFlow** | `MIGRATIONS`, refuse unknown versions |
| Brief migrations (`hornflow.brief`) | **HornFlow** | same pattern; never silently reinterpret |

### 8.2 What never crosses

* **→ Jira:** master geometry, meshes, STL/3MF/GLB binaries, caches, full
  spectrum tables, `.vips` exports, solver internals, anything with a raw float
  and no evidence label.
* **→ HornFlow:** approvals, priority, assignment, comments, links, attachments,
  sprint data, cost.

### 8.3 Sync contract

* One issue : N runs. `run.jira_issue_key` in the state; `hornflow.run.latest_run_id` on the issue.
* Automation is **append-only and deduplicated** by `(run_id, stage, event)`:
  a retry cannot double-post. It writes comments only at **gated milestones and
  failures** — not per stage.
* Automation may update only the four mirrored fields (§3.2). It never edits a
  human comment, never changes Priority/Assignee, never transitions to `Decided`.
* **Conflict rule:** if a human edits the brief after freeze, the panel mints a new
  `revision` + `input_hash` and requires a new run; the previous run stays linked
  and immutable (J5).
* A rendered value in Jira always shows `run_id` + evidence label; if the hash no
  longer matches the current run, the section shows the `stale` chip.


## 9. Deferred to the next UI layers

> **The concrete MVP is specified in [`ui-two-tab-mvp.md`](ui-two-tab-mvp.md)** — the
> two-tab interface (Geometry + Workflow), the `workflow_view.json` contract, the
> first-run screen, the five questions, exact button labels, the manual-AKABAK /
> imported-result / pass-fail blocks, the rerun flow, and the Forge plan.

* **Layer 2 — brief form UX**: autosave, per-field validation messages, unit
  pickers, "copy from a linked driver-data issue".
* **Layer 3 — evidence drill-down**: the S8 viewer embedded, artifact diffing
  between runs, ParaView hand-off.
* **Layer 4 — geometry editing** and **solver parameter editing** (explicitly out
  of scope here).
* Cost / scheduling / multi-user locking.

## 10. Open questions for the user

1. **Jira flavour** — Cloud (Forge app, custom-field limits) or Data Center
   (REST + a server app)? This decides how the panel is hosted.
2. **Hosting** — a Jira-native app, or an external web panel (the existing
   stdlib Three.js viewer style) linked from the issue? The latter keeps the
   zero-dependency production baseline.
3. **Is `Ready` a workflow status** (as designed) or a boolean flag on `Running`,
   to keep the board to 6 columns?
4. **Who owns `Freeze`** — the requester, or an automated rule once wave A passes?
5. **`must_beat_alternative`** — should the panel refuse `Decided` when the folded
   horn wins only on the preference bonus? (The critic already flags it; this
   would make it a hard panel gate.)

