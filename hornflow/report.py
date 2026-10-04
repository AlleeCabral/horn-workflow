"""Stage 1 reporting: CSV curves + a Markdown summary of the design and checks."""

from __future__ import annotations

import datetime as _dt
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from . import theory
from .config import Params
from .domain import excursion
from .response import Result


def write_csv(r: Result, path: str | Path) -> Path:
    """Write all curves to a single CSV (one row per frequency).

    Excursion is exported **twice on purpose** - ``excursion_rms_mm`` is what the
    solver computes (rms drive convention) and ``excursion_peak_mm`` is the
    one-way peak, ``sqrt(2) * rms``.  Named separately so no reader has to guess
    which convention a column holds; see ``hornflow.domain.excursion``.
    """
    from .domain.excursion import RMS_TO_PEAK

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    x_rms_mm = np.abs(r.excursion) * 1e3
    data = np.column_stack([
        r.f,
        np.abs(r.Zt), r.Zt.real, r.Zt.imag,
        np.abs(r.Ze), np.angle(r.Ze, deg=True), np.abs(r.current),
        x_rms_mm, x_rms_mm * RMS_TO_PEAK,
        np.abs(r.p_axis), r.spl, r.di,
    ])
    np.savetxt(path, data, delimiter=",", header=CURVES_HEADER, comments="",
               fmt="%.6g")
    return path


# --------------------------------------------------------------------------- #
#  curves.csv schema (v2) and the legacy reader
# --------------------------------------------------------------------------- #
# v2 adds ``excursion_peak_mm`` after ``excursion_rms_mm``.
CURVES_HEADER = ("freq_hz,Zt_abs,Zt_re,Zt_im,Ze_abs,Ze_phase_deg,I_abs,"
                 "excursion_rms_mm,excursion_peak_mm,p_abs_Pa,spl_db,di_db")
# v1 (<= 2026-10-03) called the rms column ``excursion_peak_mm``.  The *values*
# were always rms, so a v1 file is migrated by renaming that column and deriving
# the peak one - the numbers are never reinterpreted.
CURVES_HEADER_V1 = ("freq_hz,Zt_abs,Zt_re,Zt_im,Ze_abs,Ze_phase_deg,I_abs,"
                    "excursion_peak_mm,p_abs_Pa,spl_db,di_db")
CURVES_SCHEMA_V1 = "1"
CURVES_SCHEMA = "2"


@dataclass
class CurveTable:
    """A parsed curves CSV, with the schema it came from and any migration note."""

    schema: str
    columns: dict
    migrated_from: str | None = None
    notes: list = field(default_factory=list)

    def __getitem__(self, name):
        return self.columns[name]

    def __contains__(self, name) -> bool:
        return name in self.columns

    def excursion_summary(self, **kw):
        """Band summary using the canonical rms column of this table."""
        from .domain.excursion import summarize

        return summarize(self.columns["excursion_rms_mm"] / 1e3,
                         self.columns["freq_hz"], **kw)


def _parse_curves(path: str | Path) -> tuple:
    path = Path(path)
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        lines = fh.read().splitlines()
    if not lines:
        raise ValueError(f"{path}: empty curves file")
    names = [h.strip() for h in lines[0].split(",")]
    rows = [ln.split(",") for ln in lines[1:] if ln.strip()]
    return names, rows


def read_csv(path: str | Path) -> CurveTable:
    """Read a curves CSV, honouring both schema versions.

    v1 files (``excursion_peak_mm`` holding rms values) are migrated *in memory*
    with an explicit note - the bytes on disk are never rewritten, and a v1 file
    is never silently treated as if its excursion column were peak.
    """
    from .domain.excursion import RMS_TO_PEAK

    names, rows = _parse_curves(path)
    cols = {n: np.array([float(v) for v in r], dtype=float)
            for n, r in zip(names, zip(*rows))} if rows else {n: np.array([]) for n in names}

    if "excursion_rms_mm" in names and "excursion_peak_mm" in names:
        return CurveTable(schema=CURVES_SCHEMA, columns=cols)

    if "excursion_peak_mm" in names:
        # v1: the column is really rms.
        cols["excursion_rms_mm"] = cols["excursion_peak_mm"]
        cols["excursion_peak_mm"] = cols["excursion_rms_mm"] * RMS_TO_PEAK
        return CurveTable(
            schema=CURVES_SCHEMA_V1, columns=cols, migrated_from=CURVES_SCHEMA_V1,
            notes=["v1 curves file: the column named 'excursion_peak_mm' held rms "
                   "displacement (solver drive convention is volts rms). Renamed to "
                   "'excursion_rms_mm' in memory and 'excursion_peak_mm' derived as "
                   "sqrt(2) x rms. Values untouched."])

    raise ValueError(
        f"{path}: unrecognised curves header {names!r}; expected "
        f"{CURVES_SCHEMA_V1!r} or {CURVES_SCHEMA!r}")


def guidance_lines(params: Params, r: Result) -> list:
    """Plain-language advice: what the numbers mean and which knob to turn.

    Written for someone who is not a loudspeaker engineer: every bullet says what
    the design does now, whether that is good or bad, and what to change.
    """
    d = r.derived
    t = params.target
    out = []

    # ---- low frequency extension -------------------------------------------------
    if d["fc_hz"] > t.f_low * 1.10:
        need = theory.size_requirements(r.design.rt, [t.f_low], [t.krm_target],
                                        c=params.simulation.c, T=r.design.T,
                                        profile=r.design.profile)
        if need and need[0]["length_mm"] == need[0]["length_mm"]:      # not NaN
            out.append(
                f"Low end: the flare cuts off at {d['fc_hz']:.0f} Hz, which is above your "
                f"{t.f_low:.0f} Hz target. Below the cut-off a horn stops helping, so expect "
                f"weak output there. To reach {t.f_low:.0f} Hz with this profile and throat you "
                f"need at least a {need[0]['mouth_diameter_mm']:.0f} mm wide mouth and "
                f"{need[0]['length_mm']:.0f} mm of depth (envelope "
                f"{need[0]['bounding_volume_l'] / 1000:.2f} m3)."
            )
        else:
            out.append(
                f"Low end: the flare cuts off at {d['fc_hz']:.0f} Hz, above your "
                f"{t.f_low:.0f} Hz target; for this profile family the cut-off is not set by a "
                f"flare, so lower target.fc or reduce the coverage angle instead."
            )
    elif d["fc_hz"] < t.f_low * 0.85:
        out.append(
            f"Low end: the flare cuts off at {d['fc_hz']:.0f} Hz, comfortably below your "
            f"{t.f_low:.0f} Hz target - the horn works in its useful range. This is the safe "
            f"side of the trade-off, and it costs size (see below)."
        )
    else:
        out.append(
            f"Low end: the flare cuts off at {d['fc_hz']:.0f} Hz, right at the bottom of your "
            f"{t.f_low:.0f}-{t.f_high:.0f} Hz band. That is the classic choice: the horn loads "
            f"the driver down to the cut-off, below it the output falls away."
        )

    # ---- mouth size (paper's k*rm criterion) -------------------------------------
    krm = d["k_rm_at_fc"]
    if krm < 0.7:
        out.append(
            f"Mouth size: k*rm = {krm:.2f} at the cut-off - the opening is small compared with "
            f"the wavelength there, which the paper associates with a rippled, peaky response "
            f"(it recommends 0.7-1 for bass horns, >= 1 for midrange/tweeter). Try a larger "
            f"mouth_radius, or accept the ripple."
        )
    elif krm < 1.0:
        out.append(
            f"Mouth size: k*rm = {krm:.2f} at the cut-off, inside the paper's 0.7-1 range for "
            f"bass horns - a reasonable compromise between smoothness and box size. Pushing "
            f"towards k*rm = 1 smooths the response further and grows the box."
        )
    else:
        out.append(
            f"Mouth size: k*rm = {krm:.2f} at the cut-off, at or above the paper's "
            f"recommendation - good termination and smooth loading, larger box."
        )

    # ---- flatness across the band -----------------------------------------------
    var = r.variations_db(t.f_low, t.f_high)
    mean = r.band_spl(t.f_low, t.f_high)
    if var <= 6.0:
        out.append(
            f"Flatness: the on-axis response varies {var:.1f} dB across {t.f_low:.0f}-"
            f"{t.f_high:.0f} Hz (average {mean:.1f} dB at {params.simulation.voltage:.2f} V / "
            f"{params.simulation.observation_distance:g} m). That is a usable horn response."
        )
    elif var <= 12.0:
        out.append(
            f"Flatness: {var:.1f} dB of variation across {t.f_low:.0f}-{t.f_high:.0f} Hz "
            f"(average {mean:.1f} dB). Workable, but expect to need equalisation. Levers in "
            f"order of effect: mouth size, horn length (cut-off), rear chamber volume, then the "
            f"driver itself."
        )
    else:
        out.append(
            f"Flatness: {var:.1f} dB of variation across {t.f_low:.0f}-{t.f_high:.0f} Hz "
            f"(average {mean:.1f} dB) - that is a lot. Use the sweep mode and pick a design "
            f"with a bigger mouth and/or a lower cut-off before building anything."
        )

    # ---- the rear chamber the driver actually sits in ---------------------------
    fb, qtc = d.get("box_resonance_hz"), d.get("box_Qtc")
    if fb and qtc:
        if qtc <= 0.8:
            verdict = "well damped, no bump"
        elif qtc <= 1.1:
            verdict = "a mild bump of about a decibel at that frequency"
        else:
            verdict = "a noticeable peak - expect some boom there"
        out.append(
            f"Rear chamber: your sealed box puts the driver's own resonance at {fb:.0f} Hz with "
            f"Qtc {qtc:.2f} ({verdict}). Below that frequency neither the box nor the horn helps "
            f"the driver, so that is the real bottom end of this system; above it the horn takes "
            f"over."
        )

    # ---- model validity ----------------------------------------------------------
    if d["k_rt_at_fc"] > 0.5:
        out.append(
            f"Model limit: the throat is large (k*rt = {d['k_rt_at_fc']:.2f} at the cut-off), so "
            f"the 1D horn model used here is only a rough guide - real 3D behaviour and "
            f"diffraction will differ. That is what Stage 2 (AKABAK, BEM) is for."
        )

    # ---- excursion ---------------------------------------------------------------
    # Both conventions are stated explicitly.  The *peak* value is what must be
    # compared with Xmax, which the data sheet gives as one-way peak travel.
    xr = np.abs(r.excursion)
    esum = excursion.summarize(xr, r.f,
                               drive_voltage_vrms=params.simulation.voltage,
                               re_ohm=params.driver.Re,
                               xmax_m=params.driver.Xmax,
                               xmax_convention=getattr(params.driver,
                                                       "Xmax_convention", None))
    x_rms = esum.rms_max_m * 1e3
    x_peak = esum.peak_max_m * 1e3
    f_x = esum.f_at_max_hz
    con = excursion.convention_label(getattr(params.driver, "Xmax_convention", None))
    if esum.has_xmax:
        out.append(
            f"Excursion: {x_rms:.2f} mm rms / {x_peak:.2f} mm one-way peak at "
            f"{f_x:.0f} Hz with {params.simulation.voltage:.2f} V rms - the peak "
            f"travel is {esum.peak_used_pct:.0f} % of the driver's "
            f"{esum.xmax_one_way_peak_m * 1e3:.1f} mm Xmax ({con}). "
            + excursion_power_text(esum)
        )
    else:
        out.append(
            f"Excursion: {x_rms:.2f} mm rms / {x_peak:.2f} mm one-way peak at "
            f"{f_x:.0f} Hz with {params.simulation.voltage:.2f} V rms. Compare the "
            f"**peak** figure with the driver's Xmax (one-way peak) - below the "
            f"cut-off excursion grows quickly because the horn no longer loads the "
            f"diaphragm. (Add 'Xmax: <mm>' to the driver file to have this checked "
            f"automatically.)"
        )

    # ---- what it will look like --------------------------------------------------
    w, ht, dep = d["build_width_mm"], d["build_height_mm"], d["build_depth_mm"]
    shape = ("rectangular" if d["mouth_shape"] == "rectangular" else "round")
    out.append(
        f"What you would build: a {shape} mouth about {w:.0f} x {ht:.0f} mm, {dep:.0f} mm deep, "
        f"envelope {w / 1000:.2f} x {ht / 1000:.2f} x {dep / 1000:.2f} m "
        f"(~{d['build_volume_l'] / 1000:.2f} m3 outside, about {d['horn_volume_l']:.0f} litres of "
        f"air inside)."
    )
    if d["mouth_shape"] == "rectangular":
        out.append(
            "Mouth shape: the low-frequency model uses the equal-area round equivalent "
            f"({d['mouth_diameter_mm']:.0f} mm dia), which is accurate for loading and on-axis "
            "response; the rectangular shape mainly shapes the horizontal/vertical coverage, and "
            "that is what the 3D solve in Stage 2 measures. Run with --build to get the actual "
            "outline (it is slightly wider than the nominal rectangle so that it encloses the "
            "same area with soft corners)."
        )
    return out


def excursion_power_text(esum: excursion.ExcursionSummary) -> str:
    """Where the diaphragm would hit Xmax, given that excursion scales with voltage.

    Takes the *summary* rather than raw arrays so the like-for-like convention
    (peak travel vs one-way peak Xmax) is applied in exactly one place.  Before
    2026-10-04 this compared rms travel with a peak Xmax and so reported the
    drive voltage at which Xmax is reached as ~sqrt(2) too high, and the power as
    twice too high.
    """
    if not esum.has_xmax or esum.peak_max_m <= 0.0:
        return "Excursion is negligible at this drive level."
    v_at = esum.voltage_vrms_at_xmax
    p_at = esum.power_w_at_xmax
    headroom = 20.0 * math.log10(
        max((v_at or 0.0) / esum.drive_voltage_vrms, 1e-6)) if v_at else float("inf")
    return (
        f"Excursion scales with voltage, so {esum.xmax_one_way_peak_m * 1e3:.1f} mm "
        f"peak travel would be reached at about {v_at:.0f} V rms "
        f"(~{p_at:.0f} W into the {esum.re_ohm:.1f} ohm coil) at "
        f"{esum.f_at_max_hz:.0f} Hz. This drive level is {esum.drive_power_w:.1f} W, "
        f"so you have roughly {headroom:.0f} dB of travel headroom; below the cut-off "
        f"excursion grows quickly because the horn stops loading the diaphragm, so "
        f"high-pass the signal there if you plan to use that power."
    )


def size_requirement_rows(params: Params, r: Result) -> list:
    """Table: the mouth/length needed to reach a range of cut-off frequencies."""
    if r.design.profile not in ("exponential", "hyperbolic", "conical", "os"):
        return []
    return theory.size_requirements(r.design.rt, [60.0, 80.0, 100.0, 125.0, 160.0, 200.0],
                                    [0.7, 1.0], c=params.simulation.c, T=r.design.T,
                                    profile=r.design.profile)


def _row(label: str, value, unit: str = "", note: str = "") -> str:
    if isinstance(value, float):
        value = f"{value:,.4g}"
    return f"| {label} | {value} | {unit} | {note} |"


def summary_text(params: Params, r: Result) -> str:
    """Human readable design summary (also used by the CLI)."""
    d = r.derived
    t = params.target
    lines = [
        f"horn profile        : {r.design.profile}"
        + (f" (T = {r.design.T:g})" if r.design.profile == "hyperbolic" else ""),
        f"throat radius       : {d['throat_radius_mm']:.1f} mm ({d['throat_area_cm2']:.0f} cm^2)",
        f"mouth               : {d['mouth_width_mm']:.0f} x {d['mouth_height_mm']:.0f} mm "
        f"{d['mouth_shape']} ({d['mouth_area_cm2']:.0f} cm^2, equal-area dia "
        f"{d['mouth_diameter_mm']:.0f} mm)",
        f"horn length         : {d['length_mm']:.0f} mm, area ratio {d['area_ratio']:.1f}",
        f"flare / cut-off     : m = {d['flare_m_1_per_m']:.3f} 1/m, fc = {d['fc_hz']:.0f} Hz, "
        f"x0 = {d['flare_x0_mm']:.0f} mm",
        f"mouth criterion     : k*rm = {d['k_rm_at_fc']:.2f} at fc (target "
        f"{d['k_rm_target']:.2f}; paper: 0.7-1 bass, >= 1 mid/tweeter)",
        f"1P validity         : k*rt = 1 at {d['f_1P_validity_hz']:.0f} Hz; "
        f"k*rt = {d['k_rt_at_fc']:.3f} at fc; k*rm = {d['mouth_ka_at_f_high']:.2f} at "
        f"{t.f_high:.0f} Hz",
        f"driver              : {params.driver.name}, Sd = {d['driver_Sd_cm2']:.0f} cm^2, "
        f"fs = {d['driver_fs_hz']:.1f} Hz, Sd/St = {d['compression_ratio_Sd_St']:.2f}",
        f"driver T/S          : Qms {d['driver_Qms']:.2f}, Qes {d['driver_Qes']:.2f}, "
        f"Qts {d['driver_Qts']:.2f}, Vas {d['driver_Vas_l']:.0f} l",
        f"sealed rear chamber : resonance {d['box_resonance_hz']:.1f} Hz, "
        f"Qtc {d['box_Qtc']:.2f} (Vas/Vb = {d['box_alpha']:.2f})",
        f"simulated band      : {t.f_low:.0f}-{t.f_high:.0f} Hz, {params.simulation.voltage:.2f} V "
        f"at {params.simulation.observation_distance:g} m",
        f"on-axis SPL (band)  : {r.band_spl(t.f_low, t.f_high):.1f} dB mean, "
        f"{r.variations_db(t.f_low, t.f_high):.1f} dB peak-to-peak",
        f"electrical impedance: {np.abs(r.Ze).min():.2f} - {np.abs(r.Ze).max():.2f} ohm",
        f"excursion rms       : {np.max(np.abs(r.excursion)) * 1e3:.2f} mm at "
        f"{r.f[int(np.argmax(np.abs(r.excursion)))]:.0f} Hz",
        f"excursion peak (1w) : {np.max(np.abs(r.excursion)) * excursion.RMS_TO_PEAK * 1e3:.2f} "
        f"mm at {r.f[int(np.argmax(np.abs(r.excursion)))]:.0f} Hz",
        f"directivity (mouth) : DI {r.di.min():.1f} - {r.di.max():.1f} dB, Q(coverage) = "
        f"{d['q_coverage']:.1f}, intercept = {d['directivity_intercept_hz']:.0f} Hz",
    ]
    return "\n".join(lines)


def write_report(params: Params, r: Result, path: str | Path,
                 figure_paths: list | None = None) -> Path:
    """Markdown report: what was simulated, with which values, and the checks."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    d = r.derived
    t = params.target
    sim = params.simulation
    drv = params.driver

    md = [
        f"# Horn workflow - Stage 1 report: {params.project}",
        "",
        f"generated: {_dt.datetime.now().isoformat(timespec='seconds')}  ",
        f"definition file: `{params.source_path}`  ",
        "model: 1P (Webster) horn + lumped-element driver, mouth terminated by "
        f"`{sim.mouth_termination}`  ",
        "",
        "## 1. Design summary",
        "",
        "```",
        summary_text(params, r),
        "```",
        "",
        "## 2. What this means (plain language)",
        "",
    ]
    md += [f"- {g}" for g in guidance_lines(params, r)]
    md += [
        "",
        "## 3. How big a horn has to be for a given cut-off",
        "",
        "Mouth diameter and depth needed to satisfy the paper's mouth criteria (k*rm = 0.7 and "
        "1.0) with this profile and throat - handy for seeing what a lower cut-off costs.",
        "",
        "| cut-off fc [Hz] | k*rm | mouth diameter [mm] | depth [mm] | envelope [m3] |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in size_requirement_rows(params, r):
        md.append(f"| {row['fc_hz']:.0f} | {row['k_rm']:.1f} | {row['mouth_diameter_mm']:.0f} | "
                  f"{row['length_mm']:.0f} | {row['bounding_volume_l'] / 1000:.2f} |")
    md += [
        "",
        "## 4. Resolved geometry",
        "",
        "| quantity | value | unit | note |",
        "| --- | --- | --- | --- |",
        _row("profile", d["profile"]),
        _row("throat radius r0", d["throat_radius_mm"], "mm"),
        _row("throat area St", d["throat_area_cm2"], "cm^2"),
        _row("mouth radius rm", d["mouth_radius_mm"], "mm"),
        _row("mouth diameter", d["mouth_diameter_mm"], "mm"),
        _row("mouth area Sm", d["mouth_area_cm2"], "cm^2"),
        _row("area ratio Sm/St", d["area_ratio"]),
        _row("length", d["length_mm"], "mm"),
        _row("cut-off frequency fc", d["fc_hz"], "Hz", "flare parameter of the profile"),
        _row("flare constant m", d["flare_m_1_per_m"], "1/m", "S = St e^(m x)"),
        _row("scale length x0", d["flare_x0_mm"], "mm", "x0 = c/(2 pi fc)"),
        _row("mouth circumference", d["mouth_circumference_mm"], "mm"),
        _row("wavelength at fc", d["lambda_at_fc_mm"], "mm"),
        _row("k*rm at fc", d["k_rm_at_fc"], "", f"target {d['k_rm_target']:.2f}"),
        _row("k*rt at fc", d["k_rt_at_fc"], ""),
        _row("1P validity limit", d["f_1P_validity_hz"], "Hz", "k*rt = 1"),
        _row("k*rm at f_high", d["mouth_ka_at_f_high"], "", f"{t.f_high:.0f} Hz"),
        _row("Q from coverage (Eq. 25)", d["q_coverage"]),
        _row("directivity intercept (Eq. 26)", d["directivity_intercept_hz"], "Hz"),
        _row("build width (mouth)", d["build_width_mm"], "mm",
             "equal-area circle for rectangular mouths"),
        _row("build height (mouth)", d["build_height_mm"], "mm"),
        _row("build depth", d["build_depth_mm"], "mm"),
        _row("envelope volume", d["build_volume_l"] / 1000.0, "m^3"),
        _row("air volume inside", d["horn_volume_l"], "l"),
        "",
        "## 5. Driver (lumped element)",
        "",
        "| quantity | value | unit |",
        "| --- | --- | --- |",
        _row("name", drv.name),
        _row("Sd (from dD)", drv.Sd * 1e4, "cm^2"),
        _row("dD", drv.dD * 1e3, "mm"),
        _row("Mms", drv.Mms * 1e3, "g"),
        _row("Cms", drv.Cms, "m/N"),
        _row("Rms", drv.Rms, "Ns/m"),
        _row("Bl", drv.Bl, "T*m"),
        _row("Re", drv.Re, "ohm"),
        _row("Le", drv.Le * 1e3, "mH"),
        _row("fs (no load)", drv.fs, "Hz"),
        _row("Qms", d["driver_Qms"]),
        _row("Qes", d["driver_Qes"]),
        _row("Qts", d["driver_Qts"]),
        _row("Vas", d["driver_Vas_l"], "l"),
        _row("rear volume", drv.rear_volume * 1e6, "cm^3"),
        _row("Vas/Vb (alpha)", d["box_alpha"]),
        _row("box resonance fb", d["box_resonance_hz"], "Hz", "sealed alignment"),
        _row("box Qtc", d["box_Qtc"], "", "> 1 means a peak at fb"),
        _row("Sd/St", d["compression_ratio_Sd_St"]),
    ]
    md += [
        "",
        "## 6. Simulation settings",
        "",
        "```",
        f"voltage              {sim.voltage:.2f} Vrms",
        f"frequency sweep      {sim.f_min:.0f} - {sim.f_max:.0f} Hz, {sim.n_frequencies} points, "
        f"{sim.spacing}",
        f"speed of sound       {sim.c:.1f} m/s    air density {sim.rho:.3f} kg/m^3",
        f"mouth termination    {sim.mouth_termination}"
        + ("  (piston in an infinite baffle, pressure doubled)" if sim.half_space
           else "  (free space)"),
        f"two-port segments    {sim.segments}",
        f"observation          {sim.observation_distance:g} m, on axis",
        "```",
        "",
        "## 7. How the geometry was completed, and warnings",
        "",
    ]
    if r.notes:
        md += ["Completed for you (not a problem, just so you know):", ""]
        md += [f"- {n}" for n in r.notes]
        md += [""]
    md += ["Warnings:", ""]
    md += [f"- {w}" for w in r.warnings] if r.warnings else ["- none"]
    md += [
        "",
        "## 8. Files",
        "",
    ]
    for p in (figure_paths or []):
        md.append(f"- `{Path(p).name}`")
    md += [
        "- `curves.csv` (all simulated curves, one row per frequency)",
        "",
        "## 9. What Stage 1 covers",
        "",
        "Covered: driver loading (throat impedance including the mouth reflection), "
        "on-axis SPL from the mouth volume velocity, electrical impedance, diaphragm "
        "excursion, directivity index, plus the design checks derived from the horn "
        "theory paper (flare constant, cut-off, k*rm mouth criterion, 1P validity).",
        "",
        "Not covered: mouth/edge diffraction, higher-order modes, real 3D geometry, "
        "baffle/ground/wall placement, phase-plug and front-cavity detail, polar maps. "
        "Those are Stage 2 (ATH -> Gmsh -> AKABAK BEM), which consumes this same "
        "definition file.",
        "",
    ]
    path.write_text("\n".join(md), encoding="utf-8")
    return path