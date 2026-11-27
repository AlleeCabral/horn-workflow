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

# Preference bonus for the preferred (folded horn) class, in score points.  The
# reported composite is dominated by dB, so one point is a tie-breaker, never a
# head start (decision D4).  It is only ever added to a candidate that the raw
# scores cannot separate from the leader (see :func:`score`).
PREFERENCE_BONUS = {"folded_horn": 1.0}

# Two feasible candidates whose raw scores differ by less than this cannot be
# separated by the reported composite: the run reports a tie (decision D4).
TIE_TOLERANCE_POINTS = 0.5


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
    elsewhere and are not affected by the bonus.  ``raw_score`` is the same
    composite without the bonus, so a caller can tell a real lead from a
    preference-decided one (decision D4).

    The bonus is added **only** to a feasible candidate whose raw score is
    within :data:`TIE_TOLERANCE_POINTS` of the raw leader.  A candidate that is
    behind by that much or more is never reordered, so preference can break a
    tie but never overrule the acoustic evidence (decision D4).
    """
    bonus = dict(PREFERENCE_BONUS if preference_bonus is None else preference_bonus)
    scored = []
    for r in results:
        m = r.metrics or {}
        base = _num(m.get("spl_mean_db", m.get("spl_mean_band_db")))
        flat_pen = _num(m.get("spl_variation_db", m.get("spl_variation_band_db")))
        raw = base - flat_pen
        scored.append({"architecture_id": r.architecture_id, "display_name": r.display_name,
                       "fidelity": r.fidelity, "feasible": r.feasible,
                       "score": round(raw, 3),
                       "raw_score": round(raw, 3),
                       "spl_mean_db": m.get("spl_mean_db"),
                       "spl_variation_db": m.get("spl_variation_db"),
                       "preference_bonus": 0.0,
                       "implementation": r.implementation})
    feasible = [s["raw_score"] for s in scored if s["feasible"]]
    leader = max(feasible) if feasible else None
    for s in scored:
        extra = bonus.get(s["architecture_id"], 0.0)
        if not extra or leader is None or not s["feasible"]:
            continue
        if leader - s["raw_score"] < TIE_TOLERANCE_POINTS:
            s["score"] = round(s["raw_score"] + extra, 3)
            s["preference_bonus"] = extra
    scored.sort(key=lambda d: (not d["feasible"], -d["score"]))
    return scored


def decisive_winner(scores: list) -> str | None:
    """The raw-score leader, or None when the top two feasible scores are a tie.

    The question this answers is "does the acoustic evidence pick a winner", so
    the bonus is ignored and the two leaders are compared against
    :data:`TIE_TOLERANCE_POINTS` (decision D4).
    """
    feasible = sorted((s for s in scores if s.get("feasible")),
                      key=lambda s: -_num(s.get("raw_score", s.get("score"))))
    if not feasible:
        return None
    if len(feasible) > 1:
        lead = _num(feasible[0].get("raw_score", feasible[0].get("score")))
        chase = _num(feasible[1].get("raw_score", feasible[1].get("score")))
        if lead - chase < TIE_TOLERANCE_POINTS:
            return None
    return feasible[0]["architecture_id"]


def _num(v) -> float:
    try:
        f = float(v)
        return f if f == f else 0.0     # guard NaN
    except (TypeError, ValueError):
        return 0.0
