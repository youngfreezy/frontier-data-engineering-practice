# Data-engineering gates

Choose only the gates exercised by the live task, plus `clean_checkout` and `unit_tests`.

## Required on most batch pipelines

- `clean_checkout`: the run starts at the recorded commit with no untracked or modified files.
- `unit_tests`: supplied tests and evaluator-added tests pass.
- `schema_contract`: output columns, types, nullability, keys, and grain match the contract.
- `duplicates`: replayed input cannot create duplicate business facts.
- `late_data`: a later arrival with an earlier processing time lands according to event-time rules.
- `backfill`: historical input updates the intended partitions without regressing newer state.
- `idempotency`: a second run over the same input produces the same canonical output hash.
- `recovery`: an injected interruption rolls back or resumes from the documented safe point.

## Add when the task needs them

- `incremental_full_equivalence`: incremental output equals a clean full refresh.
- `deletes`: tombstones and hard deletes follow the stated retention rules.
- `timezone`: UTC conversion, daylight-saving transitions, and date boundaries are tested.
- `precision`: decimal scale, overflow, and comparison tolerances are explicit.
- `schema_drift`: additive, missing, and incompatible fields have a defined result.
- `query_plan`: plans show the intended scan, join, pruning, and partition behavior.
- `scale`: runtime, memory, shuffle, state, or file-count measurements meet the task target.
- `observability`: a controlled failure produces a run ID, failed stage, metric, and actionable log.
- `secrets`: credentials are absent from diffs, outputs, logs, and saved artifacts.

## Failure record

For every failure that changes rows, schema, completion status, or a stated runtime target, record:

1. Hypothesis.
2. Input fixture and command.
3. Expected and actual result.
4. Row diff, exception, plan fragment, or measurement.
5. Severity under the task rubric.
6. Fix.
7. Regression test.
