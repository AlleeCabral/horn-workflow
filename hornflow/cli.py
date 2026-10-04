#!/usr/bin/env python3
"""hornflow pipeline CLI - the gated, state-driven workflow.

    python3 -m hornflow.cli params/horn_jbl_1200b.yaml
    python3 -m hornflow.cli params/horn_jbl_1200b.yaml --out runs \\
        --wall-mm 18 --min-bend-radius-m 0.15 --max-fold-count 2

This is additive: the legacy ``run_workflow.py`` command is untouched and keeps
producing the same Stage-1/2 outputs.
"""

from __future__ import annotations

import argparse
import sys

from .workflow import run_pipeline


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hornflow.cli",
        description="Run the gated folded-horn design pipeline (deterministic, "
                    "state-driven, artifact-producing).")
    p.add_argument("definition", help="path to the YAML definition file")
    p.add_argument("--out", default="runs", help="run root directory (default: runs)")
    p.add_argument("--wall-mm", type=float, default=18.0, help="wall thickness [mm]")
    p.add_argument("--min-bend-radius-m", type=float, default=0.0,
                   help="minimum permitted bend radius [m]")
    p.add_argument("--max-fold-count", type=int, default=99,
                   help="maximum number of bends allowed")
    p.add_argument("--area-rms-tol", type=float, default=0.15,
                   help="area-law RMS tolerance for a fold to be valid")
    p.add_argument("--min-safe-impedance-ohm", type=float, default=None,
                   help="amplifier minimum safe load (hard gate)")
    p.add_argument("--max-external-volume-m3", type=float, default=None,
                   help="maximum external enclosure volume (hard gate)")
    p.add_argument("--bem-import", default=None, metavar="FOLDER",
                   help="validate + import AKABAK .vips spectra from FOLDER, compare with "
                        "the 1-D reference and advance the manual-solve state machine")
    p.add_argument("--bem-tolerance-db", type=float, default=6.0, metavar="dB",
                   help="max |difference| between the BEM on-axis curve and the 1-D "
                        "reference for the candidate to be BEM_VALIDATED (default 6 dB)")
    p.add_argument("--quiet", action="store_true", help="print only the summary")
    p.add_argument("--emit-ui", nargs="?", const="", default=None, metavar="RUN_DIR",
                   help="re-render the UI shell (Viewer/Workflow/Results tabs) for a run "
                        "without re-running the pipeline; with no value, the newest run "
                        "under --out")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    limits = {
        "wall_mm": args.wall_mm,
        "min_bend_radius_m": args.min_bend_radius_m,
        "max_fold_count": args.max_fold_count,
        "area_rms_tol": args.area_rms_tol,
    }
    if args.min_safe_impedance_ohm is not None:
        limits["min_safe_impedance_ohm"] = args.min_safe_impedance_ohm
    if args.max_external_volume_m3 is not None:
        limits["max_external_volume_m3"] = args.max_external_volume_m3

    progress = (lambda m: None) if args.quiet else (lambda m: print(m, flush=True))

    if args.emit_ui is not None:
        from pathlib import Path
        from .app import emit as emit_mod
        if args.emit_ui:
            newest = Path(args.emit_ui)
        else:
            root = Path(args.out)
            runs = sorted(p for p in root.iterdir()
                          if p.is_dir() and (p / "state.json").is_file()) \
                if root.is_dir() else []
            if not runs:
                print(f"no run with a state.json under {root}", file=sys.stderr)
                return 1
            newest = runs[-1]
        res = emit_mod.emit_ui_for_run(newest)
        print(f"run:      {newest.name}")
        print(f"mode:     {res['view']['mode']}")
        print(f"viewer:   {res['files']['viewer']}")
        print(f"view:     {res['files']['app_view']}")
        print("open the UI with:")
        print(f"  firefox '{res['files']['viewer'].resolve()}'")
        print(f"  # or, over http (recommended): "
              f"python3 -m http.server 8765 --directory {(newest / 'deliverables').resolve()}")
        return 0

    if args.bem_import:
        from .workflow import bem_import
        run_dir = bem_import.find_run_dir(args.bem_import)
        if run_dir is not None:
            if not args.quiet:
                print(f"resuming run: {run_dir}")
        else:
            summary = run_pipeline(args.definition, out_root=args.out,
                                   limits=limits, progress=progress)
            run_dir = summary["run_dir"]
        if not args.quiet:
            print(f"manual BEM import: {args.bem_import}")
        res = bem_import.import_into_run(run_dir, args.bem_import,
                                         tolerance_db=args.bem_tolerance_db)
        v = res["validation"]
        for c in v["checks"]:
            print(f"  [{'pass' if c['passed'] else 'FAIL'}] {c['name']}: {c['detail']}")
        for w in v["warnings"]:
            print(f"  warning: {w}")
        m = res.get("metrics")
        if m:
            print(f"  vs 1-D reference: mean {m['mean_diff_db']:+.2f} dB, "
                  f"worst {m['worst_diff_db']:.2f} dB "
                  f"(tolerance {m['tolerance_db']:.1f} dB, {m['n_points']} points)")
        print(f"  manual-solve state: {res['state']}")
        print(f"  report: {res['report']}")
        return 0 if v["passed"] else 1

    summary = run_pipeline(args.definition, out_root=args.out, limits=limits,
                           progress=progress)

    print("")
    print(f"run:        {summary['run_id']}")
    print(f"best folded:{summary['best_folded']}")
    print(f"best overall:{summary['best_overall']}")
    print(f"folds:      {summary['n_fold_candidates']} candidates")
    print(f"report:     {summary['report']}")
    print(f"viewer:     {summary['viewer']}")
    failed = [k for k, v in summary["stages"].items()
              if v.get("status") in ("failed", "blocked")]
    if failed:
        print(f"stages not passed: {', '.join(failed)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
