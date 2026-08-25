#!/bin/sh
set -eu

project_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
evidence_root="$project_root/evidence"
scratch_root="$evidence_root/worktrees"
python_bin="$project_root/.venv/bin/python"

mkdir -p "$evidence_root" "$scratch_root"
git -C "$project_root" worktree prune

for attempt in 1 2; do
  checkout="$scratch_root/attempt-$attempt"
  if [ -d "$checkout" ]; then
    git -C "$project_root" worktree remove --force "$checkout"
  fi
  git -C "$project_root" worktree add --detach "$checkout" HEAD
  PYTHONPATH="$checkout/src" "$python_bin" -m practice_pipeline.benchmark \
    --worktree "$checkout" \
    --artifacts "$evidence_root/attempt-$attempt" \
    --state "$evidence_root/control-plane.json" \
    --run-id "practice-clean-$attempt" \
    --attempt "$attempt" \
    --owner "clean-worker-$attempt"
done

PYTHONPATH="$project_root/src" "$python_bin" -m practice_pipeline.compare \
  --state "$evidence_root/control-plane.json" \
  --output "$evidence_root/comparison.json" \
  practice-clean-1 practice-clean-2

