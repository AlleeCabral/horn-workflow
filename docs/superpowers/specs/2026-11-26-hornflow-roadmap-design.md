# HornFlow roadmap: design

Status: approved by the owner on 2026-11-27, with decisions D1 to D8 recorded below. Source material: `docs/audit/2026-11-26-hornflow-audit.md` and the planning conversation of 2026-11-26.

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

## Decided by the owner (2026-11-26)

- The headless BEM direction, with AKABAK kept as a cross-check.
- All six creative proposals, plus interactive bending and a telescoping printed horn.
- The telescoping horn is for **transport to outdoor events**.

## Decided by the owner (2026-11-27)

D1 to D8, the eight open decisions, are closed. Each answer is recorded in its Jira issue and applied in the phase named at the end of its entry.

### D1. BEM validation (HORN-31)

Two separate checks.

- **Solver check:** headless solver against AKABAK on the same model, tight. Target 1 to 2 dB, with the final number set in Phase 3 from the mesh convergence study.
- **Model check:** 1-D against 3-D with the same radiation condition. Within 3 dB is "consistent"; above it is an explained difference, never hidden.

Raising the tolerance above the default never produces `BEM_VALIDATED`; it produces `BEM_ACCEPTED_WITH_TOLERANCE`. Allowed range 0.5 to 20 dB, default 6 dB. The Phase 0 Task 6 constants stay; the new state name is added in Task 6, the earlier of Task 6 and Task 14.

Applied in: Phase 0 Task 6 (constants and the new state), Phase 3 Task 3.6 (tolerances).

### D2. Excursion safety gate (HORN-32)

Amplifier: 300 W class D with a programmable DSP, high-pass available.

- **Pass/fail check:** at full amplifier power, 300 W into the driver's nominal impedance, over the passband, **with** the DSP high-pass applied. `gate_voltage = sqrt(300 * Z_nominal)`. Use the driver's `Re` when the driver file has no nominal impedance, and say so in the report.
- **Warning only:** the same 300 W without the high-pass, over the full range.
- **The tool recommends the high-pass** for the DSP: the lowest corner frequency (Butterworth, order 2 and 4 shown) that keeps peak excursion at or below one-way peak Xmax at 300 W.
- **Target loudness** is not fixed. The report states the maximum SPL reachable at 300 W within Xmax, which is the useful number at an event.

Config, all defaulting to "as before":

```
simulation.amp_power_w: float | None = None
simulation.highpass: {fc_hz, order, type: "butterworth"} | None = None
simulation.gate_band: "passband" | "full"
```

New module `hornflow/physics/highpass.py`:

```
highpass_response(f, fc_hz, order) -> complex ndarray      # applied to the drive voltage
recommend_highpass(params, power_w, orders=(2, 4)) -> list[{order, fc_hz, peak_mm}]
```

Tests: the gate uses `sqrt(300 * Z)` volts; with the recommended high-pass the gate passes; without it the warning names the frequency where Xmax is exceeded; the report shows the recommended DSP settings.

Applied in: Phase 0 Task 15.

### D3. Fold selection (HORN-33)

Lowest bend risk among the folds that fit the size limits. Compactness only breaks ties.

Applied in: Phase 2 Task 2.4.

### D4. Folded preference (HORN-34)

Tie-breaker only. `PREFERENCE_BONUS = 1.0` point, `TIE_TOLERANCE_POINTS = 0.5`. Ties are reported as "No acoustic winner".

Applied in: Phase 0 Task 9, where the placeholders become final.

### D5. Build target (HORN-35)

The telescoping printed straight horn comes first (Phase 4 Tasks 4.3 to 4.9). The plywood folded horn moves to the backlog, in HORN-40 "Plywood folded horn build output (cut list, DXF)", in the Phase 4 epic with label `later`. Phase 4 Tasks 4.1 and 4.2 are deferred to that issue.

Applied in: Phase 4 of the roadmap.

### D6. "Max depth" (HORN-36)

"Max depth" is the outside size of the finished horn: box depth when folded, total extended length when straight. Centreline length is derived from it.

A separate limit covers the collapsed length: `transport.max_collapsed_length_mm`, default `None`, which means report only.

The brief lives in HORN-41 "Brief: depth budget limits the outside size, not the path length" (audit U6), in the Phase 1 epic.

Applied in: Phase 1 Task 1.10, referenced from Phase 2 Task 2.4 and Phase 4 Task 4.3.

### D7. Radiation condition (HORN-37)

The horn stands **on the ground outdoors**.

- Stage 1 keeps `half_space: true` as the approximation of ground placement, and the report says "ground placement approximated as half space".
- Phase 3 solves both: (a) a reflecting ground plane under the horn, as the reference, and (b) free-standing, as a comparison. The 1-D against 3-D model check from D1 uses (a).

Applied in: Phase 3 Task 3.8.

### D8. Telescoping horn for a cargo bike (HORN-38)

**Weight:** as light as possible while panel vibration stays tolerable. Every panel's first resonance must lie above `f_high` of the passband (Phase 4 Task 4.7); the design uses the lightest wall plus rib layout that meets it. The report states mass per piece and total mass.

```
transport.max_piece_mass_kg  = 10     # overridable, not a hard limit yet
transport.max_total_mass_kg  = None   # report only
```

**Transport:** the report states collapsed length, width, height, volume and centre of mass, so it can be checked against the cargo bike box. The design adds carry handles and strap anchor points.

**Printer:** not confirmed, so it is a parameter: `manufacturing.printer_bed_mm = [256, 256, 256]` by default, a common consumer size. Every tiling output is recomputed from it.

**Material for sun and rain, best cost-benefit:** PETG with an outdoor UV-protective coating by default; it is cheaper and easier to print. ASA is the alternative when the printer is enclosed, being UV-stable without coating and harder to print. Parameter `manufacturing.material = "PETG" | "ASA"`. The build sheet lists the coating steps for PETG.

**Assembly time:** no hard limit. The build sheet estimates it and lists the steps.

Applied in: Phase 4 Tasks 4.3 to 4.9.

## What is left to the builder

- Exact UI layout of the bench, diary and bending editor, within the existing tab shell (`hornflow/viz/viewer/index.html`, `ui/app.js`).
- Internal module boundaries inside each phase, following the plan's file map.
