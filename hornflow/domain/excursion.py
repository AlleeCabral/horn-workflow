"""Excursion and Xmax conventions - the single source of truth.

WHY THIS MODULE EXISTS
----------------------
``response.simulate()`` drives the lumped-element network with ``sim.voltage``
in **volts rms** (the project-wide convention: 2.83 V rms), so every phasor it
produces is an rms phasor::

    current   = sim.voltage / Ze        # A rms
    velocity  = Bl * current / Zm       # m/s rms
    excursion = velocity / (j * w)      # m rms      <-- NOT peak

Until 2026-10-04 the exported column was named ``excursion_peak_mm`` while
holding that rms value, so every "Xmax is reached at ..." figure was optimistic
by 3.01 dB of displacement - a factor of two in drive power.  No physics
changed when this module was added: only the labels and the missing sqrt(2).

CONVENTIONS (fixed - do not change silently)
--------------------------------------------
solver output ........ ``rms``, one-way magnitude
``excursion_rms_mm`` .. rms displacement, one-way
``excursion_peak_mm`` . one-way peak displacement == sqrt(2) * rms for a steady
                        sine, which is the only waveform this model describes
``driver.Xmax`` ....... one-way peak linear excursion (the data-sheet default;
                        override with ``driver.Xmax_convention``)
comparison ............ always like-for-like: peak travel vs one-way peak Xmax

Evidence label: ``ANALYTICAL_ESTIMATE``.  The sqrt(2) is exact for a steady sine
at each frequency, so no crest factor is assumed or hidden.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

# --------------------------------------------------------------------------- #
#  the conversion factors everything else must use
# --------------------------------------------------------------------------- #
RMS_TO_PEAK = math.sqrt(2.0)      # 1.4142135623730951
PEAK_TO_RMS = 1.0 / RMS_TO_PEAK   # 0.7071067811865475

EVIDENCE = "ANALYTICAL_ESTIMATE"

# --------------------------------------------------------------------------- #
#  Xmax conventions
# --------------------------------------------------------------------------- #
ONE_WAY_PEAK = "one_way_peak"
PEAK_TO_PEAK = "peak_to_peak"

XMAX_CONVENTIONS = (ONE_WAY_PEAK, PEAK_TO_PEAK)

# Spellings seen in data sheets, the brief and older YAML files.  Anything not
# listed here is an error rather than a guess: a silent default would be exactly
# the class of bug this module exists to prevent.
_ALIASES = {
    "one_way_peak": ONE_WAY_PEAK,
    "one-way peak": ONE_WAY_PEAK,
    "one_way": ONE_WAY_PEAK,
    "one-way": ONE_WAY_PEAK,
    "peak": ONE_WAY_PEAK,
    "xmax": ONE_WAY_PEAK,
    "peak_to_peak": PEAK_TO_PEAK,
    "peak-to-peak": PEAK_TO_PEAK,
    "p-p": PEAK_TO_PEAK,
    "p2p": PEAK_TO_PEAK,
}

_CONVENTION_LABEL = {
    ONE_WAY_PEAK: "one-way peak",
    PEAK_TO_PEAK: "peak-to-peak",
}


def normalize_convention(value) -> str:
    """Map an accepted spelling to a canonical convention id.

    ``None`` means "the data-sheet default", i.e. one-way peak.  Any other
    unrecognised string raises - never guess, because guessing here silently
    halves or doubles a safety margin.
    """
    if value is None:
        return ONE_WAY_PEAK
    key = str(value).strip().lower()
    if key in _ALIASES:
        return _ALIASES[key]
    raise ValueError(
        f"unknown Xmax convention {value!r}; expected one of "
        f"{', '.join(sorted(_ALIASES))}")


def convention_label(value) -> str:
    """Human-readable form of a convention for reports and the UI."""
    return _CONVENTION_LABEL[normalize_convention(value)]


def xmax_one_way_peak(xmax_m, convention=ONE_WAY_PEAK) -> float:
    """Convert a declared Xmax to a **one-way peak** value [m].

    * ``one_way_peak`` - already like-for-like with the solver's peak travel.
    * ``peak_to_peak`` - a p-p figure is twice the one-way value, so divide by 2.
    """
    if xmax_m is None:
        return float("nan")
    x = float(xmax_m)
    if x <= 0.0:
        raise ValueError("Xmax must be > 0 when given")
    return x if normalize_convention(convention) == ONE_WAY_PEAK else x / 2.0


# --------------------------------------------------------------------------- #
#  rms <-> peak displacement
# --------------------------------------------------------------------------- #
def rms_to_peak(x_rms):
    """One-way peak displacement from rms [m] (or a whole array of them)."""
    return RMS_TO_PEAK * x_rms


def peak_to_rms(x_peak):
    """Rms displacement from one-way peak [m] (or a whole array of them)."""
    return PEAK_TO_RMS * x_peak


def rms_mm(x_rms_m: float) -> float:
    return float(x_rms_m) * 1e3


def peak_mm(x_rms_m: float) -> float:
    """One-way peak in mm, from an rms value in metres."""
    return float(x_rms_m) * RMS_TO_PEAK * 1e3


# --------------------------------------------------------------------------- #
#  the band summary
# --------------------------------------------------------------------------- #
@dataclass
class ExcursionSummary:
    """Displacement summary in both conventions plus the Xmax margin.

    Every marginal figure is computed **peak travel vs one-way peak Xmax**; the
    rms values are carried alongside purely so the two are never confused again.
    """

    drive_voltage_vrms: float
    drive_power_w: float
    re_ohm: float
    rms_max_m: float
    peak_max_m: float
    f_at_max_hz: float
    rms_at_f_max_m: float
    # Xmax block
    xmax_declared_m: float | None = None
    xmax_convention: str = ONE_WAY_PEAK
    xmax_one_way_peak_m: float = float("nan")
    peak_used_pct: float | None = None
    rms_used_pct: float | None = None
    peak_margin_m: float | None = None
    peak_margin_db: float | None = None
    voltage_vrms_at_xmax: float | None = None
    power_w_at_xmax: float | None = None
    # convenience, so a caller never re-derives the conversion by hand
    rms_to_peak: float = RMS_TO_PEAK
    evidence: str = EVIDENCE

    @property
    def has_xmax(self) -> bool:
        return self.xmax_declared_m is not None

    def to_dict(self) -> dict:
        return asdict(self)


def summarize(excursion_rms_m, frequency_hz, *, drive_voltage_vrms: float,
              re_ohm: float, xmax_m=None, xmax_convention=ONE_WAY_PEAK,
              ) -> ExcursionSummary:
    """Band summary of a solver's **rms** excursion array.

    ``excursion_rms_m`` is taken verbatim from the solver; the peak column is
    derived here, once, so no caller has to remember the sqrt(2).

    ``voltage_vrms_at_xmax`` follows from displacement scaling linearly with
    drive voltage: the rms travel that corresponds to the Xmax *peak* is
    ``Xmax / sqrt(2)``, so the drive level is scaled by the same ratio.  Power
    uses ``P = V^2 / Re``, the same convention the rest of the report uses.
    """
    import numpy as np

    x = np.abs(np.asarray(excursion_rms_m, dtype=float))
    f = np.asarray(frequency_hz, dtype=float)
    if x.size == 0:
        raise ValueError("excursion array is empty")
    i = int(np.argmax(x))
    rms_max = float(x[i])
    peak_max = float(RMS_TO_PEAK * rms_max)

    v0 = float(drive_voltage_vrms)
    re = float(re_ohm)
    summary = ExcursionSummary(
        drive_voltage_vrms=v0,
        drive_power_w=(v0 ** 2 / re) if re > 0 else float("nan"),
        re_ohm=re,
        rms_max_m=rms_max,
        peak_max_m=peak_max,
        f_at_max_hz=float(f[i]) if f.size else float("nan"),
        rms_at_f_max_m=rms_max,
    )

    if xmax_m is not None:
        conv = normalize_convention(xmax_convention)
        peak_limit = xmax_one_way_peak(xmax_m, conv)
        summary.xmax_declared_m = float(xmax_m)
        summary.xmax_convention = conv
        summary.xmax_one_way_peak_m = peak_limit
        if peak_limit > 0.0:
            summary.peak_used_pct = 100.0 * peak_max / peak_limit
            summary.rms_used_pct = 100.0 * rms_max / peak_limit
            summary.peak_margin_m = peak_limit - peak_max
            summary.peak_margin_db = (20.0 * math.log10(peak_limit / peak_max)
                                      if peak_max > 0.0 else float("inf"))
            if rms_max > 0.0:
                summary.voltage_vrms_at_xmax = v0 * (peak_limit / RMS_TO_PEAK) / rms_max
                if re > 0.0:
                    summary.power_w_at_xmax = summary.voltage_vrms_at_xmax ** 2 / re
    return summary


def excursion_gate(excursion_rms_m, *, xmax_m=None, xmax_convention=ONE_WAY_PEAK,
                   ) -> tuple:
    """Like-for-like hard gate: peak travel vs one-way peak Xmax.

    Returns ``(ok, peak_m, limit_m, detail)``.  ``ok`` is ``False`` when Xmax is
    unknown, because an unknown safety limit is not a pass.
    """
    import numpy as np

    x = np.abs(np.asarray(excursion_rms_m, dtype=float))
    peak = float(RMS_TO_PEAK * np.max(x)) if x.size else 0.0
    if xmax_m is None:
        return False, peak, float("nan"), "Xmax unknown (safety-critical)"
    conv = normalize_convention(xmax_convention)
    limit = xmax_one_way_peak(xmax_m, conv)
    ok = peak <= limit
    detail = (f"peak travel {peak * 1e3:.3f} mm vs Xmax {limit * 1e3:.2f} mm "
              f"one-way peak (declared as {convention_label(conv)})")
    return ok, peak, limit, detail
