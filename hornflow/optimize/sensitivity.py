"""Constraint sensitivity (Stage 13).

For each active numerical limit, run one stricter and one relaxed case,
re-optimize the dependent geometry and record the differences.  Every effect
reported here is a ONE_DIMENSIONAL_SIMULATION result, which replaces the
QUALITATIVE limit-impact entries.
"""

from __future__ import annotations

import numpy as np

from .. import config
from .. import theory
from ..metrics import minus3db_cutoff
from ..physics.solvers.webster import WebsterSolver


def _metrics(params) -> dict:
    design = theory.solve_design(params.horn, params.target,
                                 c=params.simulation.c, rho=params.simulation.rho)
    run = WebsterSolver(params).solve()
    f = run.frequency_hz
    spl = run.spl_db
    m = (f >= params.target.f_low) & (f <= params.target.f_high)
    mean = float(np.mean(spl[m])) if np.any(m) else float("nan")
    var = float(np.max(spl[m]) - np.min(spl[m])) if np.any(m) else float("nan")
    cutoff = minus3db_cutoff(f, spl, params.target.f_low, params.target.f_high)
    return {
        "spl_mean_db": round(mean, 3),
        "spl_variation_db": round(var, 3),
        "cutoff_minus3db_hz": None if cutoff is None else round(cutoff, 2),
        # rms is the solver convention; peak is the one that compares with Xmax
        "excursion_rms_mm": round(float(np.max(run.excursion_rms_m)) * 1e3, 4),
        "excursion_peak_mm": round(float(np.max(run.peak_excursion_m)) * 1e3, 4),
        "mouth_area_cm2": round(float(design.Sm) * 1e4, 1),
        "throat_area_cm2": round(float(design.St) * 1e4, 1),
        "depth_mm": round(float(design.length) * 1e3, 1),
        "envelope_m3": round(float(design.build_volume_l()) * 1e-3, 4),
    }


# label -> (what it moves, stricter factor, relaxed factor, unit).  Factors are
# relative to this project, so a lever means the same thing on any design; the
# absolute numbers it used to carry only made sense for one horn (audit P3).
LEVERS = (
    ("passband_bottom", "target.f_low", 1.15, 0.85, "Hz"),
    ("depth_budget", "horn.length", 0.8, 1.2, "mm"),
    # fc and the length together define the mouth, so the mouth lever moves fc
    ("mouth_area", "target.fc", 1.15, 0.85, "Hz"),
    ("rear_chamber", "driver.rear_volume", 0.5, 2.0, "cm^3"),
    ("drive_voltage", "simulation.voltage", 0.7, 1.4, "V"),
)

# dotted key -> (how to read it from Params, factor back to the definition unit)
_YAML_VALUE = {
    "target.f_low": (lambda p: p.target.f_low, 1.0),
    "target.fc": (lambda p: p.target.fc, 1.0),
    "horn.length": (lambda p: p.horn.length, 1e3),
    "driver.rear_volume": (lambda p: p.driver.rear_volume, 1e6),
    "simulation.voltage": (lambda p: p.simulation.voltage, 1.0),
}


def _override(key: str, factor: float, params) -> dict | None:
    """The dotted override in definition units, or None when the value is auto."""
    getter, scale = _YAML_VALUE[key]
    value = getter(params)
    if value is None:
        return None
    return {key: round(float(value) * scale * factor, 6)}


def run_sensitivity(param_path, levers=LEVERS, *, snapshot: bool = False) -> list:
    """Return one record per lever with base / stricter / relaxed metrics.

    ``snapshot`` is passed to :func:`config.load`: a run's own copy resolves its
    driver inside the run, a plain definition resolves it as written.
    """
    base_params = config.load(param_path, snapshot=snapshot)
    base = _metrics(base_params)
    out = []
    for name, key, strict_factor, relax_factor, unit in levers:
        cases = {}
        for label, factor in (("stricter", strict_factor), ("relaxed", relax_factor)):
            override = _override(key, factor, base_params)
            if override is None:
                cases[label] = {key: None, "factor": factor,
                                "metrics": {"error": f"{key} is 'auto' here"},
                                "geometry_changed": {}, "no_effect": False}
                continue
            try:
                params = config.load(param_path, overrides=dict(override),
                                     snapshot=snapshot)
                metrics = _metrics(params)
            except Exception as exc:                   # expected infeasibility
                metrics = {"error": str(exc)}
            cases[label] = {**override, "factor": factor, "metrics": metrics,
                            "geometry_changed": _geometry_changed(metrics, base),
                            "no_effect": _no_effect(metrics, base)}
        rel_delta = _delta(cases["relaxed"]["metrics"], base)
        rec = {
            "limit": name, "override": key, "unit": unit,
            "stricter": cases["stricter"], "relaxed": cases["relaxed"],
            "delta_relaxed": rel_delta,
            "evidence": "ONE_DIMENSIONAL_SIMULATION",
        }
        if not _moved(rel_delta):
            rec["note"] = "the relaxed case did not move a reported metric"
        out.append(rec)
    # attach the base to every record for a self-contained table
    for rec in out:
        rec["base"] = base
    return out


def _geometry_changed(case: dict, base: dict) -> dict:
    """How far the re-optimised geometry moved, in report units."""
    out = {}
    for k in ("mouth_area_cm2", "depth_mm", "throat_area_cm2"):
        a, b = case.get(k), base.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out[k] = round(a - b, 4)
    return out


def _no_effect(case: dict, base: dict) -> bool:
    """True when the case changed the geometry but moved no reported metric."""
    if "error" in case:
        return False
    return not _moved(_delta(case, base))


def _moved(delta: dict) -> bool:
    """True when at least one delta is a real move, not rounding noise."""
    return any(abs(v) > 1e-9 for v in delta.values())


def _delta(case: dict, base: dict) -> dict:
    keys = ("spl_mean_db", "spl_variation_db", "cutoff_minus3db_hz",
            "excursion_rms_mm", "excursion_peak_mm", "envelope_m3")
    out = {}
    for k in keys:
        a, b = case.get(k), base.get(k)
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            out[k + "_delta"] = round(a - b, 4)
    return out
