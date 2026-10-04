"""Typed stage failures.

Expected engineering infeasibility is *data*, not an exception.  Exceptions are
reserved for programming, dependency and data-integrity errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict


@dataclass
class StageFailure:
    """A non-recoverable-by-itself stage result carrying actionable evidence."""

    stage: str
    category: str                 # e.g. "FEASIBILITY", "GEOMETRY", "MESH", "DEPENDENCY"
    failed_checks: list = field(default_factory=list)
    affected_candidates: list = field(default_factory=list)
    recoverable: bool = False
    recommended_upstream_revision: str = ""
    evidence: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)
