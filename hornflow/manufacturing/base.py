"""Manufacturing transformer contract and variant record."""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Protocol, runtime_checkable


@dataclass
class ManufacturingVariant:
    variant_id: str
    method: str                 # "additive" | "plywood"
    candidate_id: str
    fold_id: str
    valid: bool
    metrics: dict = field(default_factory=dict)
    deviations: dict = field(default_factory=dict)
    panels: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    artifacts: dict = field(default_factory=dict)
    deferred: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@runtime_checkable
class ManufacturingTransformer(Protocol):
    method: str

    def transform(self, candidate, cfg: dict) -> ManufacturingVariant:
        ...

    def exports(self, variant: ManufacturingVariant) -> dict:
        ...
