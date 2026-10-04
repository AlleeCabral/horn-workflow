#!/usr/bin/env python3
"""horn-workflow: parameter file in, horn simulation out.

Stage 1: 1P (Webster) horn model + lumped-element driver -> throat impedance,
on-axis SPL, electrical impedance, excursion, directivity index, plus the design
checks from the horn-theory paper. `--advise` derives the geometry from a size
budget, `--sweep` compares designs.

Stage 2: `--stage 2` writes the AKABAK inputs (lumped-element driver script, BEM
mesh in MSH 2.2, click-by-click recipe); `--bem-import <folder>` reads the
exported spectra back and compares them with the Stage-1 model.

`--build` turns the simulated design into makeable geometry: profile CSV/DXF,
slice stack, a closed STL solid, the BEM mesh and a build sheet.

Usage:
    python run_workflow.py params/horn_80_250Hz.yaml
    python run_workflow.py params/horn_80_250Hz.yaml --out results/run1
    python run_workflow.py params/horn_80_250Hz.yaml --build
    python run_workflow.py params/horn_80_250Hz.yaml --stage 2
    python run_workflow.py params/horn_80_250Hz.yaml --bem-import ~/akabak_export
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hornflow import __version__, advise, config, plots, report, response, sweep   # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="run_workflow.py",
        description="Run the horn workflow from a single definition file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "examples:\n"
            "  python run_workflow.py params/horn_80_250Hz.yaml\n"
            "  python run_workflow.py params/horn_80_250Hz.yaml --sweep\n"
            "  python run_workflow.py params/horn_80_250Hz.yaml "
            "--sweep horn.mouth_radius=450,600,750 --sweep horn.length=600,900\n"
            "  python run_workflow.py params/horn_jbl_1200b.yaml --build\n"
            "  python run_workflow.py params/horn_jbl_1200b.yaml --stage 2\n"
            "  python run_workflow.py params/horn_jbl_1200b.yaml "
            "--bem-import ~/akabak_export\n"
        ),
    )
    p.add_argument("definition", help="path to the YAML definition file")
    p.add_argument("--out", default=None,
                   help="output directory (default: <project>/<output.dir>)")
    p.add_argument("--stage", default="stage1", metavar="1|2",
                   help="stage1 (default) = 1P model + lumped-element driver; stage2 also "
                        "writes the AKABAK inputs (BEM mesh, LE driver script, recipe). "
                        "Accepts 1/2 or stage1/stage2.")
    p.add_argument("--sweep", action="append", nargs="?", const="", metavar="KEY=v1,v2",
                   help="run a comparison grid instead of a single design; with no "
                        "value the 'sweep:' block of the definition file is used. "
                        "Repeat for more axes.")
    p.add_argument("--advise", action="store_true",
                   help="derive the geometry from a size budget: mouth and depth for a "
                        "range of cut-offs, ranked, with the gain over the direct radiator")
    p.add_argument("--advise-targets", default=None, metavar="f1,f2,...",
                   help="cut-off frequencies to design for [Hz] (default: around target.f_low)")
    p.add_argument("--advise-depth", type=float, default=1500.0, metavar="mm",
                   help="maximum horn depth [mm] (default 1500)")
    p.add_argument("--advise-aspect", type=float, default=None, metavar="W:H",
                   help="mouth width/height ratio (default: horn.mouth_aspect from the file)")
    p.add_argument("--advise-kmin", type=float, default=0.7, metavar="k",
                   help="minimum mouth criterion k*rm to accept (default 0.7)")
    p.add_argument("--advise-kmax", type=float, default=1.0, metavar="k",
                   help="mouth criterion the depth budget is spent up to (default 1.0)")
    p.add_argument("--build", action="store_true",
                   help="write the build package: profile CSV/DXF, slice stack, STL, "
                        "BEM mesh, build sheet")
    p.add_argument("--build-slice-size", type=float, default=100.0, metavar="mm",
                   help="slice thickness for the stack (default 100 mm)")
    p.add_argument("--build-wall", type=float, default=18.0, metavar="mm",
                   help="wall thickness for the slice frames and the solid (default 18 mm)")
    p.add_argument("--build-mesh-frequency", type=float, default=500.0, metavar="Hz",
                   help="mesh frequency for the BEM mesh in the build package (default 500 Hz)")
    p.add_argument("--no-geo", action="store_true",
                   help="skip the optional Gmsh .geo file and the gmsh call")
    p.add_argument("--bem-import", default=None, metavar="FOLDER",
                   help="import AKABAK/VACS exported spectra from FOLDER and compare "
                        "them with the Stage-1 model")
    p.add_argument("--bem-tolerance-db", type=float, default=6.0, metavar="dB",
                   help="max |difference| between the BEM on-axis curve and the Stage-1 "
                        "model for the import to count as validated (default 6 dB)")
    p.add_argument("--bem-mesh-frequency", type=float, default=500.0, metavar="Hz",
                   help="mesh frequency for the Stage-2 BEM mesh (default 500 Hz)")
    p.add_argument("--bem-baffle", type=float, default=400.0, metavar="mm",
                   help="width of the optional baffle ring around the mouth (0 = none)")
    p.add_argument("--bem-platform", default="wine", choices=("wine", "windows"),
                   help="where AKABAK will run; only affects the wording of the recipe")
    p.add_argument("--bem-symmetry", default=None, choices=("x", "y", "xy"), metavar="x|y|xy",
                   help="also write a cut mesh (bem_half.msh / bem_quarter.msh) for a "
                        "project that exploits Global -> Dim, Sym and BEM -> Symmetry")
    p.add_argument("--no-plots", action="store_true", help="skip the figures")
    p.add_argument("--no-csv", action="store_true", help="skip the CSV export")
    p.add_argument("--quiet", action="store_true", help="print nothing but errors")
    p.add_argument("--version", action="version", version=f"horn-workflow {__version__}")
    return p


def _axes_from_args(args, params) -> dict:
    """Merge the 'sweep:' block of the file with any --sweep KEY=values axes."""
    axes: dict = {}
    for spec in args.sweep:
        spec = (spec or "").strip()
        if spec:
            key, values = sweep.parse_sweep_arg(spec)
            axes[key] = values
    if not axes:
        block = (params.raw or {}).get("sweep") or {}
        axes = {k: list(v) for k, v in block.items()}
    else:
        # unnamed axes from the file are added too (kept for convenience)
        block = (params.raw or {}).get("sweep") or {}
        for k, v in block.items():
            axes.setdefault(k, list(v))
    return axes


def run_sweep_mode(args, params, out_dir, log) -> int:
    axes = _axes_from_args(args, params)
    if not axes:
        print("error: no sweep axes given. Use --sweep key=v1,v2 or add a 'sweep:' "
              "block to the definition file.", file=sys.stderr)
        return 2

    def progress(i, n, row):
        state = ("ok" if row.ok else f"failed ({row.error})")
        log(f"  [{i}/{n}] {row.label} -> {state}")

    log(f"sweep over {len(sweep.grid(axes))} designs")
    for k, v in axes.items():
        log(f"  {k}: {v}")
    result = sweep.run(params.source_path, axes, out_dir, make_plots=not args.no_plots,
                       progress=progress)
    log("")
    rows = result["rows"]
    ok = [r for r in rows if r.ok]
    log(f"{len(ok)}/{len(rows)} designs completed")
    if ok:
        sl = sweep.shortlist(rows)
        log("")
        log("shortlists:")
        for name, row in (("smoothest", sl["flattest"]), ("smallest nearly as smooth",
                                                          sl["compact"]),
                          ("lowest cut-off", sl["lowest_fc"]),
                          ("best covering your band", sl["best_in_band"])):
            if row:
                m = row.metrics
                log(f"  {name:28s} {row.label}  ->  mouth {sweep.mouth_text(m)} mm, "
                    f"depth {m['length_mm']:.0f} mm, fc {m['fc_hz']:.0f} Hz, "
                    f"variation {m['spl_variation_db']:.1f} dB, envelope {m['envelope_m3']:.2f} m3")
        if sl.get("f_low") and not sl.get("best_in_band"):
            log(f"  note: no design has its cut-off at or below {sl['f_low']:.0f} Hz - "
                f"all are small/short for that band")
    log("")
    log(f"output directory: {out_dir}")
    for f in result["files"]:
        log(f"  {Path(f).name}")
    log("")
    log("read sweep_report.md for the full table and the plain-language summary")
    return 0 if ok else 1


def run_advise_mode(args, params, out_dir, log) -> int:
    targets = None
    if args.advise_targets:
        try:
            targets = [float(v) for v in str(args.advise_targets).split(",") if v.strip()]
        except ValueError as exc:
            print(f"error: --advise-targets needs comma-separated numbers ({exc})",
                  file=sys.stderr)
            return 2
    aspect = args.advise_aspect or params.horn.mouth_aspect

    log(f"advising: depth limit {args.advise_depth:.0f} mm, mouth aspect {aspect:.1f}:1, "
        f"k*rm window {args.advise_kmin:.2f}-{args.advise_kmax:.2f}")
    def progress(i, n, label, fits):
        log(f"  [{i}/{n}] {label} -> {'design ok' if fits else 'does not fit the budget'}")

    data = advise.run(params.source_path, targets=targets, depth_limit=args.advise_depth,
                      aspect=aspect, k_min=args.advise_kmin, k_max=args.advise_kmax,
                      out_dir=out_dir, make_plots=not args.no_plots, progress=progress)

    floor = data["floor_fc"]
    log("")
    if floor == floor:                      # not NaN
        c = advise.make_candidate(floor, params.horn.throat_diameter / 2.0,
                                  args.advise_depth * 1e-3, aspect, args.advise_kmin,
                                  args.advise_kmax, params.simulation.c)
        log(f"lowest cut-off your depth can support: {floor:.1f} Hz  ->  mouth "
            f"{c.mouth_width * 1e3:.0f} x {c.mouth_height * 1e3:.0f} mm")
    else:
        log(f"with {args.advise_depth:.0f} mm of depth, k*rm = {args.advise_kmin:.2f} is out "
            f"of reach for these cut-offs")
    best = advise.best_candidate(data)
    low = advise.lowest_candidate(data)
    if best:
        m = best.metrics
        log(f"recommended (smoothest) : {best.label}  ->  k*rm {m['k_rm']:.2f}, "
            f"{m['spl_mean_db']:.1f} dB mean, {m['spl_variation_db']:.1f} dB variation, "
            f"air {m['air_volume_l']:.0f} l")
    if low and low is not best:
        log(f"most low end            : {low.label}  ->  k*rm {low.metrics['k_rm']:.2f}, "
            f"{low.metrics['spl_variation_db']:.1f} dB variation")
    log("")
    log(f"output directory: {data['out_dir']}")
    for f in data["files"]:
        log(f"  {Path(f).name}")
    log("")
    log("read advise_report.md for the full table and the gain-over-direct-radiator numbers")
    return 0


def main(argv: list | None = None) -> int:
    args = build_parser().parse_args(argv)
    t0 = time.time()
    args.stage = {"1": "stage1", "stage1": "stage1", "2": "stage2", "stage2": "stage2"}.get(
        str(args.stage).strip().lower(), None)
    if args.stage is None:
        print("error: --stage takes 1 or 2 (stage1/stage2)", file=sys.stderr)
        return 2

    try:
        params = config.load(args.definition)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    log = (lambda *a: None) if args.quiet else print
    log(f"horn-workflow {__version__}  |  {params.project}")
    log(f"definition : {params.source_path}")

    base = Path(params.source_path).resolve().parent.parent
    out_root = Path(args.out) if args.out else (base / params.output.dir)

    if args.advise:
        try:
            return run_advise_mode(args, params, out_root / "advise", log)
        except (ValueError, KeyError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    if args.sweep is not None:
        try:
            return run_sweep_mode(args, params, out_root / "sweep", log)
        except ValueError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2

    result = response.simulate(params)
    out_dir = out_root
    out_dir.mkdir(parents=True, exist_ok=True)

    log("")
    log(report.summary_text(params, result))

    written: list[Path] = []
    if params.output.csv and not args.no_csv:
        written.append(report.write_csv(result, out_dir / "curves.csv"))
    figures: list[Path] = []
    if params.output.plots and not args.no_plots:
        figures = plots.all_figures(params, result, out_dir)
        written += figures
    if params.output.report_md:
        written.append(report.write_report(params, result, out_dir / "report.md", figures))

    if args.build:
        from hornflow import build as build_mod

        log("")
        log(f"build package: slices of {args.build_slice_size:.0f} mm, wall "
            f"{args.build_wall:.0f} mm, BEM mesh at {args.build_mesh_frequency:.0f} Hz")
        b = build_mod.run(params, result, out_dir / "build",
                          slice_size_mm=args.build_slice_size, wall_mm=args.build_wall,
                          mesh_frequency=args.build_mesh_frequency, with_geo=not args.no_geo)
        for k, v in b["files"].items():
            if not isinstance(v, (float, int)):
                log(f"  {Path(str(v)).name}: {k}")
        passed = sum(1 for _, good, _ in b["verification"] if good)
        log(f"  verification: {passed}/{len(b['verification'])} checks passed")
        for name, good, detail in b["verification"]:
            if not good:
                log(f"    FAIL {name} ({detail})")
        written.append(b["sheet"])
        if b["gmsh_note"] and b["gmsh_note"] != "gmsh ok":
            log(f"  note: {b['gmsh_note']}; horn.stl and horn.msh come from the workflow "
                "itself, Gmsh is only needed for the extra .geo export")

    if args.stage == "stage2":
        from hornflow import bem as bem_mod

        log("")
        log("stage 2: writing the AKABAK inputs (lumped-element driver, BEM mesh, recipe)")
        s2 = bem_mod.write_bem_files(params, result, out_dir / "bem",
                                     mesh_frequency=args.bem_mesh_frequency,
                                     baffle_margin_mm=args.bem_baffle,
                                     platform=args.bem_platform,
                                     symmetry=args.bem_symmetry)
        for k, v in s2["files"].items():
            log(f"  {Path(v).name}: {k}")
        log(f"  mesh: {len(s2['mesh'].tris)} triangles "
            f"({s2['suggest']['n_around']} around x {s2['suggest']['n_stations']} stations), "
            f"good to {s2['suggest']['mesh_frequency_hz']:.0f} Hz")
        if s2.get("sym_mesh") is not None:
            log(f"  symmetric mesh: {len(s2['sym_mesh'].tris)} triangles - set "
                f"Global -> Dim, Sym and BEM -> Symmetry = {args.bem_symmetry}, then "
                f"Re-Open the Mesh File object (step 11 of the recipe)")
        mani = s2.get("manifest")
        if mani is not None:
            log(f"  run manifest: bem_manifest.json fingerprints the inputs; exports go to "
                f"{mani.export_dir}")
        log("  follow the RUN CHECKLIST at the top of akabak_recipe.md (tick as you go, "
            "run id + exact paths + troubleshooting), then run the import command printed "
            "at its end")
        log("  next: start AKABAK with AKABAK/akabak.sh (it is already unpacked in "
            "AKABAK/free/), load bem.msh with a Mesh File object (Scaling = 1), build the "
            "BEM tree + LEM network as in the recipe, solve, then export the spectra "
            "(VACS or Preferences-VACS -> Files) and re-run with --bem-import <folder>")
        written += [v for v in s2["files"].values()]

    if args.bem_import:
        from hornflow import bem as bem_mod
        from hornflow.physics.solvers import bem_manual, manual as manual_mod

        log("")
        log(f"stage 2 results: reading {args.bem_import}")
        bem_dir = out_dir / "bem"
        manifest = manual_mod.read_manifest(bem_dir / manual_mod.MANIFEST_NAME)
        validation = bem_manual.validate_exports(args.bem_import, manifest)
        log(f"  validated export folder ({'pass' if validation.passed else 'FAIL'}):")
        for c in validation.checks:
            log(f"    [{'pass' if c.passed else 'FAIL'}] {c.name}: {c.detail}")
        for w in validation.warnings:
            log(f"    warning: {w}")
        if not validation.passed:
            log(f"  hard validation failures: {', '.join(validation.hard_failures())}")
            log("  fix the export and re-run; the candidate is NOT marked validated")
            return 2
        try:
            res = bem_manual.import_and_validate(params, result, args.bem_import, bem_dir,
                                                 manifest=manifest,
                                                 tolerance_db=args.bem_tolerance_db)
        except (FileNotFoundError, ValueError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        imp = res["comparison"]
        parsed = imp["parsed"]
        log(f"  {imp['source']}: {len(parsed['freq'])} frequencies, "
            f"{len(parsed['curves'])} curves ({', '.join(list(parsed['curves'])[:4])}"
            f"{'...' if len(parsed['curves']) > 4 else ''})")
        log(f"  on-axis curve: {bem_mod._onaxis_curve(parsed)}")
        m = res["metrics"]
        if m:
            log(f"  vs Stage 1: mean {m['mean_diff_db']:+.2f} dB, worst "
                f"|difference| {m['worst_diff_db']:.2f} dB over {m['n_points']} points "
                f"(tolerance {m['tolerance_db']:.1f} dB)")
        log(f"  manual-solve state: {res['state']}")
        bem_report = bem_manual.validation_md(res, project=params.project)
        bem_report_path = bem_dir / "bem_manual_report.md"
        bem_report_path.write_text(bem_report, encoding="utf-8")
        written.append(bem_report_path)
        for k, v in imp["files"].items():
            log(f"  {Path(v).name}: stage 1 vs stage 2 {k}")
            written.append(v)

    log("")
    if result.notes:
        log("notes (completed automatically):")
        for n in result.notes:
            log(f"  - {n}")
    if result.warnings:
        log("warnings:")
        for w in result.warnings:
            log(f"  - {w}")
    log("")
    log(f"output directory: {out_dir}")
    for p in written:
        log(f"  {p.name}")
    log(f"done in {time.time() - t0:.2f} s")

    if args.stage == "stage1" and not args.build:
        log("")
        log("options: --build (geometry, slice stack, STL, build sheet) | "
            "--stage 2 (AKABAK inputs) | --sweep | --advise")
    return 0


if __name__ == "__main__":
    sys.exit(main())
