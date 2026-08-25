# Evaluation integrity

Use these rules when a coding-agent run fails, times out, or disagrees with a reference output.

## Trust order

Build the verdict from the raw bundle:

1. Run result and exception type.
2. Agent exit state and duration.
3. Verifier report and test output.
4. Artifact manifest, file sizes, digests, and native-format integrity.
5. Agent trajectory or terminal recording when needed to explain an incomplete run.
6. Dashboard or sticky summary only as a pointer to the raw evidence.

Hash the bundle or its manifest before analysis. A later download or regenerated report must be distinguishable from the evidence used for the verdict.

## Outcome classes

- `solved`: the run completed normally and every required semantic gate passed.
- `completed_semantic_failure`: the run completed normally, produced valid requested artifacts, and a disclosed invariant failed.
- `timeout`: the agent did not complete within the budget. A coherent partial artifact does not convert the run into a completed semantic failure.
- `oom`: the run ended because its memory budget was exhausted.
- `infrastructure`: the container, runner, network, storage, or evaluator failed independently of the candidate implementation.
- `malformed_artifact`: a requested artifact exists but cannot be parsed or opened as its declared type.
- `missing_artifact`: a requested artifact was not produced.
- `transport_failure`: the command or editing channel truncated, wedged, or failed to deliver the intended candidate action.

Do not let a timeout, infrastructure error, malformed artifact, missing artifact, or transport failure count as evidence that the model misunderstood the data-engineering contract. It may still be an operational weakness, but report it separately.

## Evaluator sanity

When the task supplies suitable paths:

- Run the reference or oracle and require a full pass.
- Run a no-op or deliberately broken candidate and require a semantic failure.
- Confirm the verifier reads only the requested outputs.
- Keep expected outputs and hidden fixtures outside the candidate-visible environment.
- Pin or bake verifier dependencies; do not let verification depend on a mutable live service.

## Fair edge coverage

Every enforced rule must be derivable from the task contract. Give a visible example or precise representation rule for byte-sensitive behavior such as ordering, tie-breaks, whitespace, case, time zones, decimals, nulls, duplicate identity, and canonical serialization.

Held-out tests should change values, scale, arrival order, and combinations. They should not introduce a new semantic rule. When preserving the coupled reasoning crux requires withholding a combined example, expose each representation rule independently.

## Mutation quality

Use realistic semantic mutants to test evaluator strength: wrong deduplication key, unstable tie-break, processing-time instead of event-time logic, non-atomic recovery, incorrect watermark boundary, or precision loss. Count a kill as semantic only when a specific invariant rejects a validly produced but wrong output. Report crash-only and malformed-output kills separately.

## Approval boundary

Immediately before approval, repeat the feedback and artifact snapshot. Record any new comments, checks, artifact IDs, sizes, and digests. If anything changed after the review began, reconcile the delta and rerun the affected gates.
