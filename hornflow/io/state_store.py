"""Persistence for the versioned design state (atomic JSON, one locked writer).

Every ``state.json`` write in the project goes through this module (audit S1).
:data:`STATE_LOCK` is a process wide re-entrant lock, so a read-modify-write
cannot interleave with another one and silently drop a change: the app server
handles requests on several threads, and the CLI and the tests write the same
files.
"""

from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Callable, TypeVar

from ..domain.state import DesignState, load_state
from .artifacts import atomic_write

T = TypeVar("T")

LOG = logging.getLogger(__name__)

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


def run_input_path(run_dir: str | Path, state: DesignState) -> Path:
    """The definition this run was started from: its own snapshot when it has one.

    A 1.2 run copied its definition and driver under ``inputs/`` at start, so the
    answer never depends on a file that can be edited or moved afterwards.  A
    1.1 run has no snapshot; it is answered with the path it recorded, and the
    caller is told that the run is not reproducible (audit S7).
    """
    run = state.run or {}
    inputs = run.get("inputs") or {}
    if inputs.get("definition"):
        return Path(run_dir) / inputs["definition"]
    original = run.get("input_path") or state.project.get("input_path") or ""
    if not original:
        raise ValueError("this run records no definition path; it cannot be reproduced")
    LOG.warning(
        "run %s predates schema 1.2: it has no input snapshot, so it is not "
        "reproducible and its recorded definition path is used",
        run.get("run_id") or Path(run_dir).name)
    return Path(original)


def run_params(run_dir: str | Path, state: DesignState):
    """The design parameters a run was built from, read from its own snapshot.

    Loading a snapshot is not the same as loading a definition: a driver next to
    it wins over an absolute reference, so a copied run cannot read a driver
    from outside itself.  A 1.1 run has no snapshot and keeps the plain rule.
    """
    from .. import config                    # local: io stays importable alone

    inputs = (state.run or {}).get("inputs") or {}
    return config.load(run_input_path(run_dir, state), snapshot=bool(inputs))


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
