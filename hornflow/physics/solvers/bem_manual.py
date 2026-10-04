"""Validation and import of the manually exported AKABAK ``.vips`` spectra.

The GUI step is manual (see :mod:`hornflow.physics.solvers.manual`), so the
returned data must be *validated* before it can influence any decision.  This
module checks the eight required properties, then compares the accepted export
with the one-dimensional reference and assigns the manual-solve state.  A
candidate can only reach ``BEM_VALIDATED`` through a passing import *and* a
comparison - never from the mere existence of a solved GUI project.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ... import bem as _bem
from ...domain.evidence import EvidenceLabel
from .manual import MANIFEST_NAME, ManualSolveState, read_manifest

HARD = "hard"
SOFT = "soft"
DEFAULT_TOLERANCE_DB = 6.0
MIN_FREQ_HZ, MAX_FREQ_HZ = 1.0, 1.0e6


@dataclass
class Check:
    name: str
    passed: bool
    detail: str = ""
    severity: str = HARD

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ExportValidation:
    """The outcome of validating one exported-spectra folder."""

    state: str
    passed: bool
    rejected: bool
    checks: list
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    files: list = field(default_factory=list)
    source: str | None = None
    best: dict | None = None
    best_name: str | None = None

    def hard_failures(self) -> list:
        return [c.name for c in self.checks
                if c.severity == HARD and not c.passed]

    def to_dict(self) -> dict:
        return {
            "state": self.state, "passed": self.passed, "rejected": self.rejected,
            "checks": [c.to_dict() if hasattr(c, "to_dict") else c for c in self.checks],
            "hard_failures": self.hard_failures(),
            "warnings": list(self.warnings), "errors": list(self.errors),
            "files": list(self.files), "source": self.source,
        }



# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #
def _parse_utc(text) -> datetime | None:
    try:
        dt = datetime.fromisoformat(str(text))
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _mtime_utc(path: Path) -> datetime:
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)


def _same_dir(a, b) -> bool:
    try:
        ra, rb = Path(a).resolve(), Path(b).resolve()
    except OSError:
        return False
    return ra == rb or rb in ra.parents


def _sha256(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _grid_detail(best) -> tuple:
    if best is None:
        return False, "nothing parsed"
    f = np.asarray(best["freq"], dtype=float)
    if len(f) < 2:
        return False, f"only {len(f)} frequency point(s)"
    if not np.all(np.isfinite(f)):
        return False, "non-finite frequencies"
    if np.any(np.diff(f) <= 0):
        return False, "frequency grid is not strictly increasing"
    if f.min() < MIN_FREQ_HZ or f.max() > MAX_FREQ_HZ:
        return False, f"grid {f.min():g}-{f.max():g} Hz outside {MIN_FREQ_HZ:g}-{MAX_FREQ_HZ:g} Hz"
    return True, f"{len(f)} points, {f.min():g}-{f.max():g} Hz, monotonic"


def _manifest_matches(manifest) -> tuple:
    """Is the manifest on disk the one we were handed, with unchanged inputs?"""
    on_disk = read_manifest(Path(manifest.bem_dir) / MANIFEST_NAME)
    if on_disk is None:
        return False, f"no {MANIFEST_NAME} next to the inputs"
    if on_disk.run_id != manifest.run_id:
        return False, f"manifest run_id {on_disk.run_id!r} != {manifest.run_id!r}"
    changed = []
    for name, rec in (on_disk.files or {}).items():
        p = Path(rec.get("path", ""))
        if not p.is_file():
            changed.append(f"{name}(missing)")
        elif _sha256(p) != rec.get("sha256"):
            changed.append(f"{name}(changed)")
    if changed:
        return False, "inputs changed after generation: " + ", ".join(changed)
    return True, f"run_id {on_disk.run_id!r}, {len(on_disk.files or {})} input hash(es) unchanged"


# --------------------------------------------------------------------------- #
#  validation - the eight required checks
# --------------------------------------------------------------------------- #
def validate_exports(folder, manifest=None, *, slack_s: float = 120.0) -> ExportValidation:
    """Validate an exported-spectra folder against the eight required properties.

    A hard failure does not advance the state machine: the candidate stays at
    ``MANUAL_SOLVE_PENDING`` and the failed checks say what to fix.  Only a
    folder that passes every hard check reaches ``VIPS_IMPORTED``.
    """
    folder = Path(folder)
    files = _bem.candidate_files(folder)
    parsed, errors = _bem.parse_folder(folder)
    checks: list = []

    # 1. expected file exists
    checks.append(Check(
        "expected_file_exists", bool(files),
        f"{len(files)} importable file(s) under {folder}" if files
        else f"no file matching {', '.join(_bem.IMPORT_EXTS)} under {folder}"))

    # 2. file is non-empty
    empty = [p.name for p in files if p.stat().st_size == 0]
    checks.append(Check(
        "files_non_empty", bool(files) and not empty,
        "all files non-empty" if not empty else f"empty file(s): {', '.join(empty)}"))

    best, best_name = _bem.choose_best(list(parsed.items()), _bem.folder_mtimes(folder))

    # 3. frequency grid valid
    ok, detail = _grid_detail(best)
    checks.append(Check("frequency_grid_valid", ok, detail))

    # 4. required spectrum present (a pressure / SPL curve)
    spl_files = [n for n, p in parsed.items() if _bem._looks_like_spl(p)]
    checks.append(Check(
        "required_spectrum_present", bool(spl_files),
        f"pressure/SPL curve found in: {', '.join(spl_files)}" if spl_files
        else "no pressure/SPL curve found (need Mic1 or H 0-90)"))

    # 5. values numeric and finite
    bad = []
    for n, p in parsed.items():
        if not np.all(np.isfinite(np.asarray(p["freq"], dtype=float))):
            bad.append(f"{n}:freq")
        for lab, v in p["curves"].items():
            if not np.all(np.isfinite(np.asarray(v, dtype=float))):
                bad.append(f"{n}:{lab}")
    checks.append(Check("values_numeric_finite", not bad,
                        "all values finite" if not bad
                        else "non-finite in " + ", ".join(bad[:5])))

    # 6. export timestamp is after input generation
    if manifest is None:
        checks.append(Check("export_timestamp_after_inputs", False,
                            "no run manifest, so no generation time to compare",
                            severity=SOFT))
    else:
        gen = _parse_utc(manifest.generated_utc)
        stale = [p.name for p in files if gen and _mtime_utc(p) < gen - _secs(slack_s)]
        checks.append(Check(
            "export_timestamp_after_inputs", bool(files) and not stale,
            f"all exports newer than {manifest.generated_utc}" if not stale
            else f"older than the generated inputs: {', '.join(stale)}"))

    # 7. file belongs to the current run
    if manifest is None:
        checks.append(Check("belongs_to_run", False,
                            "no run manifest - provenance cannot be proven",
                            severity=SOFT))
    else:
        token = any(manifest.run_id in p.name for p in files)
        dirmatch = _same_dir(folder, manifest.export_dir)
        gen = _parse_utc(manifest.generated_utc)
        newer = bool(files) and bool(gen) and all(
            _mtime_utc(p) >= gen - _secs(slack_s) for p in files)
        ok = token or dirmatch or newer
        detail = ("run id in filename" if token else
                  "export directory matches the manifest" if dirmatch else
                  "timestamp newer than the manifest (weak evidence)" if newer else
                  "no run id, wrong directory, and not newer than the inputs")
        checks.append(Check("belongs_to_run", ok, detail, severity=SOFT))

    # 8. run manifest matches (and its input hashes are unchanged)
    if manifest is None:
        checks.append(Check("run_manifest_matches", False,
                            f"no {MANIFEST_NAME} supplied", severity=SOFT))
    else:
        ok, detail = _manifest_matches(manifest)
        checks.append(Check("run_manifest_matches", ok, detail, severity=SOFT))

    passed = all(c.passed for c in checks if c.severity == HARD)
    warnings = [f"{c.name}: {c.detail}" for c in checks
                if c.severity == SOFT and not c.passed]
    return ExportValidation(
        state=(ManualSolveState.VIPS_IMPORTED.value if passed
               else ManualSolveState.MANUAL_SOLVE_PENDING.value),
        passed=passed, rejected=not passed, checks=checks, warnings=warnings,
        errors=errors, files=[p.name for p in files],
        source=best_name, best=best)


def _secs(slack_s: float):
    from datetime import timedelta
    return timedelta(seconds=float(slack_s))



# --------------------------------------------------------------------------- #
#  comparison against the one-dimensional reference
# --------------------------------------------------------------------------- #
def compare_reference(reference, parsed: dict, tolerance_db: float = DEFAULT_TOLERANCE_DB) -> dict:
    """Compare an imported export's on-axis curve with the 1-D reference.

    ``reference`` is anything exposing ``.f`` and ``.spl`` (a ``response.Result``
    or a lightweight stand-in).  The imported pressure curve is already in
    rms-referenced dB SPL (the +3.01 dB peak-rendering offset is removed by the
    ``.vips`` parser), so the two are directly comparable.
    """
    ref_f = np.asarray(reference.f, dtype=float)
    ref_spl = np.asarray(reference.spl, dtype=float)
    label = _bem._onaxis_curve(parsed)
    f = np.asarray(parsed["freq"], dtype=float)
    y = np.asarray(parsed["curves"][label], dtype=float)

    lo, hi = max(float(f.min()), float(ref_f.min())), min(float(f.max()), float(ref_f.max()))
    if hi <= lo:
        return {"curve": label, "within_tolerance": False, "n_points": 0,
                "reason": "no overlapping frequency band",
                "tolerance_db": float(tolerance_db),
                "evidence": EvidenceLabel.BEM_SIMULATION.value}
    mask = (f >= lo) & (f <= hi)
    ff, yy = f[mask], y[mask]
    ref = np.interp(ff, ref_f, ref_spl)
    d = yy - ref
    return {
        "curve": label, "n_points": int(mask.sum()),
        "band_hz": [float(lo), float(hi)],
        "points": [[float(a), float(b), float(c), float(b - c)]
                   for a, b, c in zip(ff, yy, ref)][:64],
        "mean_diff_db": float(np.mean(d)),
        "worst_diff_db": float(np.max(np.abs(d))),
        "tolerance_db": float(tolerance_db),
        "within_tolerance": bool(np.max(np.abs(d)) <= tolerance_db),
        "evidence": EvidenceLabel.BEM_SIMULATION.value,
    }


def import_and_validate(params, reference, folder, out_dir, *, manifest=None,
                        tolerance_db: float = DEFAULT_TOLERANCE_DB,
                        write_outputs: bool = True) -> dict:
    """Validate, then (if accepted) compare - and return the resulting state.

    ``state`` is ``MANUAL_SOLVE_PENDING`` when validation fails (retry the
    export), otherwise ``BEM_VALIDATED`` or ``BEM_REJECTED`` from the comparison.
    """
    validation = validate_exports(folder, manifest)
    out: dict = {"validation": validation.to_dict(), "state": validation.state,
                 "rejected": validation.rejected, "metrics": None, "comparison": None}
    if not validation.passed:
        return out
    metrics = compare_reference(reference, validation.best, tolerance_db)
    out["metrics"] = metrics
    if write_outputs:
        out["comparison"] = _bem._write_comparison(
            params, reference, validation.best, validation.source or "export",
            Path(out_dir))
    out["state"] = (ManualSolveState.BEM_VALIDATED.value if metrics["within_tolerance"]
                    else ManualSolveState.BEM_REJECTED.value)
    return out


# --------------------------------------------------------------------------- #
#  a short, traceable report of the return path
# --------------------------------------------------------------------------- #
def validation_md(result: dict, *, project: str = "", run_id: str = "") -> str:
    v = result["validation"]
    lines = [
        f"# Manual BEM import - {project}" + (f" (`{run_id}`)" if run_id else ""),
        "",
        f"**State after import: `{result['state']}`**"
        + ("" if v["passed"] else "  (validation failed - re-export and retry)"),
        "",
        "| check | severity | result | detail |",
        "| --- | --- | --- | --- |",
    ]
    for c in v["checks"]:
        lines.append(f"| {c['name']} | {c['severity']} | "
                     f"{'pass' if c['passed'] else 'FAIL'} | {c['detail']} |")
    if v["warnings"]:
        lines += ["", "Warnings (soft checks):", ""] + [f"* {w}" for w in v["warnings"]]
    if v["errors"]:
        lines += ["", "Unparsed files:", ""] + [f"* {e}" for e in v["errors"]]
    m = result.get("metrics")
    if m:
        lines += ["", "## Comparison with the 1-D reference", "", 
                  f"* curve compared: `{m['curve']}`",
                  f"* overlapping band: {m.get('band_hz')} ({m['n_points']} points)",
                  f"* mean difference: **{m['mean_diff_db']:+.2f} dB**, "
                  f"worst |difference|: **{m['worst_diff_db']:.2f} dB** "
                  f"(tolerance {m['tolerance_db']:.1f} dB)",
                  f"* evidence: `{m['evidence']}`",
                  "",
                  "The exported pressure curve is already rms-referenced, so the AKABAK "
                  "peak-rendering +3.01 dB convention has been removed before comparing.",
                  ""]
    return "\n".join(lines)

