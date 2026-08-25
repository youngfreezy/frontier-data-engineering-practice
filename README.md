# Frontier data-engineering toolkit

This private repository is the canonical home of two reusable components:

- the `frontier-data-engineering` skill under `.cursor/skills/`;
- the dependency-free `frontier_control_plane` Python package under `src/`.

The toolkit records requirements-pinned run identity and ownership, tri-state executable gate results, typed outcomes, required artifact receipts, measurements, residual risks, canonical result hashes, verification, approval, submission, and identity-safe candidate comparisons. Approval and submission re-hash artifacts inside their locked state transitions. It contains no warehouse engine, browser automation, grading policy, or task fixture.

Read [BOUNDARIES.md](BOUNDARIES.md) for the enforced ownership and dependency rules.

## Reusable toolkit commands

```sh
uv sync
scripts/test_toolkit.sh
python3 .cursor/skills/frontier-data-engineering/scripts/control_plane.py --help
python3 scripts/install_skill_links.py
```

New runs must register `clean_checkout` and `unit_tests`, the requirements,
dataset, and environment SHA-256 digests, and every required artifact name.
Use the CLI `outcome`, `measure`, and `risk` commands to keep non-semantic
failures, resource evidence, and residual risks out of prose-only summaries.

## Practice task

The incremental order-event exercise is isolated under `practice/incremental-order-etl`. That project owns DuckDB, its schemas, fixtures, expected totals, pipeline code, and clean-worktree benchmark.

```sh
uv sync --project practice/incremental-order-etl
practice/incremental-order-etl/scripts/test.sh
practice/incremental-order-etl/scripts/run_clean_benchmark.sh
```

The practice project depends on the root toolkit through a relative local package reference. The reusable toolkit does not import the practice project.

## Consumer integrations

Consumer-specific adapters remain in their consumer repositories. Feather pins this repository as a private Git submodule and imports only the control-plane package through its Feather adapter.

The draw.io source and rendered architecture diagram are under `docs/`.
