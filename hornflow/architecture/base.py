"""Architecture model contract.

An architecture is a plugin behind ``ArchitectureModel``.  Four are wired for
real in this milestone (front-loaded horn, folded horn, sealed, reflex); the
rest are declared as SCREENING_ONLY stubs so the plugin surface exists without
shipping low-quality models.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Protocol, runtime_checkable

from ..domain.geometry import AcousticMaster


class FidelityLabel(str, Enum):
    SCREENING_ONLY = "SCREENING_ONLY"
    ONE_DIMENSIONAL = "ONE_DIMENSIONAL"
    BEM = "BEM"


@dataclass
class DesignContext:
    """Everything an architecture needs to synthesize a candidate."""

    params: object
    feasibility: object = None
    master: AcousticMaster | None = None
    requirements: dict = field(default_factory=dict)


@dataclass
class ArchitectureResult:
    architecture_id: str
    display_name: str
    fidelity: str
    feasible: bool
    master: AcousticMaster | None = None
    metrics: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    implementation: str = "wired"        # "wired" | "stub"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["master"] = self.master.to_dict() if self.master else None
        return d


@runtime_checkable
class ArchitectureModel(Protocol):
    architecture_id: str
    display_name: str
    fidelity: str

    def synthesize(self, ctx: DesignContext) -> ArchitectureResult:
        ...


@dataclass
class StubArchitecture:
    """A declared-but-not-yet-implemented architecture (SCREENING_ONLY)."""

    architecture_id: str
    display_name: str
    fidelity: str = FidelityLabel.SCREENING_ONLY.value
    reason: str = "screening model not yet implemented"

    def synthesize(self, ctx: DesignContext) -> ArchitectureResult:
        return ArchitectureResult(
            architecture_id=self.architecture_id,
            display_name=self.display_name,
            fidelity=self.fidelity,
            feasible=False,
            metrics={"status": "not_implemented"},
            warnings=[self.reason],
            implementation="stub",
        )
