"""State file writes must survive threads and must never lose an update (audit S1).

Two defects motivated these tests:

* ``atomic_write`` used ``<name>.tmp.<pid>`` as its temporary file, so two
  threads of the same process shared one temp path: one thread renamed it away
  and the other crashed in ``os.replace`` with ``FileNotFoundError``.
* ``state.json`` had no read-modify-write primitive, so two app requests could
  load the same state, each add its change and each save: the later save erased
  the other request's change.

Run standalone:  python3 -m pytest tests/test_state_store.py -q
"""

from __future__ import annotations

import json
import shutil
import threading

from hornflow.io.artifacts import atomic_write
from hornflow.io.state_store import load_state_file, update_state


def test_concurrent_atomic_writes_never_fail(tmp_path):
    """Four threads, one target path: every write must land, none may raise."""
    target = tmp_path / "x.json"
    errors = []

    def work(i):
        for _ in range(100):
            try:
                atomic_write(target, f'{{"i": {i}}}'.encode())
            except Exception as e:  # noqa: BLE001 - the test reports any failure
                errors.append(e)

    ts = [threading.Thread(target=work, args=(i,)) for i in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == []
    assert json.loads(target.read_text())["i"] in range(4)
    # no temporary file is left behind (stricter than the plan's glob)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["x.json"]


def test_atomic_write_leaves_no_temp_file_on_error(tmp_path, monkeypatch):
    """A failed write must not leave a half written temp file behind."""
    target = tmp_path / "x.json"

    class Boom(Exception):
        pass

    def explode(*args, **kwargs):
        raise Boom("disk full")

    monkeypatch.setattr("os.replace", explode)
    try:
        atomic_write(target, b'{"i": 1}')
    except Boom:
        pass
    assert list(tmp_path.iterdir()) == []


def test_update_state_serialises_read_modify_write(pipeline_run, tmp_path):
    """100 appends from 4 threads must all survive."""
    run = tmp_path / "run"
    shutil.copytree(pipeline_run, run)
    p = run / "state.json"

    def add(n):
        for k in range(25):
            update_state(p, lambda st: st.decision_log.append({"event": f"t{n}-{k}"}))

    ts = [threading.Thread(target=add, args=(n,)) for n in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    events = [e["event"] for e in load_state_file(p).decision_log]
    assert sum(e.startswith("t") for e in events) == 100


def test_update_state_returns_the_result_of_fn(pipeline_run, tmp_path):
    run = tmp_path / "run"
    shutil.copytree(pipeline_run, run)
    p = run / "state.json"
    out = update_state(p, lambda st: (len(st.decision_log), st.run.get("run_id")))
    assert out[0] == len(load_state_file(p).decision_log)
    assert out[1] == pipeline_run.name


# --------------------------------------------------------------------------- #
#  which definition a run was made from (audit S7)
# --------------------------------------------------------------------------- #
def test_run_input_path_prefers_the_snapshot_and_warns_without_one(tmp_path, caplog):
    from hornflow.domain.state import DesignState
    from hornflow.io.state_store import run_input_path

    run_dir = tmp_path / "run"
    st = DesignState()
    st.run = {"inputs": {"definition": "inputs/definition.yaml"}}
    assert run_input_path(run_dir, st) == run_dir / "inputs" / "definition.yaml"

    original = tmp_path / "original.yaml"
    old = DesignState()
    old.run = {"run_id": "run_old", "input_path": str(original)}
    with caplog.at_level("WARNING"):
        assert run_input_path(run_dir, old) == original
    assert "not reproducible" in caplog.text
