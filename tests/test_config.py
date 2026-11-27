"""A definition is validated before anything runs (audit P12, U7, P10 partial).

The typo ``lenght:`` used to be ignored, a throat in metres turned into a
"best overall: sealed box" answer with exit status 0, a quoted ``"false"`` meant
True, and a bad YAML left a half-written run directory behind.  These tests pin
the validation, the CLI exit codes and the advise fix.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow import cli, config                                         # noqa: E402
from hornflow.config import ConfigError                                  # noqa: E402

EXAMPLE = "horn_jbl_1200b.yaml"


def _copy_def(tmp_path, edit):
    """Copy ``params/`` and hand the definition to ``edit`` as a dict.

    The driver reference is inlined, so a ``driver.*`` edit changes this file
    instead of a separate driver file.
    """
    import shutil

    root = tmp_path / "params"
    shutil.copytree(ROOT / "params", root)
    path = root / EXAMPLE
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    ref = raw.get("driver")
    if isinstance(ref, str):
        raw["driver"] = yaml.safe_load((root / "drivers" / ref).read_text(encoding="utf-8"))
    edit(raw)
    path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
    return path


def _set(dotted, value):
    """Return an edit that sets one dotted item."""
    def edit(raw):
        node = raw
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return edit


# ------------------------------------------------------------------ the schema
def test_unknown_key_is_rejected(tmp_path):
    p = _copy_def(tmp_path, lambda d: d["horn"].update(lenght=1500))
    with pytest.raises(ConfigError,
                       match=r"unknown key 'horn\.lenght' \(did you mean 'horn\.length'\?\)"):
        config.load(p)


@pytest.mark.parametrize("path,value,msg", [
    ("horn.throat_diameter", 0.26, "looks like metres"),
    ("driver.Mms", float("nan"), "must be finite"),
    ("simulation.observation_distance", 0, "must be > 0"),
    ("simulation.half_space", "false", "must be true or false"),
])
def test_bad_values_are_rejected(tmp_path, path, value, msg):
    with pytest.raises(ConfigError, match=msg):
        config.load(_copy_def(tmp_path, _set(path, value)))


def test_the_cli_names_the_first_error_and_counts_the_rest(tmp_path):
    """Every problem is counted; the first one is the line the user reads."""
    edit = _set("simulation.observation_distance", 0)
    p = _copy_def(tmp_path, lambda d: (edit(d), d["horn"].update(lenght=1500)))
    with pytest.raises(ConfigError) as info:
        config.load(p)
    assert len(info.value.errors) == 2
    lines = config.error_lines(info.value)
    assert lines[0] == f"error: {info.value.errors[0]}"
    assert lines[1] == "(+1 more)"


def test_both_example_definitions_load():
    for path in sorted((ROOT / "params").glob("*.yaml")):
        config.load(path)                        # no error = accepted


# ---------------------------------------------------------------------- the CLI
def test_cli_bad_yaml_leaves_no_run_dir(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("horn: [", encoding="utf-8")
    rc = cli.main([str(bad), "--out", str(tmp_path / "runs")])
    assert rc == 2
    assert not (tmp_path / "runs").exists()
    err = capsys.readouterr().err.strip().splitlines()
    assert len(err) == 1 and err[0].startswith("error:")


def test_cli_returns_1_when_a_stage_did_not_pass(tmp_path, monkeypatch, capsys):
    summary = {"run_id": "r", "best_folded": "u_fold", "best_overall": "folded_horn",
               "n_fold_candidates": 1, "report": "report.md", "viewer": "viewer.html",
               "stages": {"input_audit": {"status": "passed"},
                          "physical_feasibility": {"status": "blocked"}}}
    monkeypatch.setattr(cli, "run_pipeline", lambda *a, **k: summary)
    rc = cli.main([str(tmp_path / "definition.yaml"), "--out", str(tmp_path / "runs")])
    assert rc == 1
    out = capsys.readouterr().out
    assert "passed   input_audit" in out
    assert "blocked  physical_feasibility" in out


# -------------------------------------------------------------------- the advise
def test_advised_candidates_are_simulated_as_exponential():
    """The closed form is exponential-only, so the simulation must be too (P10)."""
    from hornflow import advise

    cand = advise.Candidate(fc=62.0, k_rm=0.81, depth=1.5, mouth_area=1.6,
                            mouth_width=1.6, mouth_height=1.0, fits=True)
    overrides = advise._candidate_overrides(cand, 1.6)
    assert overrides["horn.profile"] == "exponential"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
