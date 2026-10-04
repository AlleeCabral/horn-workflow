"""Artifact and provenance management.

* Atomic writes (temp file + ``os.replace``) so a crash never leaves a half
  written artifact.
* Content addressing: every artifact records its SHA-256.
* Prior successful runs are never overwritten: each run lives in its own
  ``runs/<run_id>`` directory and a run id is never reused.
* Intermediate artifacts live under ``stages/``; final deliverables under
  ``deliverables/``.
"""

from __future__ import annotations

import json
import os
import hashlib
from dataclasses import dataclass, asdict
from pathlib import Path

from ..domain.evidence import now_utc


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    """Write bytes to ``path`` atomically (same-directory temp + rename)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    with open(tmp, "wb") as fh:
        fh.write(data)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


@dataclass
class ArtifactRef:
    run_id: str
    stage: str
    kind: str
    path: str            # relative to the run directory
    sha256: str
    bytes: int
    created_utc: str
    candidate_id: str | None = None
    evidence: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class ArtifactStore:
    """Content-addressed store rooted at one run directory."""

    def __init__(self, run_dir: str | Path, run_id: str) -> None:
        self.run_dir = Path(run_dir)
        self.run_id = run_id
        (self.run_dir / "stages").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "deliverables").mkdir(parents=True, exist_ok=True)
        (self.run_dir / "cache").mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- writes
    def put(self, data: bytes, *, kind: str, name: str, stage: str,
            area: str = "stages", candidate_id: str | None = None,
            evidence: str | None = None) -> ArtifactRef:
        rel = Path(area) / stage / name if area == "stages" else Path(area) / name
        target = self.run_dir / rel
        if target.exists() and sha256_file(target) != hashlib.sha256(data).hexdigest():
            # never clobber a different artifact under the same name
            stem, suf = target.stem, target.suffix
            i = 1
            while target.exists():
                target = target.with_name(f"{stem}.{i}{suf}")
                i += 1
            rel = target.relative_to(self.run_dir)
        atomic_write(target, data)
        return ArtifactRef(
            run_id=self.run_id, stage=stage, kind=kind, path=str(rel),
            sha256=hashlib.sha256(data).hexdigest(), bytes=len(data),
            created_utc=now_utc(), candidate_id=candidate_id, evidence=evidence)

    def put_text(self, text: str, **kw) -> ArtifactRef:
        return self.put(text.encode("utf-8"), **kw)

    def put_json(self, obj, **kw) -> ArtifactRef:
        return self.put_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", **kw)

    def put_csv(self, header: list, rows: list, **kw) -> ArtifactRef:
        lines = [",".join(str(h) for h in header)]
        for r in rows:
            lines.append(",".join(_fmt(v) for v in r))
        return self.put_text("\n".join(lines) + "\n", **kw)

    # ----------------------------------------------------------------- cache
    def cache_key(self, payload) -> str:
        from ..domain.ids import canonical_json
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()

    def cache_get(self, key: str) -> Path | None:
        p = self.run_dir / "cache" / key
        return p if p.exists() else None

    def cache_put(self, key: str, data: bytes) -> Path:
        p = self.run_dir / "cache" / key
        atomic_write(p, data)
        return p


def _fmt(v) -> str:
    if isinstance(v, float):
        return repr(round(v, 9))
    return str(v)


def new_run_id(prefix: str = "run") -> str:
    """A unique, sortable run id (UTC timestamp + short random suffix)."""
    import uuid
    stamp = now_utc().replace(":", "").replace("-", "")
    return f"{prefix}_{stamp}_{uuid.uuid4().hex[:6]}"
