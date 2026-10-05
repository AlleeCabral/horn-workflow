"""Versioned, machine-readable authoritative design state.

Standard-library dataclasses (no third-party schema library) so the production
path stays lean, per the dependency policy.  State is versioned; loading an
unknown or older version without a registered migration is a hard error - the
system never silently reinterprets an old state file.

Every stage reads a validated ``DesignState`` and writes only its documented
fields.  ``run.stages`` records per-stage status and provenance.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Callable

from .evidence import now_utc
from .limits import LimitImpact

SCHEMA_VERSION = "1.1"


# --------------------------------------------------------------------------- #
#  schema 1.0 -> 1.1 : the excursion column was named as if it were peak
# --------------------------------------------------------------------------- #
# In 1.0 ``simulation_runs[].excursion_m`` held **rms** displacement (the solver
# is driven in volts rms) under a name that implied peak travel.  The values are
# correct and are left exactly as they were; only the name changes, and the
# derived one-way peak column is added.  See hornflow.domain.excursion.
EXCURSION_MIGRATION_NOTE = (
    "simulation_runs[].excursion_m held rms displacement under a name that "
    "implied peak. Renamed to excursion_rms_m and excursion_peak_m = "
    "sqrt(2) x rms added; values unchanged (never reinterpreted)."
)


def _migrate_1_0_to_1_1(d: dict) -> dict:
    """Rename the ambiguous excursion key and derive the explicit peak column."""
    from .excursion import RMS_TO_PEAK

    out = dict(d)
    runs = []
    for run in (out.get("simulation_runs") or []):
        run = dict(run)
        if "excursion_m" in run:
            rms = run.pop("excursion_m")
            run["excursion_rms_m"] = rms
            if isinstance(rms, list):
                run["excursion_peak_m"] = [RMS_TO_PEAK * float(v) for v in rms]
        runs.append(run)
    out["simulation_runs"] = runs
    mig = list(out.get("migrations") or [])
    mig.append({"from_schema": "1.0", "to_schema": "1.1",
                "detail": EXCURSION_MIGRATION_NOTE})
    out["migrations"] = mig
    out["schema_version"] = "1.1"
    return out


def _ser(obj: Any) -> Any:
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    if isinstance(obj, list):
        return [_ser(o) for o in obj]
    if isinstance(obj, dict):
        return {k: _ser(v) for k, v in obj.items()}
    return obj


# Top-level fields, in the order the spec lists them (plus ``stages``).
STATE_FIELDS = (
    "schema_version", "migrations", "run", "project", "requirements", "driver",
    "constraints",
    "limit_impacts", "feasibility", "architecture_candidates",
    "acoustic_candidates", "reference_profiles", "fold_candidates",
    "simulation_runs", "sensitivity_runs", "manufacturing_variants",
    "visualization_artifacts", "validation", "critic_findings",
    "decision_log", "final_recommendations", "stages",
)


@dataclass
class DesignState:
    schema_version: str = SCHEMA_VERSION
    migrations: list = field(default_factory=list)   # applied state migrations
    run: dict = field(default_factory=dict)
    project: dict = field(default_factory=dict)
    requirements: dict = field(default_factory=dict)
    driver: dict = field(default_factory=dict)
    constraints: dict = field(default_factory=dict)
    limit_impacts: list = field(default_factory=list)          # [LimitImpact]
    feasibility: dict = field(default_factory=dict)
    architecture_candidates: list = field(default_factory=list)
    acoustic_candidates: list = field(default_factory=list)
    reference_profiles: list = field(default_factory=list)
    fold_candidates: list = field(default_factory=list)
    simulation_runs: list = field(default_factory=list)
    sensitivity_runs: list = field(default_factory=list)
    manufacturing_variants: list = field(default_factory=list)
    visualization_artifacts: list = field(default_factory=list)
    validation: dict = field(default_factory=dict)
    critic_findings: list = field(default_factory=list)
    decision_log: list = field(default_factory=list)
    final_recommendations: dict = field(default_factory=dict)
    stages: dict = field(default_factory=dict)                 # stage -> status

    # ------------------------------------------------------------------ mutate
    def log(self, stage: str, event: str, **fields: Any) -> None:
        """Append a structured decision-log entry."""
        entry = {"utc": now_utc(), "stage": stage, "event": event}
        entry.update(fields)
        self.decision_log.append(entry)

    def set_stage(self, stage: str, status: str, detail: str = "",
                  failure: Any = None) -> None:
        rec = {"status": status, "updated_utc": now_utc(), "detail": detail}
        if failure is not None:
            rec["failure"] = _ser(failure)
        self.stages[stage] = rec

    def stage_status(self, stage: str) -> str:
        return str(self.stages.get(stage, {}).get("status", "pending"))

    # ------------------------------------------------------------------ serial
    def to_dict(self) -> dict:
        out: dict = {}
        for f in STATE_FIELDS:
            out[f] = _ser(getattr(self, f))
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "DesignState":
        st = cls()
        for f in STATE_FIELDS:
            if f in d and d[f] is not None:
                setattr(st, f, d[f])
        # re-type the limit impacts
        st.limit_impacts = [LimitImpact(**li) if isinstance(li, dict) else li
                            for li in st.limit_impacts]
        if st.schema_version != SCHEMA_VERSION:
            raise ValueError(
                f"state schema_version {st.schema_version!r} is not {SCHEMA_VERSION!r}; "
                "migrate it explicitly (see MIGRATIONS)")
        return st


# --------------------------------------------------------------------------- #
#  migrations
# --------------------------------------------------------------------------- #
# version -> function(state_dict) -> state_dict at the NEXT version.
# Populated as the schema evolves.  Loading a version with no path to the
# current one must fail loudly.
MIGRATIONS: dict[str, Callable[[dict], dict]] = {
    "1.0": _migrate_1_0_to_1_1,
}


def load_state(d: dict) -> DesignState:
    """Validate and (if needed) migrate a raw state dict into a DesignState."""
    ver = str(d.get("schema_version", ""))
    if ver == SCHEMA_VERSION:
        return DesignState.from_dict(d)
    # walk migrations from `ver` forward
    guard = 0
    cur = d
    while str(cur.get("schema_version")) != SCHEMA_VERSION:
        guard += 1
        if guard > 50:
            raise ValueError("state migration did not converge")
        fn = MIGRATIONS.get(str(cur.get("schema_version")))
        if fn is None:
            raise ValueError(
                f"no migration registered from schema_version "
                f"{cur.get('schema_version')!r} to {SCHEMA_VERSION!r}")
        cur = fn(cur)
    return DesignState.from_dict(cur)
