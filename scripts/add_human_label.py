#!/usr/bin/env python3
"""Command-line helper to add or update a human label record."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts.create_human_label import main  # noqa: E402

if __name__ == "__main__":
    main()
