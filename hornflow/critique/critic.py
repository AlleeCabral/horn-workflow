"""Independent critic (Stage 14).

An adversarial check that runs before the final recommendation and may reject
it.  It verifies hard constraints, units, provenance, evidence labelling and
that folds / variants were compared against the ideal reference.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict


@dataclass
class Finding:
    check: str
    passed: bool
    detail: str = ""
    severity: str = "info"     # info | warning | reject

    def to_dict(self) -> dict:
        return asdict(self)


def review(state, *, gates, runs, fold_candidates, variants, scores) -> list:
    findings = []

    # 1. hard gates
    failed = [g.name for g in gates if not g.passed]
    findings.append(Finding(
        "hard_constraints", not failed,
        "all hard gates passed" if not failed else "failed: " + ", ".join(failed),
        "reject" if failed else "info"))

    # 2. provenance on every simulation run
    missing = [r.candidate_id for r in runs
               if not getattr(r, "solver", None) or not getattr(r, "solver_version", None)]
    findings.append(Finding("provenance", not missing,
                            "every run carries solver+version" if not missing
                            else f"missing on {len(missing)} run(s)"))

    # 3. evidence labels present (no estimate masquerading as simulation)
    ok_labels = all(getattr(r, "fidelity", "") for r in runs)
    findings.append(Finding("evidence_labels", ok_labels,
                            "every run carries a fidelity label"))

    # 4. every fold compared against the ideal reference (area law)
    bad_folds = [f.fold_id for f in fold_candidates if f.area_report is None]
    findings.append(Finding("fold_vs_reference", not bad_folds,
                            "every fold carries an area-law report vs the master"
                            if not bad_folds else f"{len(bad_folds)} fold(s) missing area report",
                            "reject" if bad_folds else "info"))

    # 5. manufacturing variants revalidated against the master
    bad_var = [v.variant_id for v in variants
               if "area_law_rms" not in (v.deviations or {})]
    findings.append(Finding("variant_revalidation", not bad_var,
                            "every variant reports area-law deviation"
                            if not bad_var else f"{len(bad_var)} variant(s) unvalidated"))

    # 6. folded horn not chosen *only* because of preference
    findings.append(_preference_check(scores))

    # 7. a SCREENING_ONLY architecture must not silently beat a simulated one
    findings.append(_fidelity_check(scores))

    return findings


def _preference_check(scores) -> Finding:
    if not scores:
        return Finding("preference_not_decisive", True, "no scored candidates")
    by_raw = sorted(scores, key=lambda s: -(s["score"] - 100.0 * s["preference_bonus"]))
    by_bonus = sorted(scores, key=lambda s: -s["score"])
    raw_win = by_raw[0]["architecture_id"]
    bonus_win = by_bonus[0]["architecture_id"]
    if bonus_win == "folded_horn" and raw_win != "folded_horn":
        return Finding("preference_not_decisive", False,
                       f"folded horn wins only with the preference bonus "
                       f"(uncorrected winner: {raw_win})", "warning")
    return Finding("preference_not_decisive", True,
                   f"winner {bonus_win} also wins without the bonus")


def rejected(findings) -> bool:
    return any(f.severity == "reject" and not f.passed for f in findings)


def _fidelity_check(scores) -> Finding:
    if not scores:
        return Finding("fidelity_flag", True, "no scored candidates")
    win = scores[0]
    simulated = any(s["fidelity"] != "SCREENING_ONLY" for s in scores)
    if win["fidelity"] == "SCREENING_ONLY" and simulated:
        return Finding("fidelity_flag", False,
                       f"winner {win['architecture_id']} is SCREENING_ONLY while "
                       f"simulated candidates exist", "warning")
    return Finding("fidelity_flag", True,
                   f"winner {win['architecture_id']} fidelity {win['fidelity']}")
