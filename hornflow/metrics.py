"""Response metrics shared by the report, the box models and the sensitivity run.

The -3 dB point used to be "the first grid point below band mean minus 3 dB",
which is almost always the lowest frequency on the grid: every sensitivity row
reported 20 Hz and a sealed box reported its own f_min.  The crossing is defined
once, here, and everything that names a cutoff calls it (audit P3).
"""

from __future__ import annotations

import numpy as np


def minus3db_cutoff(f, spl, f_lo: float, f_hi: float) -> float | None:
    """The low-frequency -3 dB point of ``spl`` over ``[f_lo, f_hi]``.

    The band mean is the reference.  The scan starts at the lowest in-band point
    and walks down in frequency, returning the first crossing at or below
    ``mean - 3 dB``, interpolated linearly in log f.  ``None`` means the response
    never drops that far on the grid, so the run has no cutoff to report.  ``NaN``
    means the band held no usable sample: that is a different fact from "never
    drops" and must not be reported as ``None``.

    The band mean ignores NaN samples, so one bad frequency does not hide a real
    crossing.
    """
    f = np.asarray(f, float)
    spl = np.asarray(spl, float)
    if f.size < 2 or spl.size != f.size:
        return None
    in_band = (f >= f_lo) & (f <= f_hi)
    if not np.any(in_band):
        return None
    band = spl[in_band]
    if np.all(np.isnan(band)):
        return float("nan")
    level = float(np.nanmean(band)) - 3.0
    upper = int(np.argmax(in_band))               # the lowest in-band index
    lower = None
    if spl[upper] <= level:
        lower = upper - 1                         # already down at the band edge
    else:
        for j in range(upper - 1, -1, -1):
            if spl[j] <= level:
                lower = j
                break
    if lower is None:
        return None
    if lower < 0:
        # the grid ends before the crossing: report it only if the last point is
        # already below the level, otherwise there is nothing honest to say
        return float(f[0]) if spl[0] <= level else None
    f_lo_grid, f_hi_grid = float(f[lower]), float(f[upper])
    s_lo, s_hi = float(spl[lower]), float(spl[upper])
    if s_hi == s_lo:
        return f_hi_grid
    t = (level - s_lo) / (s_hi - s_lo)
    return float(np.exp(np.log(f_lo_grid)
                        + t * (np.log(f_hi_grid) - np.log(f_lo_grid))))
