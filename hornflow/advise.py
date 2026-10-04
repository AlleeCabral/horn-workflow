"""Design advice: derive the geometry from a size budget instead of guessing.

Answers the two questions a builder actually has:

  * "I can go X mm deep - what mouth do I need for 60/70/80 Hz?"
  * "I want a mouth of A m^2 - how deep does the horn have to be?"

...plus "what is the lowest cut-off my depth allows?", the predicted response of
each candidate, and how much the horn beats the same driver direct-radiating.

Usage:
    python3 run_workflow.py params/horn_jbl_1200b.yaml --advise
    python3 run_workflow.py params/horn_jbl_1200b.yaml --advise \
            --advise-targets 60,62,70 --advise-depth 1200
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import config, response


# ---------------------------------------------------------------------------
#  closed-form relations between cut-off, mouth and depth (exponential flare)
#  S = St e^(mx), m = 4 pi fc/c,  rm = rt e^(mL/2),  k = 2 pi fc/c
#  =>  k*rm = (2 pi fc rt / c) * exp(2 pi fc L / c)
# ---------------------------------------------------------------------------
def k_rm_at_depth(fc: float, rt: float, depth: float, c: float = 343.0) -> float:
    """Mouth criterion k*rm that a given depth reaches for a cut-off fc."""
    return (2.0 * math.pi * fc * rt / c) * math.exp(2.0 * math.pi * fc * depth / c)


def mouth_radius_for(fc: float, k_rm: float, c: float = 343.0) -> float:
    """Mouth radius (equal-area circle) for a cut-off and a mouth criterion."""
    return k_rm * c / (2.0 * math.pi * fc)


def depth_for(fc: float, rt: float, k_rm: float, c: float = 343.0) -> float:
    """Horn depth needed for a cut-off and a mouth criterion (exponential)."""
    rm = mouth_radius_for(fc, k_rm, c)
    m = 4.0 * math.pi * fc / c
    return 2.0 * math.log(rm / rt) / m


def floor_fc(rt: float, depth: float, k_min: float = 0.7, c: float = 343.0,
             lo: float = 25.0, hi: float = 400.0) -> float:
    """Lowest cut-off that still reaches k*rm = k_min within the depth budget."""
    if k_rm_at_depth(hi, rt, depth, c) < k_min:
        return float("nan")
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if k_rm_at_depth(mid, rt, depth, c) < k_min:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def rectangle(area: float, aspect: float) -> tuple:
    """Width x height [m] of a rectangle with the given area and aspect (w/h)."""
    return (math.sqrt(area * aspect), math.sqrt(area / aspect))


@dataclass
class Candidate:
    """One proposed horn geometry (before simulating it)."""

    fc: float
    k_rm: float
    depth: float                 # [m]
    mouth_area: float            # [m^2]
    mouth_width: float           # [m]
    mouth_height: float          # [m]
    fits: bool
    note: str = ""
    result: object = None
    params: object = None
    metrics: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        return (f"fc {self.fc:.0f} Hz, mouth {self.mouth_width * 1e3:.0f} x "
                f"{self.mouth_height * 1e3:.0f} mm, depth {self.depth * 1e3:.0f} mm")


def make_candidate(fc: float, rt: float, depth_limit: float, aspect: float,
                   k_min: float, k_max: float, c: float = 343.0) -> Candidate:
    """Design the horn for one cut-off inside the depth budget."""
    k_use = min(k_rm_at_depth(fc, rt, depth_limit, c), k_max)
    depth = depth_for(fc, rt, k_use, c)
    area = math.pi * mouth_radius_for(fc, k_use, c) ** 2
    w, h = rectangle(area, aspect)
    fits = k_use >= k_min and depth <= depth_limit * 1.0001
    note = ""
    if k_use < k_min:
        note = (f"mouth would only reach k*rm = {k_use:.2f} within "
                f"{depth_limit * 1e3:.0f} mm - cut-off too low for this depth")
    elif depth > depth_limit * 1.0001:
        note = f"needs {depth * 1e3:.0f} mm of depth (budget {depth_limit * 1e3:.0f} mm)"
    return Candidate(fc=fc, k_rm=k_use, depth=depth, mouth_area=area, mouth_width=w,
                     mouth_height=h, fits=fits, note=note)


# ---------------------------------------------------------------------------
#  references: the same driver direct-radiating from the same rear chamber
# ---------------------------------------------------------------------------
def _reference_overrides(throat_radius_m: float, fc: float) -> dict:
    """A 2 mm 'horn' = a piston in a baffle = the driver direct-radiating."""
    return {
        "horn.profile": "conical",
        "horn.length": 2.0,
        "horn.mouth_radius": throat_radius_m * 1e3 * 1.0002,
        "horn.mouth_area": "auto",
        "horn.mouth_shape": "round",
        "horn.mouth_aspect": 1.0,
        "horn.coverage_angle": 1.0,
        "target.fc": fc,
    }


def _candidate_overrides(cand: Candidate, aspect: float) -> dict:
    return {
        "target.fc": cand.fc,
        "horn.length": cand.depth * 1e3,
        "horn.mouth_area": cand.mouth_area * 1e4,     # [cm^2]
        "horn.mouth_radius": "auto",
        "horn.mouth_shape": "rectangular",
        "horn.mouth_aspect": aspect,
    }


def _metrics(params, result) -> dict:
    d = result.derived
    t = params.target
    return {
        "fc_hz": d["fc_hz"],
        "k_rm": d["k_rm_at_fc"],
        "mouth_area_cm2": d["mouth_area_cm2"],
        "mouth_width_mm": d["mouth_width_mm"],
        "mouth_height_mm": d["mouth_height_mm"],
        "depth_mm": d["length_mm"],
        "envelope_m3": d["build_volume_l"] / 1000.0,
        "air_volume_l": d["horn_volume_l"],
        "area_ratio": d["area_ratio"],
        "spl_mean_db": result.band_spl(t.f_low, t.f_high),
        "spl_variation_db": result.variations_db(t.f_low, t.f_high),
        "ze_min_ohm": float(np.abs(result.Ze).min()),
        "ze_max_ohm": float(np.abs(result.Ze).max()),
        "excursion_max_mm": float(np.max(np.abs(result.excursion)) * 1e3),
    }


def run(path, targets: list | None = None, depth_limit: float = 1500.0,
        aspect: float = 1.6, k_min: float = 0.7, k_max: float = 1.0,
        out_dir=None, make_plots: bool = True, progress=None) -> dict:
    """Advise, simulate and rank; write advise.csv / advise_report.md / figures.

    ``targets``  cut-off frequencies to design for [Hz] (default: around f_low)
    ``depth_limit`` maximum horn depth [mm]
    """
    base = config.load(path)
    rt = base.horn.throat_diameter / 2.0
    c = base.simulation.c
    f_low = base.target.f_low

    if targets is None:                     # sensible defaults around the band
        targets = sorted({round(f_low * f, 1) for f in (0.8, 0.9, 1.0, 1.15)} |
                         {round(x, 1) for x in (60.0, 62.0, 70.0, 80.0) if x >= f_low * 0.7})

    depth_m = depth_limit * 1e-3
    floor = floor_fc(rt, depth_m, k_min, c)
    if not math.isnan(floor) and all(abs(t - floor) > 0.5 for t in targets):
        targets = sorted(targets + [round(floor, 1)])

    cands: list = []
    for fc in targets:
        cand = make_candidate(fc, rt, depth_m, aspect, k_min, k_max, c)
        if progress:
            progress(len(cands) + 1, len(targets) + 1, cand.label, cand.fits)
        try:
            params = config.load(path, overrides=_candidate_overrides(cand, aspect))
            result = response.simulate(params)
        except Exception as exc:                      # keep going, report it
            cand.note = f"{type(exc).__name__}: {exc}"
            cand.fits = False
        else:
            cand.params, cand.result = params, result
            cand.metrics = _metrics(params, result)
        cands.append(cand)

    # direct-radiator reference (same driver, same rear chamber)
    ref_params = config.load(path, overrides=_reference_overrides(rt, f_low))
    ref_result = response.simulate(ref_params)
    ref = {"params": ref_params, "result": ref_result, "metrics": _metrics(ref_params, ref_result)}

    out = Path(out_dir) if out_dir else (Path(path).resolve().parent.parent /
                                         base.output.dir / "advise")
    out.mkdir(parents=True, exist_ok=True)
    data = {"candidates": cands, "reference": ref, "floor_fc": floor, "targets": targets,
            "depth_limit": depth_limit, "aspect": aspect, "k_min": k_min, "k_max": k_max,
            "base": base, "out_dir": out}

    files = [write_csv(data, out / "advise.csv")]
    if make_plots:
        from . import advise_plots
        files += advise_plots.all_figures(data, out)
    files.insert(0, write_report(data, path, out / "advise_report.md", files))
    data["files"] = files
    return data


# ---------------------------------------------------------------------------
#  outputs
# ---------------------------------------------------------------------------
CSV_KEYS = ["fc_hz", "k_rm", "mouth_area_cm2", "mouth_width_mm", "mouth_height_mm",
            "depth_mm", "envelope_m3", "air_volume_l", "area_ratio", "spl_mean_db",
            "spl_variation_db", "ze_min_ohm", "ze_max_ohm", "excursion_max_mm"]


def write_csv(data: dict, path: Path) -> Path:
    path = Path(path)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["design", "fits", "note"] + CSV_KEYS)
        for c in data["candidates"]:
            w.writerow([c.label, int(c.fits), c.note] + [c.metrics.get(k, "") for k in CSV_KEYS])
        ref = data["reference"]
        w.writerow(["DIRECT RADIATOR (same driver, same rear chamber)", 1, ""]
                   + [ref["metrics"].get(k, "") for k in CSV_KEYS])
    return path


def gain_table(data: dict, cand, freqs=(50, 60, 70, 80, 100, 125, 150, 200)) -> list:
    """(f, direct dB, horn dB, gain dB) rows for a candidate."""
    if cand.result is None:
        return []
    rows = []
    ref = data["reference"]["result"]
    for f0 in freqs:
        i = int(np.argmin(abs(cand.result.f - f0)))
        j = int(np.argmin(abs(ref.f - f0)))
        rows.append((cand.result.f[i], ref.spl[j], cand.result.spl[i],
                     cand.result.spl[i] - ref.spl[j]))
    return rows


def best_candidate(data: dict):
    """The fitting candidate with the smallest in-band variation."""
    ok = [c for c in data["candidates"] if c.fits and c.result is not None]
    return min(ok, key=lambda c: c.metrics["spl_variation_db"]) if ok else None


def lowest_candidate(data: dict):
    """The fitting candidate with the lowest cut-off (most low end)."""
    ok = [c for c in data["candidates"] if c.fits and c.result is not None]
    return min(ok, key=lambda c: c.metrics["fc_hz"]) if ok else None


def write_report(data: dict, source, path: Path, files: list | None = None) -> Path:
    path = Path(path)
    base = data["base"]
    drv = base.driver
    t = base.target
    floor = data["floor_fc"]
    best = best_candidate(data)
    low = lowest_candidate(data)

    md = [
        f"# Design advice - {base.project}",
        "",
        f"definition file: `{source}`  ",
        f"driver: **{drv.name}** (Sd {drv.Sd * 1e4:.0f} cm^2, rear chamber "
        f"{drv.rear_volume * 1e6:.0f} cm^3, fs {drv.fs:.1f} Hz)  ",
        f"throat: {base.horn.throat_diameter * 1e3:.0f} mm  |  band: {t.f_low:.0f}-"
        f"{t.f_high:.0f} Hz  |  depth limit: **{data['depth_limit']:.0f} mm**  |  mouth "
        f"aspect: **{data['aspect']:.1f} : 1** (wider than tall)  |  mouth criterion "
        f"(k*rm) window: {data['k_min']:.2f}-{data['k_max']:.2f}",
        "",
        "## The short answer",
        "",
    ]
    if math.isnan(floor):
        md.append(f"* With {data['depth_limit']:.0f} mm of depth even k*rm = "
                  f"{data['k_min']:.2f} is out of reach at these cut-offs - the mouth would end "
                  f"up too small for a smooth bass horn.")
    else:
        fl = make_candidate(floor, base.horn.throat_diameter / 2.0, data["depth_limit"] * 1e-3,
                            data["aspect"], data["k_min"], data["k_max"], base.simulation.c)
        md += [f"* **The lowest cut-off your {data['depth_limit']:.0f} mm depth can support** is "
               f"**{floor:.1f} Hz** (that is where k*rm = {data['k_min']:.2f}, the paper's minimum "
               f"for a bass horn). It needs a mouth of {fl.mouth_width * 1e3:.0f} x "
               f"{fl.mouth_height * 1e3:.0f} mm ({fl.mouth_area:.2f} m2).",
               "* Lower than that means either a too-small mouth (ripple) or a deeper horn."]
    if best:
        m = best.metrics
        md += ["",
               f"* **Recommended (smoothest within your budget): {best.label}** - k*rm "
               f"{m['k_rm']:.2f}, envelope {m['envelope_m3']:.2f} m3, air inside "
               f"{m['air_volume_l']:.0f} l, in-band {m['spl_mean_db']:.1f} dB mean with "
               f"{m['spl_variation_db']:.1f} dB variation."]
    if low and low is not best:
        m = low.metrics
        md += [f"* **Most low end for the same budget: {low.label}** - k*rm {m['k_rm']:.2f}, "
               f"{m['spl_variation_db']:.1f} dB variation, envelope {m['envelope_m3']:.2f} m3."]
    md += ["", "## Every cut-off your depth budget can reach", "",
           "| cut-off fc | k*rm | mouth (rectangular) | mouth area | depth used | envelope | "
           "air volume | fits? |",
           "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for c in sorted(data["candidates"], key=lambda c: c.fc):
        flag = "yes" if c.fits else f"no - {c.note}"
        md.append(f"| {c.fc:.1f} Hz | {c.k_rm:.2f} | {c.mouth_width * 1e3:.0f} x "
                  f"{c.mouth_height * 1e3:.0f} mm | {c.mouth_area:.2f} m2 | "
                  f"{c.depth * 1e3:.0f} mm | {c.metrics.get('envelope_m3', float('nan')):.2f} m3 | "
                  f"{c.metrics.get('air_volume_l', float('nan')):.0f} l | {flag} |")
    return _report_part2(data, path, md, base, drv, ref=data["reference"], best=best,
                         files=files)


def _report_part2(data: dict, path: Path, md: list, base, drv, ref, best,
                  files: list | None = None) -> Path:
    """Second half of the advice report: gain table, ranking, derivation, limits."""
    if best and best.result is not None:
        md += ["", f"## What the horn buys you ({best.label})", "",
               f"Same driver, same {drv.rear_volume * 1e6:.0f} cm^3 rear chamber, 2.83 V, 1 m, "
               "on axis. 'direct' = the driver in that chamber radiating into the room.",
               "",
               "| frequency | direct | with horn | gain |", "| --- | --- | --- | --- |"]
        for f0, direct, horn, gain in gain_table(data, best):
            md.append(f"| {f0:.0f} Hz | {direct:.1f} dB | {horn:.1f} dB | {gain:+.1f} dB |")
        md += ["",
               f"Reference (direct radiator) in-band: {ref['metrics']['spl_mean_db']:.1f} dB mean, "
               f"{ref['metrics']['spl_variation_db']:.1f} dB variation, excursion peak "
               f"{ref['metrics']['excursion_max_mm']:.2f} mm.",
               "",
               f"That is the trade in one line: without the horn the same driver in the same "
               f"chamber is flatter ({ref['metrics']['spl_variation_db']:.1f} dB) but about "
               f"{best.metrics['spl_mean_db'] - ref['metrics']['spl_mean_db']:.0f} dB quieter. "
               f"The horn buys that output (and less cone travel); the remaining ripple can be "
               f"equalised."]

        md += ["", "## Predicted performance of the fitting designs", "",
               "| design | mean SPL | variation | excursion peak | at 100 W | impedance | "
               "air volume |",
               "| --- | --- | --- | --- | --- | --- | --- |"]
        fitting = [c for c in data["candidates"] if c.fits and c.result is not None]
        for c in sorted(fitting, key=lambda c: c.metrics["spl_variation_db"]):
            m = c.metrics
            md.append(f"| {c.label} | {m['spl_mean_db']:.1f} dB | "
                      f"{m['spl_variation_db']:.1f} dB | {m['excursion_max_mm']:.2f} mm | "
                      f"{m['excursion_max_mm'] * 7.07:.1f} mm | {m['ze_min_ohm']:.1f}-"
                      f"{m['ze_max_ohm']:.1f} ohm | {m['air_volume_l']:.0f} l |")
        md += ["",
               "(The 100 W column scales the peak excursion linearly with voltage - a rule of "
               "thumb, not a thermal or suspension limit.)"]

    md += ["",
           "## How these numbers were derived",
           "",
           "* exponential flare: `S = St exp(m x)` with `m = 4 pi fc / c`",
           "* mouth criterion: `k*rm = (2 pi fc rt / c) exp(2 pi fc L / c)` - solved for the mouth "
           "at a given depth, or for the depth at a given mouth",
           "* the mouth is emitted as a rectangle of the same area with your aspect ratio: "
           "`W = sqrt(A * aspect)`, `H = sqrt(A / aspect)`",
           "* the response comes from the Stage-1 model: 1P (Webster) horn + lumped-element "
           "driver, piston-like mouth, no diffraction",
           "",
           "## Limits",
           "",
           "* The horn is modelled as the equal-area round horn; the rectangular mouth's "
           "directivity (wide horizontally, narrower vertically) is what Stage 2 "
           "(ATH -> Gmsh -> AKABAK) measures.",
           "* Driver items marked ESTIMATE in the driver file are not measured - the low end and "
           "the rear-chamber resonance move with `fs`, `Qts` and `Vas`.",
           "* No diffraction, no losses, no room: absolute levels are approximate - comparisons, "
           "sizes and trends are solid.",
           "",
           "## Files",
           "",
           ]
    for f in (files or []):
        md.append(f"* `{Path(f).name}`")
    md += ["* `advise_report.md`", ""]
    path.write_text("\n".join(md), encoding="utf-8")
    return path



