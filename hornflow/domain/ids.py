"""Deterministic, reproducible identifiers.

A candidate / artifact id must be identical for identical inputs on any machine
and in any run order.  We hash a canonical JSON rendering of the *normalized*
payload (SI units, sorted keys, fixed separators) with SHA-1 and keep 16 hex
characters.  SHA-1 is used only as a short content fingerprint, never for
security.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> str:
    """Stable JSON: sorted keys, no incidental whitespace, floats rounded.

    Floats are rounded to 12 significant digits so that harmless binary
    representation noise (e.g. 0.1 + 0.2) cannot change an identifier.
    """
    return json.dumps(_norm(obj), sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True)


def _norm(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _norm(v) for k, v in sorted(obj.items(), key=lambda kv: str(kv[0]))}
    if isinstance(obj, (list, tuple)):
        return [_norm(v) for v in obj]
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, float):
        return round(obj, 12) + 0.0
    if isinstance(obj, (int, str)) or obj is None:
        return obj
    # numpy scalars / arrays and anything else -> best effort
    try:
        return round(float(obj), 12) + 0.0
    except (TypeError, ValueError):
        return str(obj)


def stable_id(prefix: str, payload: Any) -> str:
    """Deterministic id like ``cand_3f9a1c2b7d40e5aa`` for a payload."""
    digest = hashlib.sha1(canonical_json(payload).encode("utf-8")).hexdigest()
    return f"{prefix}_{digest[:16]}"


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_of_text(text: str) -> str:
    return sha256_of_bytes(text.encode("utf-8"))
