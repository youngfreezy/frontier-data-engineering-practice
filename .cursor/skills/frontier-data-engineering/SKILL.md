---
name: frontier-data-engineering
description: Run and evaluate AI-assisted data-engineering work with isolated candidates, executable data gates, artifact hashes, recovery tests, and fail-closed approval. Use for ETL, warehouses, analytics models, incremental pipelines, streaming jobs, or comparisons between coding agents. Do not use for ordinary prose grading or visual review.
---

# Frontier data engineering

Use the reusable control plane in this repository for each candidate attempt. Live task instructions define the required outputs and override the default gate names.

## Core invariant

A run is identified by task, candidate, attempt, starting commit, dataset hash, and environment hash. Keep each candidate in its own clean worktree or container. Never compare candidates that started from different code, data, or requirements.

The control plane fails closed. Approval requires an owner, a canonical result hash, and a passing result for every required gate.

## Workflow

1. Convert the task instructions into observable acceptance conditions. Record unresolved requirements before implementation.
2. Map every stated requirement to at least one test or inspection, and every evaluator assertion back to a stated requirement. Flag undisclosed semantics before judging candidates.
3. Reproduce the baseline and store its command, output, starting commit, dataset hash, and environment hash. When a reference and no-op path exist, require the reference to pass and the no-op to fail before trusting the evaluator.
4. Register and claim one run per candidate with `scripts/control_plane.py`.
5. Run the supplied tests, then add data-semantic, recovery, and scale tests that match the task. Read [references/gates.md](references/gates.md) when choosing gates or evaluating a failure.
6. Record each gate with specific evidence. A pass names the command, invariant, row count, hash, or execution-plan fragment that proved it.
7. Classify outcomes from raw artifacts, not a dashboard summary. Keep completed semantic failures separate from timeouts, OOMs, infrastructure faults, malformed or missing artifacts, and transport failures. Read [references/evaluation-integrity.md](references/evaluation-integrity.md).
8. Hash the final output and all decision-relevant artifacts. Verify the run before approval.
9. Give an independent reviewer the task contract, final diff, test logs, output diff, execution plans, and outcome classification. Treat uncited concerns as unverified leads.
10. Repeat the final feedback and artifact snapshot immediately before approval. Approve and submit only after every required gate passes and the snapshot has not changed. Preserve the ledger and evidence bundle.

## Candidate comparison

Run candidates from the same commit and dataset. Compare hard-gate failures, canonical output hashes, runtime, resource measurements, and residual risks. Keep explanation quality in a separate field so it cannot offset failed data invariants.

## Commands

The wrapper loads the dependency-free package from this repo:

```bash
python3 .cursor/skills/frontier-data-engineering/scripts/control_plane.py \
  --state /path/to/control-plane.json status
```

Use `--help` for register, claim, gate, artifact, result, verify, approve, submit, and compare.

Consumer-specific adapters belong in their consumer repositories. They may call the control-plane API, but this reusable skill must not import or name those consumers.
