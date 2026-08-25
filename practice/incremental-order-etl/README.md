# Incremental order ETL practice task

This directory contains one task-specific benchmark. It ingests immutable order events into DuckDB, keeps the latest state for each order, and rebuilds daily completed-order revenue for affected dates.

The fixtures and assertions belong only to this practice task. Reusable run state, hashing, approval, and candidate-comparison logic come from the root `frontier_control_plane` package.

```sh
uv sync --project practice/incremental-order-etl
practice/incremental-order-etl/scripts/test.sh
practice/incremental-order-etl/scripts/run_clean_benchmark.sh
```

The clean benchmark runs two detached worktrees from the same repository commit and requirements, dataset, and environment hashes. It requires passing clean-checkout, unit, skill-CLI, late-data, duplicate, backfill, idempotency, and recovery gates; revalidates the result and log artifacts; records the solved outcome and row measurement; then requires an identity-safe comparison with matching canonical result hashes.
