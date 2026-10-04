"""Architecture registry and scoring.

Folded-horn preference is a *scoring* bonus applied after hard gates; it can
never rescue an infeasible or unsafe candidate.
"""

from __future__ import annotations

from .base import ArchitectureResult, DesignContext, StubArchitecture
from .folded import FoldedHorn
from .front_loaded import FrontLoadedHorn
from .reflex import ReflexBox
from .sealed import SealedBox

# architectures with a real model in this milestone
WIRED = (FoldedHorn(), FrontLoadedHorn(), SealedBox(), ReflexBox())

# declared plugin surface (implemented later; SCREENING_ONLY stubs)
STUBS = (
    StubArchitecture("tapped_horn", "Tapped horn"),
    StubArchitecture("offset_driver_horn", "Offset-driver horn"),
    StubArchitecture("transmission_line", "Quarter-wave transmission line"),
    StubArchitecture("mltl", "Mass-loaded transmission line"),
    StubArchitecture("bandpass", "Band-pass enclosure"),
    StubArchitecture("passive_radiator", "Passive-radiator enclosure"),
    StubArchitecture("cardioid_pair", "Cardioid / gradient pair"),
    StubArchitecture("endfire_array", "End-fire array"),
    StubArchitecture("manifold_horn", "Multi-driver manifold horn"),
    StubArchitecture("hybrid_band", "Hybrid divided-band system"),
)

# default preference bonus for the preferred (folded horn) class
PREFERENCE_BONUS = {"folded_horn": 0.05}


def by_id(architecture_id: str):
    for a in WIRED:
        if a.architecture_id == architecture_id:
            return a
    for s in STUBS:
        if s.architecture_id == architecture_id:
            return s
    return None


def all_architectures(wired_only: bool = False) -> list:
    return list(WIRED) + ([] if wired_only else list(STUBS))


def screen(ctx: DesignContext) -> list:
    """Synthesize every wired architecture and return their results."""
    return [a.synthesize(ctx) for a in WIRED]


def score(results: list, preference_bonus: dict | None = None) -> list:
    """Rank results (feasible first) with a configurable folded-horn bonus.

    The score here is a *reported* composite; hard rejection gates are enforced
    elsewhere and are not affected by the bonus.
    """
    bonus = dict(PREFERENCE_BONUS if preference_bonus is None else preference_bonus)
    scored = []
    for r in results:
        m = r.metrics or {}
        base = _num(m.get("spl_mean_db", m.get("spl_mean_band_db")))
        flat_pen = _num(m.get("spl_variation_db", m.get("spl_variation_band_db")))
        comp = base - flat_pen + 100.0 * bonus.get(r.architecture_id, 0.0)
        scored.append({"architecture_id": r.architecture_id, "display_name": r.display_name,
                       "fidelity": r.fidelity, "feasible": r.feasible,
                       "score": round(comp, 3),
                       "spl_mean_db": m.get("spl_mean_db"),
                       "spl_variation_db": m.get("spl_variation_db"),
                       "preference_bonus": bonus.get(r.architecture_id, 0.0),
                       "implementation": r.implementation})
    scored.sort(key=lambda d: (not d["feasible"], -d["score"]))
    return scored


def _num(v) -> float:
    try:
        f = float(v)
        return f if f == f else 0.0     # guard NaN
    except (TypeError, ValueError):
        return 0.0
