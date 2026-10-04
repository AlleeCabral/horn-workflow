"""Physical feasibility screening (Stage 3).

Level-1 analytical checks run before any simulation: wavelengths, quarter/half
wave reference lengths, mouth adequacy, path adequacy, displacement-limited and
thermal-limited output, throat compression, boundary loading and directivity
plausibility.  Impossible combinations are rejected here, explicitly.

Every number is an ANALYTICAL_ESTIMATE.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict

import numpy as np

from ..domain.evidence import EvidenceLabel

P_REF = 20.0e-6
_SPL_1W = 112.1  # dB re 20uPa @1m for 100% efficiency (reference-efficiency form)


@dataclass
class Feasibility:
    wavelengths_m: dict = field(default_factory=dict)
    quarter_wave_m: float = 0.0
    half_wave_m: float = 0.0
    krm_at_flow: float = 0.0
    mouth_adequate: bool = False
    path_adequate: bool = False
    displacement_spl_db: float = 0.0
    thermal_spl_db: float = 0.0
    throat_compression: float = 1.0
    compression_note: str = ""
    boundary: str = ""
    directivity_intercept_hz: float = 0.0
    limiting_factors: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    evidence: str = EvidenceLabel.ANALYTICAL_ESTIMATE.value

    def to_dict(self) -> dict:
        return asdict(self)


class FeasibilityEvaluator:
    """Analytical Level-1 screen for a driver + target + master geometry."""

    def evaluate(self, params, master) -> Feasibility:
        c = params.simulation.c
        rho = params.simulation.rho
        f_low = float(params.target.f_low)
        f_high = float(params.target.f_high)
        drv = params.driver
        f = Feasibility(boundary=master.boundary)

        lam = lambda fr: c / fr
        f.wavelengths_m = {
            "f_low": lam(f_low), "f_high": lam(f_high),
            "fc": lam(float(master.params_snapshot.get("fc", f_low))),
        }
        f.quarter_wave_m = lam(f_low) / 4.0
        f.half_wave_m = lam(f_low) / 2.0

        rm = float(np.sqrt(master.mouth_area / np.pi))
        k = 2.0 * np.pi * f_low / c
        f.krm_at_flow = k * rm
        f.mouth_adequate = f.krm_at_flow >= 0.7
        f.path_adequate = master.length >= 0.5 * f.quarter_wave_m
        f.throat_compression = float(drv.Sd / master.throat_area) if master.throat_area else 0.0
        f.compression_note = _compression_note(f.throat_compression)

        xmax = drv.Xmax if drv.Xmax else 0.0
        f.displacement_spl_db = _displacement_spl(
            f_low, drv.Sd, xmax, rho, c, half_space=params.simulation.half_space)
        f.thermal_spl_db = _thermal_spl(drv, rho, c)
        f.directivity_intercept_hz = 25.0e6 / (2.0 * rm * 1e3 * max(1.0, 2.0 * 45.0))

        # limiting-factor diagnosis
        if not f.mouth_adequate:
            f.limiting_factors.append("mouth-limited")
        if not f.path_adequate:
            f.limiting_factors.append("path-limited")
        if f.displacement_spl_db < f.thermal_spl_db - 3.0:
            f.limiting_factors.append("displacement-limited")
        elif f.thermal_spl_db != f.thermal_spl_db:      # NaN: no thermal rating given
            f.limiting_factors.append("thermal-limit-unknown")
        else:
            f.limiting_factors.append("thermally-limited")
        if f.throat_compression > 2.0:
            f.limiting_factors.append("compression-limited")

        # explicit rejections
        if master.length < 0.25 * f.quarter_wave_m:
            f.rejected.append(
                f"path too short for {f_low:.0f} Hz: {master.length*1e3:.0f} mm "
                f"< quarter-wave/4 ({0.25*f.quarter_wave_m*1e3:.0f} mm)")
        if xmax <= 0.0:
            f.rejected.append("driver Xmax unknown: displacement-limited output "
                              "cannot be bounded (safety-critical)")
        f.notes.append(
            f"mouth k*rm @{f_low:.0f} Hz = {f.krm_at_flow:.2f} "
            f"({'adequate' if f.mouth_adequate else 'small, expect ripple'})")
        return f


def _compression_note(x: float) -> str:
    if x < 0.8:
        return "expansion at the throat (no compression)"
    if x <= 1.25:
        return "direct coupled (low stress)"
    if x <= 2.0:
        return "mild compression (watch distortion)"
    return "high compression (distortion / driver stress risk)"


def _displacement_spl(f, Sd, Xmax, rho, c, half_space=True, r=1.0) -> float:
    """On-axis SPL from displacement alone: p = rho*w^2*Sd*X/(opening*pi*r)."""
    if Xmax <= 0.0:
        return float("-inf")
    w = 2.0 * np.pi * f
    opening = 2.0 if half_space else 4.0
    p = rho * w ** 2 * Sd * Xmax / (opening * np.pi * r)
    return float(20.0 * np.log10(max(p, 1e-12) / P_REF))


def _thermal_spl(drv, rho, c) -> float:
    """Reference-efficiency estimate of the thermal-limited mid-band SPL."""
    eta0 = (4.0 * np.pi ** 2 / c ** 3) * drv.fs ** 3 * drv.Vas / max(drv.Qes, 1e-6)
    power = drv.thermal_power if getattr(drv, "thermal_power", None) else None
    if power is None:
        return float("nan")
    return float(_SPL_1W + 10.0 * np.log10(max(eta0, 1e-12) * power))
