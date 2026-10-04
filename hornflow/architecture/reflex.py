"""Bass-reflex enclosure - analytical screening model (SCREENING_ONLY)."""

from __future__ import annotations

from . import box_models
from .base import ArchitectureResult, DesignContext, FidelityLabel
from .sealed import _power


class ReflexBox:
    architecture_id = "bass_reflex"
    display_name = "Bass-reflex enclosure"
    fidelity = FidelityLabel.SCREENING_ONLY.value

    def synthesize(self, ctx: DesignContext) -> ArchitectureResult:
        p = ctx.params
        f = p.simulation.frequencies()
        Vb = float(p.driver.rear_volume) or float(p.driver.Vas)
        spl = box_models.vented_spl(f, p.driver, Vb, power_w=_power(p))
        align = box_models.sealed_alignment(p.driver, Vb)
        fb = float(p.driver.fs * (align["alpha"] ** 0.25)) if align["alpha"] == align["alpha"] else p.driver.fs
        metrics = box_models.band_metrics(f, spl, p.target.f_low, p.target.f_high)
        metrics.update({"Vb_l": Vb * 1e3, "fb_port_hz": fb, "Qtc_sealed": align["Qtc"]})
        return ArchitectureResult(
            architecture_id=self.architecture_id,
            display_name=self.display_name,
            fidelity=self.fidelity,
            feasible=True,
            master=None,
            metrics=metrics,
            warnings=["SCREENING_ONLY: approximate 4th-order T/S estimate, "
                      "not a real vented simulation"],
        )
