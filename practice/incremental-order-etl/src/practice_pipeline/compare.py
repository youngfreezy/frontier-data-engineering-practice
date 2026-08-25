"""Compare two completed benchmark runs and save the decision."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from frontier_control_plane import ControlPlane


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("run_ids", nargs=2)
    args = parser.parse_args()
    result = ControlPlane(args.state).compare(args.run_ids)
    Path(args.output).write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
