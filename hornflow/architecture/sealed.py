"""Sealed enclosure - analytical screening model (SCREENING_ONLY)."""

from __future__ import annotations

import numpy as np

from . import box_models
from .base import ArchitectureResult, DesignContext, FidelityLabel


def _power(params) -> float:
    return params.simulation.voltage ** 2 / max(params.driver.Re, 1e-6)


class SealedBox:
    architecture_id = "sealed_box"
    display_name = "Sealed enclosure"
    fidelity = FidelityLabel.SCREENING_ONLY.value

    def synthesize(self, ctx: DesignContext) -> ArchitectureResult:
        p = ctx.params
        f = p.simulation.frequencies()
        Vb = float(p.driver.rear_volume) or float(p.driver.Vas) * 0.4
        spl = box_models.sealed_spl(f, p.driver, Vb, power_w=_power(p))
        align = box_models.sealed_alignment(p.driver, Vb)
        metrics = box_models.band_metrics(f, spl, p.target.f_low, p.target.f_high)
        metrics.update({"Vb_l": Vb * 1e3, "fb_hz": align["fb"], "Qtc": align["Qtc"],
                        "alpha": align["alpha"]})
        return ArchitectureResult(
            architecture_id=self.architecture_id,
            display_name=self.display_name,
            fidelity=self.fidelity,
            feasible=True,
            master=None,
            metrics=metrics,
            warnings=["SCREENING_ONLY: 2nd-order T/S estimate, not a 3-D simulation"],
        )
