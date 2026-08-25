# Data-engineering evaluation anti-patterns

Reject these shortcuts when they can affect a ship decision:

- Golden-file-only grading: matching one expected file replaces business-key, grain, invariant, and aggregate checks.
- Unordered serialization hashes: row order, map order, null encoding, time zone, or decimal scale can change the digest without changing meaning.
- Floating-point exact equality: binary rounding is treated as a semantic difference without a declared tolerance or decimal representation.
- Empty-output success: a pipeline that emits no rows passes because schema or file-existence checks are the only assertions.
- Crash-as-semantic-failure: a timeout, OOM, infrastructure fault, malformed artifact, or transport failure is scored as wrong data logic.
- Prose-weighted correctness: a polished README or explanation offsets a failed data invariant.
- Local-runtime theater: a platform behavior is simulated on a different engine and recorded as a real streaming, table-format, or scheduler pass.
- Happy-path replay: idempotency is claimed without duplicate delivery, partial success, interruption, or backfill evidence.
- Average-only monitoring: stable row totals or means hide tail collapse, category loss, null spikes, or partition skew.
- Mutable evidence: outputs are recorded by path but not re-hashed atomically at approval and submission.
- Silent contract migration: requirements change while the task ID, requirements hash, or comparison family remains unchanged.
- Unequal evaluation: candidates use different required gates, artifacts, fixtures, commits, data, or environments.
