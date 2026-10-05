"""Markdown report renderer (Stage 16) - the 20 required sections."""

from __future__ import annotations

from . import limit_impact

EV = "evidence"


def _fsig(v, nd=3):
    if v is None:
        return "n/a"
    try:
        return f"{float(v):.{nd}f}"
    except (TypeError, ValueError):
        return str(v)


def render(ctx: dict) -> str:
    L = []
    p = ctx["params"]
    master = ctx.get("master")
    fz = ctx.get("feasibility")
    run_id = ctx.get("run_id", "?")
    best_folded = ctx.get("best_folded")
    best_overall = ctx.get("best_overall")
    scores = ctx.get("scores", [])
    L += [f"# HornFlow design report - {p.project}", "",
          f"run id: `{run_id}`  ",
          f"schema: `{ctx.get('schema_version')}`  ",
          f"input: `{p.source_path}`", ""]

    # 1 -------------------------------------------------------------------
    L += ["## 1. Executive decision", ""]
    if best_folded:
        L.append(f"* **Best folded horn:** `{best_folded.family}` "
                 f"(fold `{best_folded.fold_id}`), valid={best_folded.valid}.")
    else:
        L.append("* **Best folded horn:** none produced.")
    if best_overall:
        L.append(f"* **Best overall architecture:** {best_overall.get('display_name')} "
                 f"(`{best_overall.get('architecture_id')}`, "
                 f"{best_overall.get('fidelity')}).")
        L.append(f"* Reasons: weighted score {_fsig(best_overall.get('score'))} "
                 f"(mean SPL {_fsig(best_overall.get('spl_mean_db'),1)} dB, "
                 f"variation {_fsig(best_overall.get('spl_variation_db'),1)} dB).")
        if best_overall.get("architecture_id") == "folded_horn":
            L.append("* The folded horn is also the best overall design here.")
        else:
            L.append("* The folded horn is **not** the best overall design for these "
                     "constraints; both results are reported below.")
    L += ["", "_Evidence: see the labels on every table (USER_INPUT, "
          "ANALYTICAL_ESTIMATE, ONE_DIMENSIONAL_SIMULATION, BEM_SIMULATION)._", ""]

    # 2 -------------------------------------------------------------------
    L += ["## 2. Input audit", "", "| item | value | unit | status |", "| --- | --- | --- | --- |"]
    for c in ctx.get("constraints", []):
        L.append(f"| {c.name} | {c.value} | {c.unit} | {c.status} |")
    L += [""]

    # 3 -------------------------------------------------------------------
    L += ["## 3. Limit-impact table", "",
          limit_impact.to_markdown(ctx.get("limit_impacts", [])), ""]

    # 4 -------------------------------------------------------------------
    L += ["## 4. Feasibility diagnosis", "",
          f"Evidence: **{getattr(fz, 'evidence', 'ANALYTICAL_ESTIMATE')}**", ""]
    if fz:
        L += [f"* wavelengths: " + ", ".join(
            f"{k} {v*1e3:.0f} mm" for k, v in fz.wavelengths_m.items()),
              f"* quarter/half wave @f_low: {fz.quarter_wave_m*1e3:.0f} / "
              f"{fz.half_wave_m*1e3:.0f} mm",
              f"* mouth k*rm @f_low: {fz.krm_at_flow:.2f} "
              f"({'adequate' if fz.mouth_adequate else 'small'})",
              f"* displacement-limited SPL: {_fsig(fz.displacement_spl_db,1)} dB",
              f"* thermal-limited SPL: {_fsig(fz.thermal_spl_db,1)} dB",
              f"* throat compression Sd/St: {fz.throat_compression:.2f} "
              f"({fz.compression_note})",
              f"* **limiting factors:** {', '.join(fz.limiting_factors) or 'none'}"]
        if fz.rejected:
            L.append("* **rejected combos:** " + "; ".join(fz.rejected))
    L += [""]

    # 5 -------------------------------------------------------------------
    L += ["## 5. Architecture comparison", "",
          "| architecture | fidelity | feasible | mean SPL (dB) | variation (dB) | "
          "score | implementation |", "| --- | --- | --- | --- | --- | --- | --- |"]
    for s in scores:
        L.append(f"| {s['display_name']} | {s['fidelity']} | {s['feasible']} | "
                 f"{_fsig(s.get('spl_mean_db'),1)} | {_fsig(s.get('spl_variation_db'),1)} | "
                 f"{_fsig(s.get('score'))} | {s.get('implementation')} |")
    L += ["", "_SCREENING_ONLY architectures cannot defeat a simulated candidate "
          "without a warning (see the critic findings). " + "_", ""]
    L += [_render_sections(ctx)]
    return "\n".join(L)


def _render_sections(ctx: dict) -> str:
    L = []
    master = ctx.get("master")
    best_folded = ctx.get("best_folded")
    folds = ctx.get("fold_candidates", [])
    runs = ctx.get("runs", {})
    gates = ctx.get("gates", [])

    L += ["## 6. Best folded-horn result", ""]
    if best_folded:
        L += [f"* family: **{best_folded.family}**, fold id `{best_folded.fold_id}`",
              f"* centreline length: {best_folded.centreline.length:.3f} m",
              f"* bends: {len(best_folded.bends)}",
              f"* area-law RMS error vs master: {best_folded.area_report.rms:.4f}",
              f"* packaging: bbox {best_folded.packaging['bbox_w_m']:.2f} x "
              f"{best_folded.packaging['bbox_h_m']:.2f} x "
              f"{best_folded.packaging['bbox_d_m']:.2f} m, "
              f"eta_pack {best_folded.packaging['eta_pack']:.3f}, "
              f"mass {best_folded.packaging['mass_kg']:.1f} kg",
              f"* active constraints: "
              f"{', '.join(g.name for g in gates if not g.passed) or 'none'}"]
    else:
        L.append("* no valid folded candidate was produced")
    L += [""]

    L += ["## 7. Best overall result", ""]
    for s in ctx.get("scores", [])[:3]:
        L.append(f"* {s['display_name']} ({s['architecture_id']}) - fidelity "
                 f"{s['fidelity']}, score {_fsig(s.get('score'))}, "
                 f"mean {_fsig(s.get('spl_mean_db'),1)} dB, variation "
                 f"{_fsig(s.get('spl_variation_db'),1)} dB")
    L += [""]

    L += ["## 8. Ideal unfolded profile (the reference)", ""]
    if master:
        sts = master.area_law.evaluate([0, master.length/4, master.length/2,
                                        3*master.length/4, master.length]) * 1e4
        L += [f"* profile: {master.profile}, throat {master.throat_area*1e4:.0f} cm^2, "
              f"mouth {master.mouth_area*1e4:.0f} cm^2, ratio {master.area_ratio:.1f}",
              f"* path L: {master.length:.3f} m, aspect {master.aspect}, "
              f"boundary {master.boundary}",
              "* areas at 0/25/50/75/100 % [cm^2]: " + ", ".join(f"{s:.0f}" for s in sts)]
    L += [""]

    L += ["## 9. Fold candidate comparison", "",
          "| family | R (m) | valid | L (m) | bends | area RMS | eta_pack | mass (kg) |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for f in folds:
        L.append(f"| {f.family} | {_fsig(f.metadata.get('requested_R_m','-'))} | "
                 f"{f.valid} | {f.centreline.length:.3f} | {len(f.bends)} | "
                 f"{f.area_report.rms:.4f} | {f.packaging['eta_pack']:.3f} | "
                 f"{f.packaging['mass_kg']:.1f} |")
    L += [""]

    L += ["## 10. Bend-analysis table", ""]
    if best_folded and best_folded.bends:
        L += ["| s0-s1 (m) | angle (deg) | R (m) | inner (m) | width (m) | severity | "
              "path diff (mm) | phase skew (deg) | transverse (Hz) | risk | construction |",
              "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
        for b in best_folded.bends:
            L.append(f"| {b.s0:.2f}-{b.s1:.2f} | {b.angle_rad*57.2958:.1f} | "
                     f"{b.radius_m:.3f} | {b.inner_radius_m:.3f} | {b.duct_width_m:.3f} | "
                     f"{b.severity:.3f} | {b.path_diff_m*1e3:.1f} | {b.phase_skew_deg:.1f} | "
                     f"{b.transverse_mode_hz:.0f} | {b.reflection_risk} | {b.construction} |")
        L.append("\n_Phase skew is a screening metric, not a substitute for field simulation._")
    else:
        L.append("* no bends (straight reference).")
    L += [""]

    L += ["## 11. Acoustic simulation comparison", ""]
    for cid, r in runs.items():
        m = r.metrics or {}
        L.append(f"* `{cid}` ({r.solver} {r.solver_version}, {r.fidelity}): "
                 f"mean {_fsig(m.get('spl_mean_db'),1)} dB, "
                 f"variation {_fsig(m.get('spl_variation_db'),1)} dB, "
                 f"Zmin {_fsig(m.get('ze_min_ohm'),2)} ohm, "
                 f"excursion {_fsig(m.get('excursion_rms_mm'),3)} mm rms / "
                 f"{_fsig(m.get('excursion_peak_mm'),3)} mm peak")
    L += [""]
    L += [_render_tail(ctx)]
    return "\n".join(L)


def _render_tail(ctx: dict) -> str:
    L = []
    variants = ctx.get("variants", [])
    sens = ctx.get("sensitivity", [])
    critic = ctx.get("critic", [])
    gates = ctx.get("gates", [])
    viz_files = ctx.get("viz_files", {})
    best_folded = ctx.get("best_folded")

    L += ["## 12. Interactive 3D visualization", ""]
    if viz_files:
        L += [f"* open **`{viz_files['viewer'].name}`** in a browser (offline, no server) - "
              "orbit/pan/zoom, transparent + cutaway modes, centreline and area stations",
              f"* raw scene: `{viz_files['glb'].name}` (glTF 2.0 binary; also opens in any "
              "glTF viewer, Blender, Windows 3D Viewer)"]
    else:
        L.append("* not generated")
    L += ["* acoustic fields (VTU) are a documented deferred stub until 3-D data exists", ""]

    L += ["## 13. Constraint sensitivity", "",
          "Evidence: **ONE_DIMENSIONAL_SIMULATION**", "",
          "| limit | stricter | relaxed | d mean SPL | d variation | d cutoff | "
          "d excursion | d envelope |",
          "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for rec in sens:
        d = rec.get("delta_relaxed", {})
        L.append(f"| {rec['limit']} | {_case(rec['stricter'])} | {_case(rec['relaxed'])} | "
                 f"{_fsig(d.get('spl_mean_db_delta'),2)} | "
                 f"{_fsig(d.get('spl_variation_db_delta'),2)} | "
                 f"{_fsig(d.get('cutoff_minus3db_hz_delta'),1)} | "
                 f"{_fsig(d.get('excursion_peak_mm_delta'),4)} | "
                 f"{_fsig(d.get('envelope_m3_delta'),4)} |")
    L += ["", "_d = relaxed - base. Do not relax a limit unless the benefit is "
          "meaningful._", ""]

    L += ["## 14. 3D-print variant", ""]
    L += _variant_block(_by_method(variants, "additive"))
    L += ["## 15. Plywood variant", ""]
    L += _variant_block(_by_method(variants, "plywood"))

    L += ["## 16. Structural screening", "",
          "Evidence: **STRUCTURAL_SCREENING** (first-order screen, not FEA)", "",
          "* unsupported span (max mouth dimension) and brace spacing must be checked "
          "against panel thickness before build;",
          "* driver-mount and mouth-edge stiffness should be reinforced for a mouth "
          "this large;",
          "* centre of mass and stability: keep the driver low and central in the fold.",
          ""]

    L += ["## 17. Build risks", ""]
    risks = []
    if best_folded:
        risks.append(f"{len(best_folded.bends)} bend(s) require wall-collision and "
                     "air-tightness care" if best_folded.bends else "no bends")
    for v in variants:
        risks += [f"{v.method}: {w}" for w in v.warnings]
    for txt in (risks or ["none identified"]):
        L.append(f"* {txt}")
    L += [""]

    L += ["## 18. Validation status", "", "| gate | passed | detail | evidence |",
          "| --- | --- | --- | --- |"]
    for g in gates:
        L.append(f"| {g.name} | {g.passed} | {g.detail} | {g.evidence} |")
    L += [""]

    L += ["## 19. Uncertainties", ""]
    _v = ctx.get("validation")
    _bem = _v.get("bem_manual") if isinstance(_v, dict) else None
    if _bem:
        L += [f"* 3-D BEM verification is **{_bem.get('state')}** - the external solve is "
              "manual by design (AKABAK Free 3.3.2 b144 runs under Wine through its GUI; "
              "no usable head-less/CLI solve path, and the Free build does not write the "
              "solved BEM state `.akpbe`);",
              f"* to complete it: run the GUI solve, export the `.vips` spectra to "
              f"`{_bem.get('export_dir')}`, then re-run with `--bem-import`; the candidate "
              "becomes `BEM_VALIDATED` only after that import **plus** the comparison "
              "against the 1-D reference;",
              f"* solver: {_bem.get('solver')} (`{_bem.get('solver_version')}`);"]
    else:
        L += ["* 3-D BEM verification is **pending** (AKABAK runs via its GUI; inputs are "
              "generated, external solve not automated);"]
    L += ["* SCREENING_ONLY box architectures use T/S analytical estimates, not "
          "simulations;",
          "* printed/plywood mass figures are geometric estimates, not weighed.",
          ""]

    L += ["## 20. Next measurements / experiments", "",
          "* run the manual AKABAK GUI solve for the folded candidate (checklist: "
          "`deliverables/bem/akabak_recipe.md`), export the `.vips` spectra to "
          "`deliverables/bem/export/`, then re-run with `--bem-import` to validate and "
          "compare against the ideal reference;",
          "* measure the assembled horn's impedance and on-axis response;",
          "* confirm print wall/clearance settings reproduce the modelled acoustic surface.",
          ""]

    L += ["## Appendix A - independent critic", ""]
    for f in critic:
        mark = "PASS" if f.passed else f.severity.upper()
        L.append(f"* [{mark}] {f.check}: {f.detail}")
    L += [""]
    return "\n".join(L)


def _case(d: dict) -> str:
    vals = {k: v for k, v in d.items() if k != "metrics"}
    return ", ".join(f"{k.split('.')[-1]}={v}" for k, v in vals.items())


def _by_method(variants, method):
    for v in variants:
        if v.method == method:
            return v
    return None


def _variant_block(v) -> list:
    if v is None:
        return ["* not generated", ""]
    L = [f"* variant `{v.variant_id}` - valid={v.valid}"]
    for k, val in v.metrics.items():
        L.append(f"* {k}: {val}")
    if v.panels:
        L.append(f"* panels/parts: {len(v.panels)}")
    for w in v.warnings:
        L.append(f"* WARNING: {w}")
    if v.deferred:
        L.append(f"* deferred formats: {', '.join(v.deferred)} (see .DEFERRED.txt notes)")
    L += [""]
    return L

