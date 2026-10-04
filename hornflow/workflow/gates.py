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

    # excursion vs Xmax
    xmax = drv.Xmax
    exc = 0.0
    for r in runs:
        if getattr(r, "excursion_m", None) is not None:
            exc = max(exc, float(np.max(r.excursion_m)))
    if xmax:
        ok = exc <= xmax
        out.append(GateResult("excursion<=Xmax", ok,
                              f"max excursion {exc*1e3:.3f} mm vs Xmax {xmax*1e3:.2f} mm",
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
