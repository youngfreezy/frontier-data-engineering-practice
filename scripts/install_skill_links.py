#!/usr/bin/env python3
"""Point Claude, Cursor, and Codex at this repository's canonical skill."""

from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".cursor" / "skills" / "frontier-data-engineering"
DESTINATIONS = tuple(
    Path.home() / harness / "skills" / "frontier-data-engineering"
    for harness in (".claude", ".cursor", ".codex")
)


def main() -> int:
    if not (SOURCE / "SKILL.md").is_file():
        raise SystemExit(f"missing canonical skill at {SOURCE}")
    for destination in DESTINATIONS:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.is_symlink() or destination.exists():
            destination.unlink()
        os.symlink(SOURCE, destination)
        if (destination / "SKILL.md").resolve() != (SOURCE / "SKILL.md").resolve():
            raise SystemExit(f"link verification failed for {destination}")
        print(f"LINK {destination} -> {SOURCE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
