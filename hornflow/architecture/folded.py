"""Folded front-loaded horn (preferred architecture).

Acoustically it shares the *same* target master as the straight horn - folding
may not silently change the centreline length, area law, throat, chambers or
mouth.  The fold generator (hornflow.fold) later realises this master as a
folded centreline; the acoustic difference is evaluated by fold-aware
simulation and bend analysis, not by changing the master here.
"""

from __future__ import annotations

from .base import ArchitectureResult, DesignContext, FidelityLabel
from .front_loaded import build_master


class FoldedHorn:
    architecture_id = "folded_horn"
    display_name = "Folded front-loaded horn (preferred)"
    fidelity = FidelityLabel.ONE_DIMENSIONAL.value

    def synthesize(self, ctx: DesignContext) -> ArchitectureResult:
        design, master = build_master(ctx.params, self.architecture_id)
        derived = design.derived(ctx.params.target.f_low, ctx.params.target.krm_target)
        return ArchitectureResult(
            architecture_id=self.architecture_id,
            display_name=self.display_name,
            fidelity=self.fidelity,
            feasible=True,
            master=master,
            metrics=dict(derived),
            notes=["shares the straight-horn acoustic master; fold effects "
                   "screened by bend analysis + fold-aware simulation"],
        )
