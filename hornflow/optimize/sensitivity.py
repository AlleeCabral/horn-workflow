"""Constraint sensitivity (Stage 13).

For each active numerical limit, run one stricter and one relaxed case,
re-optimize the dependent geometry and record the differences.  Every effect
reported here is a ONE_DIMENSIONAL_SIMULATION result, which replaces the
QUALITATIVE limit-impact entries.
"""

from __future__ import annotations

import copy

import numpy as np

from .. import config
from .. import theory
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
    below = np.where(spl <= mean - 3.0)[0]
    cutoff = float(f[below[0]]) if len(below) else float(f[0])
    return {
        "spl_mean_db": round(mean, 3),
        "spl_variation_db": round(var, 3),
        "cutoff_minus3db_hz": round(cutoff, 2),
        "excursion_max_mm": round(float(np.max(run.excursion_m)) * 1e3, 4),
        "mouth_area_cm2": round(float(design.Sm) * 1e4, 1),
        "depth_mm": round(float(design.length) * 1e3, 1),
        "envelope_m3": round(float(design.build_volume_l()) * 1e-3, 4),
    }


# the limit -> (label, override key, stricter, relaxed) table
LEVERS = (
    ("passband_bottom", "target.f_low", {"target.f_low": 70}, {"target.f_low": 50}, "Hz"),
    ("depth_budget", "horn.length", {"horn.length": 1200}, {"horn.length": 1800}, "mm"),
    ("mouth_area", "horn.mouth_area", {"horn.mouth_area": 12000}, {"horn.mouth_area": 20000},
     "cm^2"),
    ("rear_chamber", "driver.rear_volume", {"driver.rear_volume": 20000},
     {"driver.rear_volume": 40000}, "cm^3"),
    ("drive_voltage", "simulation.voltage", {"simulation.voltage": 2.0},
     {"simulation.voltage": 4.0}, "V"),
)


def run_sensitivity(param_path, levers=LEVERS) -> list:
    """Return one record per lever with base / stricter / relaxed metrics."""
    base_params = config.load(param_path)
    base = _metrics(base_params)
    out = []
    for name, key, stricter, relaxed, unit in levers:
        try:
            p_str = config.load(param_path, overrides=copy.deepcopy(stricter))
            m_str = _metrics(p_str)
        except Exception as exc:                       # expected infeasibility
            m_str = {"error": str(exc)}
        try:
            p_rel = config.load(param_path, overrides=copy.deepcopy(relaxed))
            m_rel = _metrics(p_rel)
        except Exception as exc:
            m_rel = {"error": str(exc)}
        rel_delta = _delta(m_rel, base)
        rec = {
            "limit": name, "override": key, "unit": unit,
            "stricter": {**stricter, "metrics": m_str},
            "relaxed": {**relaxed, "metrics": m_rel},
            "delta_relaxed": rel_delta,
            "evidence": "ONE_DIMENSIONAL_SIMULATION",
        }
        if not rel_delta:
            rec["note"] = ("not testable via override for this project "
                           "(driver/geometry fixed by another key)")
        out.append(rec)
    # attach the base to every record for a self-contained table
    for rec in out:
        rec["base"] = base
    return out


def _delta(case: dict, base: dict) -> dict:
    keys = ("spl_mean_db", "spl_variation_db", "cutoff_minus3db_hz",
            "excursion_max_mm", "envelope_m3")
    out = {}
    for k in keys:
        if k in case and k in base:
            out[k + "_delta"] = round(case[k] - base[k], 4)
    return out
