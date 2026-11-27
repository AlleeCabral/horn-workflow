# HornFlow roadmap: design

Status: draft for owner approval. Source material: `docs/audit/2026-11-26-hornflow-audit.md` and the planning conversation of 2026-11-26.

## Intent

HornFlow is the owner's personal tool for designing and building their own horns. Development has felt confusing: two generations of tooling, a fragile manual AKABAK round trip, documents that contradict each other, and no issue tracker.

The goal is a tool the owner enjoys using. It should:
- go from "I have a driver and a box size" to "I have a validated horn I can build and carry to an event";
- give immediate interactive feedback;
- keep a memory of the design history;
- never claim more than its evidence supports.

## Goals

1. **Trustworthy core.** The run record cannot be corrupted or forged. Reports do not overclaim. Every run can be reproduced from its folder. (Audit findings S1 to S12, P1 to P12, B1 to B4, U1, U2, T1, T2.)
2. **Tuning bench.** Sliders on the main geometry and drive parameters. Stage 1 curves redraw immediately, a "ghost" of the previous design stays behind them, and Xmax is drawn on the excursion plot.
3. **Design diary.** A timeline of runs, a diff of inputs between any two runs, overlaid curves, and the reason a design was chosen. It replaces `handoff.md` and the history log.
4. **Honesty labels.** Every reported number carries its evidence level: `ANALYTICAL_ESTIMATE`, `ONE_D_SIMULATION`, `BEM_HEADLESS`, `BEM_AKABAK`, or `MEASURED`. A headline claim can never exceed its weakest input.
5. **Interactive bending.** The owner bends the horn's centreline in the 3-D viewer: drag bend points, set each bend's angle and radius. Length and area law are preserved. Box size, clearances, bend-risk warnings and panel lists update live.
6. **Headless BEM.** Stage 2 runs from Python with an open-source BEM solver (bempp-cl), coupled to the existing Python driver model. AKABAK becomes an occasional cross-check, and `tests/fixtures/bem_export/Akabak-Rad1_23Sept26-*` is the reference to reproduce.
7. **Build companion.**
   - For a folded design: plywood cut lists with real bend angles, and an exploded assembly view.
   - For transport: a **telescoping printed horn** that collapses for carrying to **outdoor events**. Sections nest inside each other, the joints seal and latch, and big sections are split into printable tiles. The tool reports collapsed volume and mass per piece.
8. **Measurement loop.** Import a measurement of the built horn (REW text export) and compare measured against modelled, with the `MEASURED` label.
9. **Nothing to install (optional).** A single offline HTML file that runs Stage 1 in the browser with Pyodide. Nice to have, not required.
10. **Project hygiene.**
    - One "start here" README; superseded documents archived.
    - GitHub Issues with the audit backlog.
    - The legacy and pipeline code paths merged behind one set of services.

## Non-goals

- No rewrite and no framework migration. ADR-0001 (wrap, do not rewrite, the validated core) still holds.
- No accounts, no cloud service, no database. The run folder stays the store.
- No Docker for now.
- The folded-horn preference stays a preference. The tool must never favour it over evidence.

## Anti-goals (failure even if it "works")

- A `BEM_VALIDATED` label, an architecture "win" or a "safe" gate that the evidence does not support.
- A bent or telescoping design shown as "valid" by a check that cannot fail.
- Interactive features that compute results in the browser that the Python model does not own (ADR-0013, ADR-0014).
- A telescoping horn that leaks, buzzes, or cannot be assembled at an event by one person.

## Constraints

- Python 3.10, 3.11 and 3.12 (the CI matrix). Production dependencies stay `numpy`, `scipy`, `PyYAML`, `matplotlib`.
- New dependencies are optional extras in `requirements-optional.txt`, imported lazily, with a clear message when missing: `bempp-cl` (Phase 3), and possibly `gmsh` (Phase 3). This follows ADR-0010.
- The viewer stays offline with no build step: Three.js r128 is vendored. Any added Three.js module comes from the same r128 release and is vendored too.
- `main` is protected (CONTRIBUTING.md). Every change goes through a `feat/`, `fix/` or `docs/` branch and a pull request, and CI must be green.
- Legacy `run_workflow.py` outputs stay governed by `tests/test_baseline.py`. Any intended change to them regenerates the baseline in the same pull request, with the reason stated.

## Approaches considered

| Approach | Trade-off | Decision |
|---|---|---|
| A. Fix the audit findings first, then build features on the corrected core | Slower to the first visible feature, but every feature sits on honest data | **Chosen** |
| B. Build the features first, then fix | Fast demos, but the bench, diary and bending would display corrupted or overclaimed results | Rejected |
| C. Rewrite around a web framework | Large risk; throws away a validated core | Rejected (ADR-0001) |

For Stage 2, headless bempp-cl was chosen over scripting the AKABAK GUI, NumCalc, ABEC/ATH and FEM; see the conversation and audit section D.

## Decided by the owner

- The headless BEM direction, with AKABAK kept as a cross-check.
- All six creative proposals, plus interactive bending and a telescoping printed horn.
- The telescoping horn is for **transport to outdoor events**.

## Open decisions (owner)

Each is a `needs-decision` task in the plan. Until decided, the plan uses the placeholder shown in brackets.

1. **D1. BEM tolerance range.** May "relax tolerance" ever lead to validated? [allowed range 0.5 to 20 dB, default 6; relaxing above 6 dB yields `BEM_ACCEPTED_WITH_TOLERANCE`, never `BEM_VALIDATED`]
2. **D2. Excursion safety-gate drive level and band.** [evaluate at `simulation.gate_voltage`, defaulting to `simulation.voltage`, over the passband only]
3. **D3. Fold selection.** Lowest bend risk or most compact. [lowest bend risk first, then compactness]
4. **D4. Folded-horn bonus.** [bonus 1.0 point on the dB-based score; a raw tie within 0.5 points is reported as "no acoustic winner"]
5. **D5. Build targets.** Telescoping printed straight horn confirmed for transport. Is the plywood folded horn still wanted? [yes, both]
6. **D6. Meaning of "max depth".** Box depth or centreline length. [box depth]
7. **D7. Reference radiation condition for Stage 1.** [kept as configured per definition; reports state it; headless BEM solves both]
8. **D8. Telescoping horn requirements.** Maximum piece mass, maximum collapsed size (a car boot?), printer bed size, material (PETG or ASA for sun and rain), and assembly time. [mass per piece 8 kg or less; bed 350 × 350 × 350 mm; PETG; one person, 10 minutes or less]

## What is left to the builder

- Exact UI layout of the bench, diary and bending editor, within the existing tab shell (`hornflow/viz/viewer/index.html`, `ui/app.js`).
- Internal module boundaries inside each phase, following the plan's file map.
