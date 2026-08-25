# Independent reviewer checklist

The reviewer may only use evidence in the run bundle. An uncited concern stays an unverified lead. It cannot become a hidden gate or change a rank.

## Required packet

Confirm each item is present and current:

- Task contract and its requirements hash.
- Starting commit, dataset hash, and environment hash.
- Final candidate diff from that commit.
- Test logs with commands and exit status.
- Output diff or semantic-equality report (key sets, invariants, checksums, then hash).
- Execution-plan fragment or an explicit `not_applicable` quote when the task has no planner.
- Typed outcome class with raw evidence.

## Blocking checks

Reject approval if any of these fail:

- Contract traceability: every stated requirement has a test or inspection; every evaluator assertion traces to a stated requirement; undisclosed semantics are recorded, not scored.
- Identity: compared runs share commit, requirements, dataset, environment, required gates, and required artifacts. A changed contract has a new task ID, a new requirements hash, and a `migration_note`.
- Evidence: each required gate is `pass` or quoted `not_applicable`. `not_run` on a required gate blocks.
- Artifact integrity: every required artifact still matches its recorded size and digest.
- Classification: timeouts, OOMs, infrastructure faults, malformed or missing artifacts, and transport failures are not scored as wrong data logic.
- Semantic equality: key sets, typed invariants, and aggregate checksums were checked before the canonical hash.
- Snapshot: the packet used for review matches the packet used for approve and submit.

## Out of scope for the reviewer

- Inventing extra acceptance rules that are not in the contract or recorded as unresolved.
- Letting README quality, explanation prose, or a dashboard summary offset a failed data invariant.
- Treating a local simulation of a missing streaming, table-format, or scheduler runtime as a pass.
