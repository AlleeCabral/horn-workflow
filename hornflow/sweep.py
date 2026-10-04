"""Comparison (sweep) mode: run one definition file over a grid of values.

Built for the "I do not know what to build yet" question: vary the mouth size, the
horn length (optionally the profile, throat, cut-off, driver), then read one table
plus overlay curves and pick a design.

From the command line:
    python run_workflow.py params/x.yaml --sweep horn.mouth_radius=450,600,750 \
                                           --sweep horn.length=600,900,1200
    python run_workflow.py params/x.yaml --sweep        # uses the 'sweep:' block
"""

from __future__ import annotations

import csv
import itertools
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                        # noqa: E402

from . import config, report, response     # noqa: E402


def parse_sweep_arg(text: str) -> tuple:
    """'horn.mouth_radius=450,600' -> ('horn.mouth_radius', [450, 600])."""
    if "=" not in text:
        raise ValueError(f"sweep axis must look like key=v1,v2,... (got {text!r})")
    key, _, values = text.partition("=")
    vals = [config.parse_value(v) for v in values.split(",") if str(v).strip() != ""]
    if not vals:
        raise ValueError(f"sweep axis {key!r} has no values")
    return key.strip(), vals


def grid(axes: dict) -> list:
    """Full cartesian product of the axes, as a list of override dicts."""
    keys = list(axes)
    return [dict(zip(keys, combo)) for combo in itertools.product(*[axes[k] for k in keys])]


_AXIS_UNITS = {
    "horn.length": "mm",
    "horn.mouth_radius": "mm",
    "horn.mouth_area": "cm^2",
    "horn.throat_diameter": "mm",
    "horn.mouth_aspect": ":1",
    "target.fc": "Hz",
    "target.f_low": "Hz",
    "driver.rear_volume": "cm^3",
}


def _label(axes: dict, overrides: dict) -> str:
    """Human label for one grid point; constant axes are not mentioned."""
    parts = []
    for key in axes:
        if len(axes[key]) < 2:                  # not really swept
            continue
        name = key.split(".")[-1].replace("_", " ")
        unit = _AXIS_UNITS.get(key, "")
        value = overrides[key]
        parts.append(f"{name} {value}" + (f" {unit}" if unit else ""))
    return ", ".join(parts) if parts else "(single design)"


@dataclass
class SweepRow:
    """One design in the comparison."""

    label: str
    overrides: dict
    ok: bool = True
    error: str = ""
    result: object = None
    params: object = None
    metrics: dict = field(default_factory=dict)

    @property
    def acceptable(self) -> bool:
        """Meets the paper's mouth criterion and produced no model warnings."""
        m = self.metrics
        return self.ok and m.get("k_rm", 0.0) >= 0.7


def _metrics(r, params) -> dict:
    d = r.derived
    t = params.target
    c = params.simulation.c
    return {
        "fc_hz": d["fc_hz"],
        "mouth_diameter_mm": d["mouth_diameter_mm"],
        "mouth_width_mm": d["mouth_width_mm"],
        "mouth_height_mm": d["mouth_height_mm"],
        "mouth_shape": d["mouth_shape"],
        "length_mm": d["length_mm"],
        "envelope_m3": d["build_volume_l"] / 1000.0,
        "air_volume_l": d["horn_volume_l"],
        "area_ratio": d["area_ratio"],
        "k_rm": d["k_rm_at_fc"],
        "k_rm_band": 2.0 * np.pi * t.f_low / c * r.design.rm,
        "k_rt_at_fc": d["k_rt_at_fc"],
        "spl_mean_db": r.band_spl(t.f_low, t.f_high),
        "spl_variation_db": r.variations_db(t.f_low, t.f_high),
        "ze_min_ohm": float(np.abs(r.Ze).min()),
        "ze_max_ohm": float(np.abs(r.Ze).max()),
        "excursion_max_mm": float(np.max(np.abs(r.excursion)) * 1e3),
        "warnings": len(r.warnings),
    }


def run(path, axes: dict, out_dir, make_plots: bool = True, progress=None) -> dict:
    """Run every combination, write the comparison files, return the rows."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    combos = grid(axes)
    rows: list = []
    for i, overrides in enumerate(combos, start=1):
        label = _label(axes, overrides)
        row = SweepRow(label=label, overrides=dict(overrides))
        try:
            params = config.load(path, overrides=overrides)
            result = response.simulate(params)
        except Exception as exc:                       # keep going: report the failure
            row.ok = False
            row.error = f"{type(exc).__name__}: {exc}"
        else:
            row.params, row.result = params, result
            row.metrics = _metrics(result, params)
        rows.append(row)
        if progress:
            progress(i, len(combos), row)

    files = []
    files.append(write_csv(rows, out / "sweep.csv"))
    if make_plots:
        for p in (spl_overlay, impedance_overlay, metric_map):
            f = p(rows, axes, out)
            if f is not None:
                files.append(f)
    files.insert(1, write_report(rows, axes, path, out / "sweep_report.md", files))
    return {"rows": rows, "axes": axes, "out_dir": out, "files": files}


# ---------------------------------------------------------------------------
#  outputs
# ---------------------------------------------------------------------------
METRIC_KEYS = ["fc_hz", "mouth_diameter_mm", "mouth_width_mm", "mouth_height_mm",
               "mouth_shape", "length_mm", "envelope_m3", "air_volume_l", "area_ratio", "k_rm",
               "k_rm_band", "k_rt_at_fc", "spl_mean_db", "spl_variation_db", "ze_min_ohm",
               "ze_max_ohm", "excursion_max_mm", "warnings"]


def mouth_text(m: dict) -> str:
    """Mouth dimension as text: 'W x H' for a rectangle, 'D dia' for a circle."""
    if m.get("mouth_shape") == "rectangular":
        return f"{m['mouth_width_mm']:.0f}x{m['mouth_height_mm']:.0f}"
    return f"{m['mouth_diameter_mm']:.0f} dia"


def write_csv(rows: list, path: Path) -> Path:
    axis_keys = list(rows[0].overrides) if rows else []
    header = ["label", "ok", "error"] + [f"set:{k}" for k in axis_keys] + METRIC_KEYS
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in rows:
            m = r.metrics
            w.writerow([r.label, int(r.ok), r.error]
                       + [r.overrides.get(k, "") for k in axis_keys]
                       + [m.get(k, "") for k in METRIC_KEYS])
    return path


def shortlist(rows: list) -> dict:
    """Four plain-language shortlists: flattest, smallest good enough, deepest, in-band."""
    ok = [r for r in rows if r.ok]
    out = {"flattest": None, "compact": None, "lowest_fc": None, "best_in_band": None,
           "f_low": None}
    if not ok:
        return out
    out["flattest"] = min(ok, key=lambda r: r.metrics["spl_variation_db"])
    best_var = out["flattest"].metrics["spl_variation_db"]
    good = [r for r in ok if r.metrics["spl_variation_db"] <= best_var + 2.0]
    out["compact"] = min(good, key=lambda r: r.metrics["envelope_m3"])
    out["lowest_fc"] = min(ok, key=lambda r: r.metrics["fc_hz"])
    f_low = getattr(getattr(ok[0].params, "target", None), "f_low", None)
    out["f_low"] = f_low
    if f_low:
        usable = [r for r in ok if r.metrics["fc_hz"] <= f_low]
        if usable:
            out["best_in_band"] = min(usable, key=lambda r: r.metrics["spl_variation_db"])
    return out


def _effect(rows: list, axis: str) -> str:
    """Describe how one swept axis moves the in-band variation."""
    vals = sorted({r.overrides.get(axis) for r in rows if r.ok and axis in r.overrides})
    if len(vals) < 2 or not all(isinstance(v, (int, float)) for v in vals):
        return ""
    means = []
    for v in vals:
        sel = [r.metrics["spl_variation_db"] for r in rows
               if r.ok and r.overrides.get(axis) == v and "spl_variation_db" in r.metrics]
        if sel:
            means.append((v, float(np.mean(sel))))
    if len(means) < 2:
        return ""
    first, last = means[0], means[-1]
    name = axis.split(".")[-1]
    direction = "larger" if last[0] > first[0] else "smaller"
    verdict = "flatter (better)" if last[1] < first[1] else "less flat (worse)"
    monotonic = all(means[i][1] <= means[i + 1][1] for i in range(len(means) - 1)) or \
                all(means[i][1] >= means[i + 1][1] for i in range(len(means) - 1))
    note = "" if monotonic else " (not a straight line - the middle values differ)"
    return (f"`{name}` {first[0]} -> {last[0]}: average in-band variation "
            f"{first[1]:.1f} dB -> {last[1]:.1f} dB, so a {direction} {name} gives a "
            f"{verdict} response{note}")


def write_report(rows: list, axes: dict, source, path: Path, files: list | None = None) -> Path:
    path = Path(path)
    sl = shortlist(rows)
    ok = [r for r in rows if r.ok]
    failed = [r for r in rows if not r.ok]
    base = ok[0].params if ok else None

    md = [
        f"# Comparison report - {getattr(base, 'project', 'horn sweep')}",
        "",
        f"definition file: `{source}`  ",
        "axes: " + ", ".join(f"`{k}` = {v}" for k, v in axes.items()) + "  ",
        f"designs run: {len(rows)} ({len(ok)} ok, {len(failed)} failed)  ",
        "",
        "## How to read this",
        "",
        "Every row is one horn you could build. The columns that matter when you are choosing:",
        "",
        "* **mouth diameter / depth** - the size of the thing you have to fit somewhere.",
        "* **fc (cut-off)** - the frequency where the horn stops helping. Keep it at or below the",
        "  bottom of the band you care about.",
        "* **variation** - how much the on-axis response wobbles across the band (peak to peak).",
        "  Smaller is smoother; a few dB is normal, 10+ dB means equalisation later.",
        "* **k·rm** - the paper's mouth criterion: 0.7-1 is the recommended range for bass horns,",
        "  below 0.7 the response tends to be peaky. Two columns are shown: at the cut-off, and at",
        "  the bottom of your band - the second one is the one that matters for what you will hear.",
        "* **excursion** - diaphragm travel at the drive level; compare with the driver's Xmax.",
        "* **(!)** after a cut-off frequency means the cut-off is *inside* your band - such a horn "
        "starts rolling off before the top of the band and usually shows the ripple.",
        "",
        "## Shortlists",
        "",
    ]
    if sl["flattest"]:
        m = sl["flattest"].metrics
        md += [f"* **Smoothest in band**: {sl['flattest'].label} - {m['spl_variation_db']:.1f} dB "
               f"variation, cut-off {m['fc_hz']:.0f} Hz, mouth {m['mouth_diameter_mm']:.0f} mm, "
               f"depth {m['length_mm']:.0f} mm, envelope {m['envelope_m3']:.2f} m3.",
               f"* **Smallest that is nearly as smooth** (within 2 dB of the best): "
               f"{sl['compact'].label} - {sl['compact'].metrics['spl_variation_db']:.1f} dB "
               f"variation, envelope {sl['compact'].metrics['envelope_m3']:.2f} m3.",
               f"* **Deepest low end** (lowest cut-off): {sl['lowest_fc'].label} - cut-off "
               f"{sl['lowest_fc'].metrics['fc_hz']:.0f} Hz, envelope "
               f"{sl['lowest_fc'].metrics['envelope_m3']:.2f} m3."]
        if sl["best_in_band"]:
            b = sl["best_in_band"]
            md += [f"* **Best one whose cut-off is below your {sl['f_low']:.0f} Hz band start** "
                   f"(this is the one that actually covers your band): {b.label} - cut-off "
                   f"{b.metrics['fc_hz']:.0f} Hz, {b.metrics['spl_variation_db']:.1f} dB "
                   f"variation, envelope {b.metrics['envelope_m3']:.2f} m3."]
        else:
            md += [f"* **None of these designs has its cut-off at or below {sl['f_low']:.0f} Hz** - "
                   f"they are all too small/short for that band; see the size table below."]
        md += [""]
    else:
        md += ["_no design completed successfully - see the failures below_", ""]

    trends = [t for t in (_effect(rows, k) for k in axes) if t]
    if trends:
        md += ["## What the sweep says about the trade-offs", ""]
        md += [f"* {t}" for t in trends]
        f_low = sl.get("f_low")
        if f_low:
            below = [r.metrics["spl_variation_db"] for r in ok if r.metrics["fc_hz"] <= f_low]
            inside = [r.metrics["spl_variation_db"] for r in ok if r.metrics["fc_hz"] > f_low]
            if below and inside:
                md += [f"* Where the cut-off lands matters more than any single dimension: designs "
                       f"whose cut-off is at or below {f_low:.0f} Hz average "
                       f"{float(np.mean(below)):.1f} dB of variation, designs whose cut-off sits "
                       f"inside the band average {float(np.mean(inside)):.1f} dB."]
            fc_auto = ok[0].params.target.fc is None
            if fc_auto:
                md += ["* Read this carefully: with `target.fc: auto` the cut-off is *derived* from "
                       "the mouth radius and the length, so changing one of them also moves the "
                       "cut-off. To isolate the effect of the mouth alone, set `target.fc` to a "
                       "number and leave `horn.length: auto`."]
        md += ["",
               "Rule of thumb: a bigger mouth buys smoothness (the paper's k*rm criterion) and more "
               "depth buys a lower cut-off - both cost space. If you can only afford one, prefer "
               "whichever puts the cut-off below your band.",
               ""]

    md += [
        "## All designs (sorted by in-band variation)",
        "",
        "| design | mouth [mm] | depth [mm] | fc [Hz] | k·rm @fc | k·rm @band | "
        "variation [dB] | mean SPL [dB] | excursion [mm] | envelope [m3] |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in sorted(ok, key=lambda r: r.metrics["spl_variation_db"]):
        m = r.metrics
        flag = " (!)" if (sl.get("f_low") and m["fc_hz"] > sl["f_low"]) else ""
        md.append(f"| {r.label} | {mouth_text(m)} | {m['length_mm']:.0f} | "
                  f"{m['fc_hz']:.0f}{flag} | {m['k_rm']:.2f} | {m['k_rm_band']:.2f} | "
                  f"{m['spl_variation_db']:.1f} | {m['spl_mean_db']:.1f} | "
                  f"{m['excursion_max_mm']:.2f} | {m['envelope_m3']:.2f} |")
    md += [""]

    if failed:
        md += ["## Designs that failed", ""]
        md += [f"* {r.label}: {r.error}" for r in failed]
        md += [""]

    if base is not None:
        rows_size = report.size_requirement_rows(base, ok[0].result)
        if rows_size:
            md += ["## How big the horn has to be for a given cut-off (this profile/throat)",
                   "",
                   "| cut-off fc [Hz] | k·rm | mouth diameter [mm] | depth [mm] | envelope [m3] |",
                   "| --- | --- | --- | --- | --- |"]
            for row in rows_size:
                md.append(f"| {row['fc_hz']:.0f} | {row['k_rm']:.1f} | "
                          f"{row['mouth_diameter_mm']:.0f} | {row['length_mm']:.0f} | "
                          f"{row['bounding_volume_l'] / 1000:.2f} |")
            md += [""]

    md += ["## Files", ""]
    files = list(files or [])
    for f in files + [path]:
        md.append(f"* `{Path(f).name}`")
    md += ["",
           "## Limits of this comparison",
           "",
           "These results come from the Stage 1 model: one-dimensional (plane wave) horn theory "
           "with a lumped-element driver, a piston-like mouth and no diffraction. It is very "
           "good for comparing shapes and sizes quickly, but absolute levels, off-axis "
           "behaviour and fine detail need Stage 2 (ATH -> Gmsh -> AKABAK BEM) for the design "
           "you finally pick.",
           ""]
    path.write_text("\n".join(md), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
#  figures
# ---------------------------------------------------------------------------
def _tag(row: SweepRow) -> str:
    m = row.metrics
    return (f"{row.label} - fc {m['fc_hz']:.0f} Hz, mouth {mouth_text(m)} mm, "
            f"var {m['spl_variation_db']:.1f} dB, {m['envelope_m3']:.2f} m3")


def spl_overlay(rows: list, axes: dict, out_dir: Path):
    ok = [r for r in rows if r.ok]
    if not ok:
        return None
    sl = shortlist(rows)
    starred = {id(sl["flattest"]), id(sl["compact"]), id(sl["lowest_fc"])}
    fig, ax = plt.subplots(figsize=(9.5, 5.2), dpi=130)
    cmap = plt.get_cmap("viridis")
    for i, r in enumerate(sorted(ok, key=lambda x: x.metrics["spl_variation_db"])):
        best = id(r) in starred
        ax.semilogx(r.result.f, r.result.spl, linewidth=2.0 if best else 1.0,
                    color=cmap(i / max(len(ok) - 1, 1)),
                    label=("* " if best else "") + _tag(r))
    base = ok[0].params
    ax.axvspan(base.target.f_low, base.target.f_high, color="tab:green", alpha=0.08,
               label=f"target band {base.target.f_low:.0f}-{base.target.f_high:.0f} Hz")
    ax.set_xlabel("frequency [Hz]")
    ax.set_ylabel("on-axis SPL [dB]")
    ax.set_title("Comparison: on-axis response of every design (* = shortlisted)", fontsize=10)
    ax.grid(alpha=0.3, linestyle=":")
    ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    p = out_dir / "sweep_spl.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def impedance_overlay(rows: list, axes: dict, out_dir: Path):
    ok = [r for r in rows if r.ok]
    if not ok:
        return None
    fig, ax = plt.subplots(figsize=(9.5, 5.2), dpi=130)
    cmap = plt.get_cmap("plasma")
    for i, r in enumerate(sorted(ok, key=lambda x: x.metrics["fc_hz"])):
        rc_st = r.result.design.rho * r.result.design.c / r.result.design.St
        ax.semilogx(r.result.f, r.result.Zt.real / rc_st, linewidth=1.0,
                    color=cmap(i / max(len(ok) - 1, 1)), label=_tag(r))
    ax.axhline(1.0, color="k", linewidth=0.6, linestyle=":")
    ax.set_xlabel("frequency [Hz]")
    ax.set_ylabel("Re(Zt) / (rho c / St)")
    ax.set_title("Comparison: how hard the horn loads the driver (normalized resistance)",
                 fontsize=10)
    ax.grid(alpha=0.3, linestyle=":")
    ax.legend(fontsize=7)
    fig.tight_layout()
    p = out_dir / "sweep_impedance.png"
    fig.savefig(p)
    plt.close(fig)
    return p


def metric_map(rows: list, axes: dict, out_dir: Path):
    """Heat map of variation and cut-off over a 2D numeric grid (if there is one)."""
    numeric = [k for k in axes if all(isinstance(v, (int, float)) for v in axes[k])]
    if len(numeric) != 2 or not all(r.ok for r in rows):
        return None
    kx, ky = numeric
    xs, ys = sorted({r.overrides[kx] for r in rows}), sorted({r.overrides[ky] for r in rows})
    var = np.full((len(ys), len(xs)), np.nan)
    fc = np.full((len(ys), len(xs)), np.nan)
    for r in rows:
        i = ys.index(r.overrides[ky])
        j = xs.index(r.overrides[kx])
        var[i, j] = r.metrics["spl_variation_db"]
        fc[i, j] = r.metrics["fc_hz"]
    fig, axes_ = plt.subplots(1, 2, figsize=(11.0, 4.4), dpi=130)
    for ax, data, title, unit in ((axes_[0], var, "in-band variation", "dB"),
                                  (axes_[1], fc, "flare cut-off", "Hz")):
        im = ax.imshow(data, origin="lower", aspect="auto", cmap="magma_r")
        ax.set_xticks(range(len(xs)), [f"{v:g}" for v in xs])
        ax.set_yticks(range(len(ys)), [f"{v:g}" for v in ys])
        ax.set_xlabel(kx.split(".")[-1])
        ax.set_ylabel(ky.split(".")[-1])
        ax.set_title(f"{title} [{unit}]", fontsize=10)
        for i in range(len(ys)):
            for j in range(len(xs)):
                if np.isfinite(data[i, j]):
                    ax.text(j, i, f"{data[i, j]:.1f}", ha="center", va="center", fontsize=7)
        fig.colorbar(im, ax=ax)
    fig.tight_layout()
    p = out_dir / "sweep_map.png"
    fig.savefig(p)
    plt.close(fig)
    return p

