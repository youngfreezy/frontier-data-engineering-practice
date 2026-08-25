#!/bin/sh
set -eu

practice_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
repo_root=$(CDPATH= cd -- "$practice_root/../.." && pwd)
cd "$practice_root"
PYTHONPATH="$practice_root/src:$repo_root/src" uv run python -m pytest -q
