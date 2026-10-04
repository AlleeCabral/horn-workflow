"""Constraints, input statuses and limit-impact records.

Two orthogonal classifications are used:

* ``InputStatus`` - how the user gave the value (FIXED / PREFERRED / RANGE /
  OPTIMIZABLE / UNKNOWN).
* ``LimitStatus`` - how the value behaves in this design (HARD / ACTIVE /
  INACTIVE / DOMINATED / UNCERTAIN).

A ``LimitImpact`` is the plain-language + technical explanation the spec
requires for every user limit, and it records whether its assessment is still
QUALITATIVE or has been replaced by a measured/simulated effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum


class InputStatus(str, Enum):
    FIXED = "FIXED"
    PREFERRED = "PREFERRED"
    RANGE = "RANGE"
    OPTIMIZABLE = "OPTIMIZABLE"
    UNKNOWN = "UNKNOWN"


class LimitStatus(str, Enum):
    HARD = "HARD"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    DOMINATED = "DOMINATED"
    UNCERTAIN = "UNCERTAIN"


@dataclass
class Constraint:
    """One user constraint with unit, provenance and confidence."""

    name: str
    value: float | str | None
    unit: str = ""
    status: str = InputStatus.UNKNOWN.value
    hard: bool = False
    low: float | None = None          # for RANGE
    high: float | None = None
    confidence: float = 1.0
    uncertainty: float | None = None
    provenance: str = "USER_INPUT"

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class LimitImpact:
    """Required explanation for one user limit (spec: limit-impact table)."""

    name: str
    value: str
    status: str = LimitStatus.UNCERTAIN.value
    positive: str = ""
    negative: str = ""
    physical_reason: str = ""
    most_affected_outputs: str = ""
    assessment: str = "QUALITATIVE"   # QUALITATIVE | MEASURED | SIMULATED
    suggested_relaxation: str = ""
    effects: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
