"""Shared fixtures for the whole test suite.

Why this file exists (audit findings T1 and T2):

* ``tests/test_app_api.py`` used to build its ``project`` fixture by copying a
  real ``runs/run_*`` folder from the repository.  ``runs/`` is generated output
  and is git ignored, so a clean checkout had no run to copy and every app test
  errored with ``ValueError: max() iterable argument is empty``.  The pipeline is
  now run once per session into a temporary folder instead, which makes the
  suite self-contained and still exercises real output.
* The app tests share one way of building ``AppActions`` and one way of touching
  ``state.json``, so the tests cannot drift from the production call path.

Nothing here writes into the repository.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from hornflow.app.actions import ACCEPT_REASONS, ApiError, AppActions  # noqa: E402
from hornflow.io.artifacts import atomic_write                          # noqa: E402
from hornflow.io.state_store import load_state_file                     # noqa: E402
from hornflow.workflow.orchestrator import run_pipeline                 # noqa: E402

BASE_DEFINITION = "params/horn_jbl_1200b.yaml"
BEM_FIXTURES = ROOT / "tests" / "fixtures" / "bem_export"
BEM_MANIFEST = Path("deliverables") / "bem" / "bem_manifest.json"

__all__ = ["ACCEPT_REASONS", "ApiError", "AppActions", "copy_exports",
           "load_state_file", "project", "pipeline_run", "update_state"]


@contextmanager
def _in_repo_root():
    """Run with the repository root as the working directory, then restore it."""
    previous = Path.cwd()
    os.chdir(ROOT)
    try:
        yield
    finally:
        os.chdir(previous)


@pytest.fixture(scope="session")
def pipeline_run(tmp_path_factory) -> Path:
    """One real run of the shipped example, in a temp folder.

    The pipeline writes a complete run directory (state, stages, deliverables),
    so any test that needs a run gets the same shape the app sees in production,
    and the repository never needs a ``runs/`` folder.
    """
    out_root = tmp_path_factory.mktemp("runs")
    with _in_repo_root():
        summary = run_pipeline(BASE_DEFINITION, out_root=out_root)
    run_dir = Path(summary["run_dir"])
    assert (run_dir / "state.json").is_file(), "the fixture run has no state"
    return run_dir


@pytest.fixture
def project(tmp_path, pipeline_run) -> tuple[Path, str]:
    """A throwaway project: a copy of params/ plus a copy of the fixture run."""
    proj = tmp_path / "proj"
    shutil.copytree(ROOT / "params", proj / "params")
    run_id = pipeline_run.name
    shutil.copytree(pipeline_run, proj / "runs" / run_id)
    return proj, run_id


def _actions(project, *, runner=None, run_dir=None) -> AppActions:
    """The one way tests build the action surface."""
    proj, run_id = project
    return AppActions(proj, base_definition=proj / "params" / "horn_jbl_1200b.yaml",
                      run_dir=(run_dir if run_dir is not None
                               else proj / "runs" / run_id),
                      author="tester", runner=runner)


def update_state(path, fn):
    """Locked read-modify-write of a state file.

    Imported lazily so this module can be imported before the locked writer
    lands (Phase 0 Task 2, audit S1).
    """
    from hornflow.io.state_store import update_state as _update
    return _update(path, fn)


def copy_exports(run_dir, pattern: str = "Akabak-Rad1_23Sept26-*") -> Path:
    """Copy the fixture ``.vips`` exports into a run and age its manifest.

    The fixture exports carry September 2026 timestamps in their headers, so the
    run manifest's ``generated_utc`` is moved back to 2026-09-01.  Without that,
    the import validation in Phase 0 Task 6 would reject every fixture as older
    than the generated inputs.
    """
    run_dir = Path(run_dir)
    dest = run_dir / "deliverables" / "bem" / "export"
    dest.mkdir(parents=True, exist_ok=True)
    copied = []
    for src in sorted(BEM_FIXTURES.glob(pattern)):
        shutil.copy2(src, dest / src.name)
        copied.append(src.name)
    if not copied:
        raise FileNotFoundError(f"no fixture export matches {pattern} in {BEM_FIXTURES}")
    _set_manifest_generated(run_dir, "2026-09-01T00:00:00Z")
    return dest


def _set_manifest_generated(run_dir: Path, stamp: str) -> None:
    man = run_dir / BEM_MANIFEST
    if not man.is_file():
        raise FileNotFoundError(f"the run has no BEM manifest at {man}")
    raw = json.loads(man.read_text(encoding="utf-8"))
    raw["generated_utc"] = stamp
    atomic_write(man, (json.dumps(raw, indent=2, sort_keys=True) + "\n")
                 .encode("utf-8"))
