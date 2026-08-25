#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$repo_root"
PYTHONPATH="$repo_root/src" uv run python -m pytest -q tests
