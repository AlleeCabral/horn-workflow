"""The shared test fixtures must work on a clean checkout (audit T1, T2).

Two failures motivated these tests:

* T1 - ``tests/test_app_api.py`` built its ``project`` fixture from a real
  ``runs/run_*`` folder.  ``runs/`` is generated output and is git ignored, so a
  fresh clone (and CI) had no run to copy: all 34 app tests errored with
  ``ValueError: max() iterable argument is empty``.
* T2 - ``tests/test_theory.py`` counted failures in a module global, so under
  pytest a failing physics check still produced a green test.

Run standalone:  python3 -m pytest tests/test_fixtures.py -q
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_project_fixture_needs_no_repo_runs_folder(project):
    """A real run, made by the pipeline itself, is enough."""
    proj, run_id = project
    assert (proj / "runs" / run_id / "state.json").is_file()
    assert run_id.startswith("run_")
    # the fixture copies from a temporary run, never from the repository
    assert not (ROOT / "runs" / run_id).exists()


def test_pipeline_run_fixture_is_a_complete_run(pipeline_run):
    assert (pipeline_run / "state.json").is_file()
    assert (pipeline_run / "deliverables" / "report.md").is_file()


def test_theory_check_raises_under_pytest():
    """A failing check must fail the pytest test, not just print FAIL."""
    import tests.test_theory as tt

    with pytest.raises(AssertionError):
        tt.check("deliberate", False, strict=True)


def test_theory_check_still_prints_when_not_strict():
    import tests.test_theory as tt

    tt.check("deliberate, not strict", False, strict=False)
    assert "deliberate, not strict" in tt.FAILURES
    tt.FAILURES.remove("deliberate, not strict")


def test_copy_exports_ages_the_run_manifest(pipeline_run, tmp_path):
    """Fixture exports dated September 2026 must look newer than the inputs."""
    from conftest import copy_exports

    run = tmp_path / "copy"
    shutil.copytree(pipeline_run, run)
    dest = copy_exports(run)
    names = sorted(p.name for p in dest.glob("*.vips"))
    assert names, "no fixture exports were copied"
    assert all(n.startswith("Akabak-Rad1_23Sept26-") for n in names)

    man = json.loads((run / "deliverables" / "bem" / "bem_manifest.json")
                     .read_text(encoding="utf-8"))
    assert man["generated_utc"] == "2026-09-01T00:00:00Z"