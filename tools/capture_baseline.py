#!/usr/bin/env python3
"""Milestone 0 - capture the validated baseline as regression fixtures.

Runs the existing JBL 1200B example exactly as it ships, records the reference
numbers and file checksums, and writes them to tests/fixtures/baseline/.

No physics is changed here.  Re-run this only when a *deliberate* baseline
change is approved; the produced fixture is what tests/test_baseline.py checks
against.

    python3 tools/capture_baseline.py
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from hornflow import config, report, response  # noqa: E402

EXAMPLE = ROOT / "params" / "horn_jbl_1200b.yaml"
FIXDIR = ROOT / "tests" / "fixtures" / "baseline"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def metrics(params, r) -> dict:
    t = params.target
    exc = np.abs(r.excursion)
    i_max = int(np.argmax(exc))
    ze = np.abs(r.Ze)
    return {
        "n_frequencies": int(len(r.f)),
        "f_min_hz": float(r.f[0]),
        "f_max_hz": float(r.f[-1]),
        "spl_band_mean_db": round(r.band_spl(t.f_low, t.f_high), 4),
        "spl_band_variation_db": round(r.variations_db(t.f_low, t.f_high), 4),
        "ze_min_ohm": round(float(np.min(ze)), 4),
        "ze_max_ohm": round(float(np.max(ze)), 4),
        "excursion_max_mm": round(float(np.max(exc)) * 1e3, 5),
        "excursion_max_at_hz": round(float(r.f[i_max]), 4),
        "di_min_db": round(float(np.min(r.di)), 4),
        "di_max_db": round(float(np.max(r.di)), 4),
        "k_rm_at_fc": round(float(r.derived["k_rm_at_fc"]), 5),
        "f_1P_validity_hz": round(float(r.derived["f_1P_validity_hz"]), 3),
    }


def main() -> int:
    FIXDIR.mkdir(parents=True, exist_ok=True)
    params = config.load(EXAMPLE)

    # determinism: two independent solves must agree bit-for-bit
    r1 = response.simulate(params)
    r2 = response.simulate(params)
    deterministic = all(
        np.array_equal(np.asarray(getattr(r1, k)), np.asarray(getattr(r2, k)))
        for k in ("spl", "Ze", "excursion", "Zt")
    )

    curves = FIXDIR / "jbl_1200b_curves.csv"
    report.write_csv(r1, curves)

    m = metrics(params, r1)
    manifest = {
        "captured_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "example": str(EXAMPLE.relative_to(ROOT)),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "git_commit": None,          # no VCS in this workspace
        "deterministic": deterministic,
        "metrics": m,
        "checksums": {
            "jbl_1200b_curves.csv": sha256(curves),
            "params/horn_jbl_1200b.yaml": sha256(ROOT / "params" / "horn_jbl_1200b.yaml"),
            "params/drivers/jbl_1200b.yaml": sha256(ROOT / "params" / "drivers" / "jbl_1200b.yaml"),
        },
    }
    man = FIXDIR / "manifest.json"
    man.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(f"deterministic: {deterministic}")
    for k, v in m.items():
        print(f"  {k:26} {v}")
    print(f"\nwrote {man.relative_to(ROOT)}")
    print(f"wrote {curves.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
