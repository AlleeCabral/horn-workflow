"""Structured JSONL stage logs.

Each line records: run_id, stage, candidate_id, event, severity, duration,
cache status and artifact locations - the observability contract from the spec.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from pathlib import Path

from ..domain.evidence import now_utc
from .artifacts import atomic_write


@dataclass
class LogRecord:
    run_id: str
    stage: str
    event: str
    severity: str = "info"
    candidate_id: str | None = None
    duration_s: float | None = None
    cache: str | None = None
    artifacts: list = field(default_factory=list)
    detail: str = ""
    utc: str = field(default_factory=now_utc)

    def to_dict(self) -> dict:
        return asdict(self)


class StageLogger:
    """Append-only JSONL logger writing atomically at close."""

    def __init__(self, run_dir: str | Path, run_id: str) -> None:
        self.path = Path(run_dir) / "logs.jsonl"
        self.run_id = run_id
        self.records: list[LogRecord] = []

    def log(self, stage: str, event: str, *, severity: str = "info",
            candidate_id: str | None = None, duration_s: float | None = None,
            cache: str | None = None, artifacts: list | None = None,
            detail: str = "") -> LogRecord:
        rec = LogRecord(run_id=self.run_id, stage=stage, event=event,
                        severity=severity, candidate_id=candidate_id,
                        duration_s=duration_s, cache=cache,
                        artifacts=list(artifacts or []), detail=detail)
        self.records.append(rec)
        return rec

    def flush(self) -> Path:
        text = "\n".join(json.dumps(r.to_dict(), sort_keys=True) for r in self.records)
        atomic_write(self.path, (text + "\n").encode("utf-8"))
        return self.path
