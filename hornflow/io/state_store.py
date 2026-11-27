"""Persistence for the versioned design state (atomic JSON, one locked writer).

Every ``state.json`` write in the project goes through this module (audit S1).
:data:`STATE_LOCK` is a process wide re-entrant lock, so a read-modify-write
cannot interleave with another one and silently drop a change: the app server
handles requests on several threads, and the CLI and the tests write the same
files.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Callable, TypeVar

from ..domain.state import DesignState, load_state
from .artifacts import atomic_write

T = TypeVar("T")

STATE_LOCK = threading.RLock()


def save_state(state: DesignState, path: str | Path) -> Path:
    path = Path(path)
    data = (json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n").encode("utf-8")
    with STATE_LOCK:
        atomic_write(path, data)
    return path


def load_state_file(path: str | Path) -> DesignState:
    path = Path(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return load_state(raw)


def update_state(path: str | Path, fn: Callable[[DesignState], T]) -> T:
    """Load, apply ``fn``, save and return whatever ``fn`` returned.

    Held under :data:`STATE_LOCK` for the whole load-modify-save cycle, which is
    the only way an update cannot be lost.
    """
    path = Path(path)
    with STATE_LOCK:
        state = load_state_file(path)
        result = fn(state)
        save_state(state, path)
    return result
