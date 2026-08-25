# Repository boundaries

This repository contains a reusable evaluation toolkit and one practice task. Dependencies point inward toward the toolkit; reusable code never imports task or consumer code.

## Reusable toolkit

- `.cursor/skills/frontier-data-engineering`: task-agnostic workflow and gate policy.
- `src/frontier_control_plane`: dependency-free run identity, ownership, evidence, hashing, verification, approval, submission, and comparison.
- `scripts/install_skill_links.py`: local skill installation for Claude, Cursor, and Codex.
- `tests/test_control_plane.py`, `tests/test_skill_cli.py`, and `tests/test_boundaries.py`: reusable behavior and boundary enforcement.

The root Python project has no runtime dependency. It must not import DuckDB, a practice pipeline, Feather, browser automation, email, or task fixtures.

## Task-specific practice

Everything under `practice/incremental-order-etl` belongs to the order-event exercise:

- DuckDB dependency and virtual environment;
- input fixtures;
- pipeline and benchmark implementation;
- expected row values and revenue totals;
- late-data, duplicate, backfill, idempotency, and recovery scenarios;
- clean-worktree runner and generated evidence.

The practice project may depend on the reusable toolkit. The toolkit may not depend on the practice project.

## Consumer integration

Feather-specific state, Chrome behavior, mail behavior, grading gates, and submission logic remain in the private Feather repository. Feather pins this repository as a submodule and imports only `frontier_control_plane` through its adapter. No Feather policy belongs in the reusable skill or package.

Documentation may draw the interaction between these areas. A diagram does not create a runtime dependency.
