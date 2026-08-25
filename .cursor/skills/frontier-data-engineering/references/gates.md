# Data-engineering gates

Choose only the gates exercised by the live task, plus `clean_checkout` and `unit_tests`.

Streaming, table-format, and orchestration gates require the real platform runtime. Do not
simulate them on a local engine and record the result as a pass; if the runtime is not
available, record the gate as not run and treat it as a residual risk in the comparison.

## Required on most batch pipelines

- `clean_checkout`: the run starts at the recorded commit with no untracked or modified files.
- `unit_tests`: supplied tests and evaluator-added tests pass.
- `contract_traceability`: each stated requirement has a test or inspection, and each evaluator assertion traces to a stated requirement.
- `schema_contract`: output columns, types, nullability, keys, and grain match the contract.
- `duplicates`: replayed input cannot create duplicate business facts.
- `late_data`: a later arrival with an earlier processing time lands according to event-time rules.
- `backfill`: historical input updates the intended partitions without regressing newer state.
- `idempotency`: a second run over the same input produces the same canonical output hash.
- `recovery`: an injected interruption rolls back or resumes from the documented safe point.

## Add when the task needs them

- `evaluator_sanity`: the reference path passes and a no-op or deliberately broken path fails without relying on infrastructure behavior.
- `outcome_classification`: raw result, exception, logs, verifier report, and produced artifacts agree that the run completed normally or identify its non-semantic failure class.
- `artifact_integrity`: every decision-relevant artifact has a size and digest, parses in its native format, and still matches its receipt at approval time.
- `representation_contract`: canonical serialization, ordering, tie-breaks, character handling, time zones, numeric precision, and content-versus-name identity are explicit and tested.
- `visible_edge_coverage`: enforced rules have visible examples or derivable specifications; held-out cases vary combinations and values rather than adding undisclosed semantics.
- `semantic_mutations`: realistic incorrect implementations fail on semantic assertions; crashes, malformed output, and incidental exceptions are reported separately.
- `incremental_full_equivalence`: incremental output equals a clean full refresh.
- `deletes`: tombstones and hard deletes follow the stated retention rules.
- `timezone`: UTC conversion, daylight-saving transitions, and date boundaries are tested.
- `precision`: decimal scale, overflow, and comparison tolerances are explicit.
- `schema_drift`: additive, missing, and incompatible fields have a defined result.
- `query_plan`: plans show the intended scan, join, pruning, and partition behavior.
- `scale`: runtime, memory, shuffle, state, or file-count measurements meet the task target.
- `observability`: a controlled failure produces a run ID, failed stage, metric, and actionable log.
- `secrets`: credentials are absent from diffs, outputs, logs, and saved artifacts.
- `concurrent_runs`: two overlapping runs of the same pipeline over the same target cannot corrupt state; the second run blocks, fails cleanly, or serializes, and a reader during a write sees either the prior complete state or the new complete state, never a mixture.
- `referential_integrity`: keys between output tables resolve; orphaned facts, dangling dimension references, and lookups that miss have a defined and tested result.
- `volume_anomaly`: output row counts and partition sizes match the baseline within a stated tolerance; empty input, a partition with zero rows, and unexpectedly large input each have a defined result rather than a silent pass.
- `cdc_ordering`: out-of-order change events resolve by the stated version or timestamp rule; same-key ties at the same version have an explicit tie-break; delete-then-reinsert and a tombstone arriving before its insert produce the documented final state.
- `scd_history`: dimension history is correct after an update, a late correction, and a full reprocess; effective-date ranges do not overlap or gap, and exactly one row per key is current.

## Streaming (only with the real streaming runtime)

- `delivery_semantics`: the stated guarantee (at-least-once or exactly-once) holds under broker redelivery and consumer restart; duplicates permitted by the guarantee are deduplicated or tolerated downstream, with evidence from an injected redelivery.
- `watermark_windowing`: window assignment, allowed lateness, and the split between on-time and late output match the contract, including an event exactly on a window boundary and a late event past the watermark.
- `checkpoint_recovery`: killing the job mid-stream and restarting from the last checkpoint resumes without loss, and without duplication beyond the stated guarantee; operator state survives the restart.
- `partition_rebalance`: a consumer joining or leaving mid-run reassigns partitions without losing or double-processing records beyond the stated guarantee.

## Table formats and lakehouse (only with the real table format)

- `snapshot_isolation`: a reader concurrent with a commit sees one complete snapshot; reading a prior snapshot or time-travel query returns the recorded state.
- `write_conflict`: two writers committing to overlapping partitions follow the format's conflict rule; one retries or fails cleanly and no committed update is lost.
- `maintenance_safety`: compaction and snapshot expiry or vacuum do not break a concurrent reader and do not delete data inside the stated retention window.
- `format_evolution`: added, renamed, and type-widened columns read correctly across old and new files; an incompatible change fails loudly instead of returning nulls.

## Orchestration (only with the real scheduler)

- `scheduling_semantics`: the run uses the data interval rather than the wall-clock trigger time; scheduler-driven catchup or backfill produces each intended partition exactly once.
- `retry_side_effects`: a task retry after a partial success does not duplicate external side effects such as writes, publishes, or notifications; a sensor or upstream dependency that never arrives fails at its deadline instead of hanging.

## Failure record

For every failure that changes rows, schema, completion status, or a stated runtime target, record:

1. Hypothesis.
2. Input fixture and command.
3. Expected and actual result.
4. Row diff, exception, plan fragment, or measurement.
5. Severity under the task rubric.
6. Fix.
7. Regression test.
8. Outcome class: completed semantic failure, timeout, OOM, infrastructure, malformed artifact, missing artifact, or transport failure.
