#!/bin/sh
set -eu

practice_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
repo_root=$(CDPATH= cd -- "$practice_root/../.." && pwd)
evidence_root="$practice_root/evidence"
scratch_root="$evidence_root/worktrees"
python_bin="$practice_root/.venv/bin/python"

mkdir -p "$evidence_root" "$scratch_root"
git -C "$repo_root" worktree prune
# Each invocation is one independent two-checkout experiment. Previous result
# files remain in the attempt folders, but the run ledger starts empty.
rm -f "$evidence_root/control-plane.json" "$evidence_root/comparison.json"

for attempt in 1 2; do
  checkout="$scratch_root/attempt-$attempt"
  if [ -d "$checkout" ]; then
    git -C "$repo_root" worktree remove --force "$checkout"
  fi
  git -C "$repo_root" worktree add --detach "$checkout" HEAD
  checkout_practice="$checkout/practice/incremental-order-etl"
  PYTHONPATH="$checkout_practice/src:$checkout/src" "$python_bin" -m practice_pipeline.benchmark \
    --worktree "$checkout_practice" \
    --artifacts "$evidence_root/attempt-$attempt" \
    --state "$evidence_root/control-plane.json" \
    --run-id "practice-clean-$attempt" \
    --attempt "$attempt" \
    --owner "clean-worker-$attempt"
done

PYTHONPATH="$practice_root/src:$repo_root/src" "$python_bin" -m practice_pipeline.compare \
  --state "$evidence_root/control-plane.json" \
  --output "$evidence_root/comparison.json" \
  practice-clean-1 practice-clean-2
