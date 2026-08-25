#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_root"
PYTHONPATH="$project_root/src" uv run python -m pytest -q
