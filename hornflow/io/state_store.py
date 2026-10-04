"""Persistence for the versioned design state (atomic JSON)."""

from __future__ import annotations

import json
from pathlib import Path

from ..domain.state import DesignState, load_state
from .artifacts import atomic_write


def save_state(state: DesignState, path: str | Path) -> Path:
    path = Path(path)
    atomic_write(path, (json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n")
                 .encode("utf-8"))
    return path


def load_state_file(path: str | Path) -> DesignState:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return load_state(raw)
