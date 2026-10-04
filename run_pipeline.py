#!/usr/bin/env python3
"""Convenience entry point for the gated folded-horn pipeline.

    python3 run_pipeline.py params/horn_jbl_1200b.yaml
    python3 run_pipeline.py params/horn_jbl_1200b.yaml --out runs --wall-mm 18

Equivalent to ``python3 -m hornflow.cli``.  The legacy ``run_workflow.py`` is
untouched and still produces the original Stage-1/2 outputs.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from hornflow.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
