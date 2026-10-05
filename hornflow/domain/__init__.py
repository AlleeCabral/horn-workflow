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
from .excursion import (EVIDENCE as EXCURSION_EVIDENCE, ONE_WAY_PEAK,
                        PEAK_TO_PEAK, PEAK_TO_RMS, RMS_TO_PEAK, ExcursionSummary,
                        excursion_gate, normalize_convention, peak_mm, peak_to_rms,
                        rms_to_peak, summarize, xmax_one_way_peak)

__all__ = [
    "EvidenceLabel", "Provenance", "now_utc",
    "StageFailure",
    "canonical_json", "stable_id",
    "Constraint", "InputStatus", "LimitStatus", "LimitImpact",
    "AcousticMaster", "AreaLaw", "Centreline", "Section",
    "EXCURSION_EVIDENCE", "ONE_WAY_PEAK", "PEAK_TO_PEAK", "PEAK_TO_RMS",
    "RMS_TO_PEAK", "ExcursionSummary", "excursion_gate", "normalize_convention",
    "peak_mm", "peak_to_rms", "rms_to_peak", "summarize", "xmax_one_way_peak",
]
