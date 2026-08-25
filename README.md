# Frontier data-engineering practice

This is a small production-style incremental ETL benchmark. It ingests order events into DuckDB, keeps one current row per order, and rebuilds daily revenue only for dates affected by a batch.

This repository is also the canonical home of the `frontier-data-engineering` skill and its dependency-free `frontier_control_plane` package. Feather consumes this repository as an integration; it does not own the canonical skill source.

The benchmark is deliberately narrow. Its purpose is to exercise the failure modes that matter when evaluating coding agents:

- duplicate delivery and replay safety;
- late-arriving state changes;
- older backfill events that must not overwrite current state;
- idempotent reruns;
- transaction rollback and recovery;
- deterministic output from independent clean checkouts.

## Run it

```sh
uv sync
./scripts/test.sh
python3 .cursor/skills/frontier-data-engineering/scripts/control_plane.py --help
PYTHONPATH=src uv run python -m practice_pipeline.benchmark --help
python3 scripts/install_skill_links.py
```

The repository also includes `scripts/run_clean_benchmark.sh`. It creates two detached Git worktrees at the same commit, runs the full benchmark and the skill CLI lifecycle in each, and fails unless both result hashes match and every required gate passes.

The explicit `PYTHONPATH` keeps the commands reliable on Python builds that skip hidden editable-install `.pth` files.

## Tables

- `raw_order_events`: immutable, deduplicated source events.
- `orders_current`: the latest event for each order, ordered by event time, ingestion time, and event id.
- `daily_revenue`: completed-order revenue grouped by the UTC date of the current event.
- `pipeline_runs`: a lightweight operational log for completed and failed attempts.

All amounts use integer cents. The pipeline uses explicit transactions. An injected failure after raw staging must leave every business table unchanged.
