"""hornflow.domain - pure domain layer.

No I/O, no CLI, no solver subprocesses, no visualization code may be imported
here.  Everything is typed, dataclass-based and dependency-free (standard
library only) so the domain can be unit-tested in isolation and serialized to a
stable, versioned state.
"""

from .evidence import EvidenceLabel, Provenance, now_utc
from .failures import StageFailure
from .ids import canonical_json, stable_id
from .limits import Constraint, InputStatus, LimitStatus, LimitImpact
from .geometry import AcousticMaster, AreaLaw, Centreline, Section

__all__ = [
    "EvidenceLabel", "Provenance", "now_utc",
    "StageFailure",
    "canonical_json", "stable_id",
    "Constraint", "InputStatus", "LimitStatus", "LimitImpact",
    "AcousticMaster", "AreaLaw", "Centreline", "Section",
]
