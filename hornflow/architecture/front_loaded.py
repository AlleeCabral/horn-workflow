"""Front-loaded horn (straight) - wraps the existing validated Webster design."""

from __future__ import annotations

from .. import theory
from ..domain.geometry import AcousticMaster
from ..domain.ids import stable_id
from .base import ArchitectureResult, DesignContext, FidelityLabel


def candidate_id(architecture_id: str, design, aspect: float, boundary: str) -> str:
    return stable_id("cand", {
        "architecture": architecture_id,
        "profile": design.profile,
        "throat_area_m2": round(float(design.St), 9),
        "mouth_area_m2": round(float(design.Sm), 9),
        "length_m": round(float(design.length), 9),
        "aspect": round(float(aspect), 6),
        "boundary": boundary,
    })


def build_master(params, architecture_id: str) -> tuple:
    """Solve the straight horn and wrap it as an AcousticMaster (no new physics)."""
    design = theory.solve_design(params.horn, params.target,
                                 c=params.simulation.c, rho=params.simulation.rho)
    boundary = "piston_infinite_baffle" if params.simulation.half_space else "free"
    aspect = float(getattr(params.horn, "mouth_aspect", 1.6) or 1.6)
    cid = candidate_id(architecture_id, design, aspect, boundary)
    master = AcousticMaster.from_design(
        design, cid, architecture_id, aspect=aspect, boundary=boundary,
        rear_volume=float(params.driver.rear_volume),
        params_snapshot={"profile": design.profile, "fc": float(design.fc),
                         "throat_diameter_mm": float(params.horn.throat_diameter) * 1e3,
                         "mouth_aspect": aspect},
    )
    return design, master


class FrontLoadedHorn:
    architecture_id = "front_loaded_horn"
    display_name = "Front-loaded horn (straight)"
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
            notes=["validated 1-P Webster + lumped-element core"],
        )
