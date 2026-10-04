"""Evidence labels and provenance.

Every numerical result that reaches a report must carry an EvidenceLabel so no
estimate can be mistaken for a simulation (a hard requirement of the spec).
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum


class EvidenceLabel(str, Enum):
    USER_INPUT = "USER_INPUT"
    MEASURED = "MEASURED"
    ANALYTICAL_ESTIMATE = "ANALYTICAL_ESTIMATE"
    ONE_DIMENSIONAL_SIMULATION = "ONE_DIMENSIONAL_SIMULATION"
    BEM_SIMULATION = "BEM_SIMULATION"
    FEM_SIMULATION = "FEM_SIMULATION"
    STRUCTURAL_SCREENING = "STRUCTURAL_SCREENING"


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class Provenance:
    """Where a value or artifact came from."""

    source: str
    method: str
    evidence: str = EvidenceLabel.ANALYTICAL_ESTIMATE.value
    solver: str | None = None
    solver_version: str | None = None
    created_utc: str = field(default_factory=now_utc)
    git_commit: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Provenance":
        known = {f: d.get(f) for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**known)  # type: ignore[arg-type]
