#!/usr/bin/env python3
"""Load the repo-local control-plane CLI without installing the package."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "src"))

from frontier_control_plane.cli import main  # noqa: E402


if __name__ == "__main__":
    raise SystemExit(main())
