"""Hard rejection gates.

These are evaluated BEFORE scoring.  A high weighted score cannot rescue a
candidate that fails a hard gate.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str = ""
    evidence: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def hard_gates(params, feasibility, runs, variants=None, limits=None) -> list:
    limits = dict(limits or {})
    drv = params.driver
    out = []

    # excursion vs Xmax - like-for-like: one-way peak travel against one-way peak Xmax
    from ..domain.excursion import RMS_TO_PEAK, normalize_convention, xmax_one_way_peak

    xmax = drv.Xmax
    exc_rms = 0.0
    for r in runs:
        arr = getattr(r, "excursion_rms_m", None)
        if arr is None:
            arr = getattr(r, "excursion_m", None)   # pre-1.1 state, still rms
        if arr is not None:
            exc_rms = max(exc_rms, float(np.max(np.abs(arr))))
    exc_peak = RMS_TO_PEAK * exc_rms
    if xmax:
        conv = normalize_convention(getattr(drv, "Xmax_convention", None))
        peak_limit = xmax_one_way_peak(xmax, conv)
        ok = exc_peak <= peak_limit
        out.append(GateResult(
            "excursion<=Xmax", ok,
            f"peak travel {exc_peak * 1e3:.3f} mm "
            f"(= {exc_rms * 1e3:.3f} mm rms x sqrt(2)) vs Xmax "
            f"{peak_limit * 1e3:.2f} mm one-way peak",
            "ONE_DIMENSIONAL_SIMULATION"))
    else:
        out.append(GateResult("excursion<=Xmax", False, "Xmax unknown (safety-critical)",
                              "USER_INPUT"))

    # minimum safe impedance
    zmin = limits.get("min_safe_impedance_ohm")
    if zmin:
        zlo = min((float(np.min(np.hypot(r.impedance_real_ohm, r.impedance_imag_ohm)))
                   for r in runs), default=float("inf"))
        out.append(GateResult("Ze>=min_safe", zlo >= float(zmin),
                              f"min |Ze| {zlo:.2f} ohm vs limit {zmin}",
                              "ONE_DIMENSIONAL_SIMULATION"))

    # geometry feasibility
    rejected = list(getattr(feasibility, "rejected", []) or [])
    out.append(GateResult("geometry_feasible", not rejected,
                          "; ".join(rejected) if rejected else "no infeasibility",
                          "ANALYTICAL_ESTIMATE"))

    # size limit (optional)
    max_vol = limits.get("max_external_volume_m3")
    if max_vol:
        vols = [v.metrics.get("gross_volume_m3") for v in (variants or [])]
        vols = [v for v in vols if v is not None]
        if vols:
            ok = min(vols) <= float(max_vol)
            out.append(GateResult("size<=max", ok,
                                  f"min gross volume {min(vols):.3f} m^3 vs {max_vol}",
                                  "ANALYTICAL_ESTIMATE"))

    # manufacturing watertight (any valid variant must be watertight)
    if variants:
        ok = any(v.valid and v.metrics.get("watertight", True) for v in variants)
        out.append(GateResult("watertight_variant", ok,
                              "at least one watertight manufacturing variant",
                              "ANALYTICAL_ESTIMATE"))
    return out


def all_passed(gates) -> bool:
    return all(g.passed for g in gates)
