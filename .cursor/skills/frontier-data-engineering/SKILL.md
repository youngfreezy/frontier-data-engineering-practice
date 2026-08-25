---
name: frontier-data-engineering
description: Run and evaluate AI-assisted data-engineering work with isolated candidates, executable data gates, artifact hashes, recovery tests, and fail-closed approval. Use for ETL, warehouses, analytics models, incremental pipelines, streaming jobs, or comparisons between coding agents. Do not use for ordinary prose grading or visual review.
---

# Frontier data engineering

Use the reusable control plane in this repository for each candidate attempt. Live task instructions define the required outputs and override the default gate names.

## Core invariant

A run is identified by task, candidate, attempt, starting commit, requirements hash, dataset hash, and environment hash. Keep each candidate in its own clean worktree or container. Never compare candidates that started from different code, data, requirements, required gates, or required artifacts. When requirements change, start a new task ID and requirements hash, preserve the old ledger, and record a `migration_note` on the first run of the new contract.

The control plane fails closed. Approval requires an owner, a typed `solved` outcome, a canonical SHA-256 result hash, every required artifact at its recorded size and digest, and a passing or justified `not_applicable` result for every required gate. `not_run` is a residual risk and blocks approval when the gate is required.

## Default gate catalog

Every task must select gates explicitly and record `pass`, `fail`, `not_run`, or `not_applicable` with evidence. `not_applicable` must quote the task sentence that excludes the behavior.

1. Contract: requirements map to tests and evaluator assertions; unresolved and undisclosed semantics are recorded. Default name: `contract_traceability`.
2. Evaluator sanity: reproduce the baseline; require the reference to pass and a no-op or semantic mutant to fail when those paths exist. Default name: `evaluator_sanity`.
3. Identity and isolation: claim ownership; pin the start commit, requirements, dataset, environment, clean checkout, and required artifacts. Default names: `clean_checkout`, `artifact_integrity`.
4. Grain and keys: assert output grain, business-key uniqueness, join cardinality, unmatched keys, null keys, and referential integrity. Default names: `join_cardinality`, `aggregate_grain`, `key_stability`, `referential_integrity`.
5. Invariants: assert nulls, ranges, categories, volume, distribution, freshness, and aggregate checksums where the contract uses them. Default names: `value_invariants`, `null_semantics`, `volume_anomaly`, `distribution_shift`, `freshness`.
6. Replay and recovery: rerun equivalent input, inject interruption and partial success, and test duplicates, backfills, and concurrent writers as applicable. Default names: `idempotency`, `recovery`, `duplicates`, `backfill`, `atomic_commit`, `concurrent_runs`.
7. Schema: test declared types and nullability plus additive, missing, renamed, coerced, and incompatible fields. Default names: `schema_contract`, `schema_drift`, `type_coercion`, `category_drift`.
8. Time: distinguish event, ingest, and processing time; pin time zone; test daylight-saving, skew, early, late, and out-of-order data. Default names: `late_data`, `timezone`, `event_time_contract`, `cdc_ordering`, `scd_history`.
9. Determinism: remove or pin wall-clock time, random IDs, unstable iteration, floating-point order, and unspecified tie-breaks. Default name: `determinism`.
10. Semantic equality: compare primary-key sets, typed invariants, and aggregate checksums before canonical sorting, null encoding, decimal scale, and hashing. Default names: `semantic_equality`, `representation_contract`, `precision`.
11. Plan, scale, layout, and cost: record rows, partitions, bytes, elapsed time, memory, spill or shuffle, file count, cost, and a plan fragment that proves the claimed access path. Default names: `query_plan`, `scale`, `data_layout`, `cost`.
12. Classification: record `solved`, completed semantic failure, timeout, OOM, infrastructure, malformed or missing artifact, or transport failure from raw evidence. Default name: `outcome_classification`.
13. Snapshot: hash every decision-relevant artifact and revalidate it inside the approval and submission transitions. Default name: `artifact_integrity`.

Use the expanded catalog in [references/gates.md](references/gates.md), reject the shortcuts in [references/anti-patterns.md](references/anti-patterns.md), and give reviewers [references/reviewer-checklist.md](references/reviewer-checklist.md).

## Workflow

Steps 1 to 4, 6 to 8, and 10 are blocking. Step 5 selects task-specific gates. Step 9 is comparative and cannot rescue a blocked run.

1. Convert the task instructions into observable acceptance conditions and hash that contract. Record unresolved requirements before implementation.
2. Map every stated requirement to at least one test or inspection, and every evaluator assertion back to a stated requirement. Flag undisclosed semantics before judging candidates.
3. Reproduce the baseline and store its command, output, starting commit, requirements hash, dataset hash, and environment hash. When a reference and no-op path exist, require the reference to pass and the no-op to fail before trusting the evaluator.
4. Register the required gates and artifact names, then claim one run per candidate with `scripts/control_plane.py`.
5. Run the supplied tests, then add data-semantic, recovery, and scale tests that match the task. Read [references/gates.md](references/gates.md) when choosing gates or evaluating a failure.
6. Record each gate with specific evidence. A pass names the command, invariant, row count, hash, or execution-plan fragment that proved it.
7. Classify outcomes from raw artifacts, not a dashboard summary. Keep completed semantic failures separate from timeouts, OOMs, infrastructure faults, malformed or missing artifacts, and transport failures. Re-run a non-semantic failure once in a clean environment as a new linked attempt; keep it incomplete rather than scoring it as wrong data logic. Read [references/evaluation-integrity.md](references/evaluation-integrity.md).
8. Compare primary keys, typed invariants, aggregate checksums, and canonicalized values before hashing the final output. Record every decision-relevant artifact and verify the run before approval.
9. Give an independent reviewer the task contract, final diff, test logs, output diff, execution plans, and outcome classification. The reviewer checks [references/reviewer-checklist.md](references/reviewer-checklist.md); uncited concerns remain unverified leads and cannot introduce hidden criteria.
10. Repeat the final feedback and artifact snapshot immediately before approval. Approve and submit only after every required gate passes or has a quoted `not_applicable` basis and the snapshot has not changed. Preserve the ledger and evidence bundle.

## Candidate comparison

Run candidates from the same commit and dataset. Compare hard-gate failures, canonical output hashes, runtime, resource measurements, and residual risks. Keep explanation quality in a separate field so it cannot offset failed data invariants.

## Commands

The wrapper loads the dependency-free package from this repo:

```bash
python3 .cursor/skills/frontier-data-engineering/scripts/control_plane.py \
  --state /path/to/control-plane.json status
```

Use `--help` for register, claim, gate, artifact, result, outcome, measure, risk, verify, approve, submit, and compare.

Consumer-specific adapters belong in their consumer repositories. They may call the control-plane API, but this reusable skill must not import or name those consumers.
