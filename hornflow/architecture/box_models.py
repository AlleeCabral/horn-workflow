"""Analytical box models (sealed / vented) - SCREENING_ONLY.

These are the classic small-signal T/S responses, used only to compare a
non-horn architecture against a horn at the screening level.  They are
analytical estimates, never simulations, and are labelled as such.
"""

from __future__ import annotations

import numpy as np

P_REF = 20.0e-6
_SPL_1W = 112.1


def reference_sensitivity(driver, power_w: float = 1.0) -> float:
    """Mid-band SPL [dB] at 1 m for a given electrical power (estimate)."""
    eta0 = (4.0 * np.pi ** 2 / 343.0 ** 3) * driver.fs ** 3 * driver.Vas / max(driver.Qes, 1e-6)
    return float(_SPL_1W + 10.0 * np.log10(max(eta0, 1e-12) * max(power_w, 1e-12)))


def sealed_alignment(driver, Vb: float) -> dict:
    if Vb <= 0.0:
        return {"fb": driver.fs, "Qtc": driver.Qts, "alpha": float("nan")}
    alpha = driver.Vas / Vb
    root = np.sqrt(1.0 + alpha)
    return {"fb": float(driver.fs * root), "Qtc": float(driver.Qts * root),
            "alpha": float(alpha)}


def _hp2(f, fc, Q):
    u = f / fc
    return u ** 2 / np.sqrt((1.0 - u ** 2) ** 2 + (u / Q) ** 2)


def sealed_spl(f, driver, Vb: float, power_w: float = 1.0):
    """2nd-order sealed-box on-axis SPL [dB] (analytical estimate)."""
    a = sealed_alignment(driver, Vb)
    ref = reference_sensitivity(driver, power_w)
    return ref + 20.0 * np.log10(np.maximum(_hp2(np.asarray(f, float), a["fb"], a["Qtc"]), 1e-9))


def band_metrics(f, spl, f_lo: float, f_hi: float) -> dict:
    """Mean / variation / -3 dB cutoff of a response over a band."""
    f = np.asarray(f, float)
    spl = np.asarray(spl, float)
    m = (f >= f_lo) & (f <= f_hi)
    mean = float(np.mean(spl[m])) if np.any(m) else float("nan")
    var = float(np.max(spl[m]) - np.min(spl[m])) if np.any(m) else float("nan")
    # -3 dB point relative to the band mean, scanning downward
    below = np.where(spl <= mean - 3.0)[0]
    cutoff = float(f[below[0]]) if len(below) else float(f[0])
    return {"spl_mean_db": mean, "spl_variation_db": var,
            "cutoff_minus3db_hz": cutoff,
            "f_min_hz": float(f[0]), "f_max_hz": float(f[-1])}


def vented_spl(f, driver, Vb: float, fb_port: float | None = None,
               Ql: float = 7.0, power_w: float = 1.0):
    """4th-order vented-box SPL [dB] (analytical estimate, SCREENING_ONLY).

    Modelled as the sealed 2nd-order section cascaded with a port high-pass at
    the tuning frequency.  This is an approximation for screening only and is
    always flagged; a real decision needs a vented simulation.
    """
    a = sealed_alignment(driver, Vb)
    fb = float(fb_port) if fb_port else float(driver.fs * (a["alpha"] ** 0.25))
    ref = reference_sensitivity(driver, power_w)
    sec1 = _hp2(np.asarray(f, float), a["fb"], a["Qtc"])
    sec2 = _hp2(np.asarray(f, float), fb, 0.7)
    return ref + 20.0 * np.log10(np.maximum(sec1 * sec2, 1e-9))

