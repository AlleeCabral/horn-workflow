"""pytest path setup for the horn-workflow test suite.

The suite must also run standalone (``python3 tests/test_*.py``), so each test
file still inserts the repo root itself; this conftest covers the pytest route.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
