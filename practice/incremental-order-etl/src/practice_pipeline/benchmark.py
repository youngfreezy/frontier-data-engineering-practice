"""Execute the semantic gates and write a signed control-plane run record."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import duckdb
import frontier_control_plane
from frontier_control_plane import (
    ControlPlane,
    RunIdentity,
    environment_fingerprint,
    files_hash,
)

from .pipeline import InjectedFailure, Pipeline, load_jsonl
from .semantics import (
    CONTRACT_TRACE,
    aggregate_grain_holds,
    event_time_holds,
    invariants_hold,
    late_data_holds,
    same_semantics,
    schema_holds,
    snapshot_semantics,
    timezone_holds,
)

REQUIRED_GATES = (
    "clean_checkout",
    "unit_tests",
    "skill_cli",
    "contract_traceability",
    "evaluator_sanity",
    "schema_contract",
    "value_invariants",
    "aggregate_grain",
    "key_stability",
    "semantic_equality",
    "event_time_contract",
    "timezone",
    "volume_anomaly",
    "poison_records",
    "incremental_full_equivalence",
    "late_data",
    "duplicates",
    "backfill",
    "idempotency",
    "recovery",
    "delivery_semantics",
    "snapshot_isolation",
    "scheduling_semantics",
)
BATCH_CONTRACT = (
    '"It ingests immutable order events into DuckDB, keeps the latest state '
    'for each order, and rebuilds daily completed-order revenue for affected dates."'
)


def git_value(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=True
    )
    return proc.stdout.strip()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def record_pass(
    control: ControlPlane, run_id: str, name: str, detail: str, evidence: list[str]
) -> None:
    control.record_gate(run_id, name, True, detail, evidence)


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.worktree).resolve()
    repo_root = root.parents[1]
    fixtures = root / "fixtures"
    artifact_dir = Path(args.artifacts).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    database = artifact_dir / "pipeline.duckdb"
    if database.exists():
        database.unlink()

    fixture_paths = sorted(fixtures.glob("*.jsonl"))
    control_source = Path(frontier_control_plane.__file__).resolve().parent
    control_source_hash = files_hash(sorted(control_source.glob("*.py")))
    commit = git_value(root, "rev-parse", "HEAD")
    dirty = git_value(root, "status", "--porcelain")
    identity = RunIdentity(
        run_id=args.run_id,
        task_id="incremental-order-etl",
        candidate_id="practice-pipeline",
        attempt=args.attempt,
        starting_commit=commit,
        dataset_hash=files_hash(fixture_paths),
        environment_hash=environment_fingerprint(
            {
                "duckdb": duckdb.__version__,
                "benchmark": "incremental-order-etl-v2",
                "control_plane_source": control_source_hash,
            }
        ),
        requirements_hash=files_hash([root / "README.md"]),
    )
    control = ControlPlane(args.state)
    control.register(
        identity,
        REQUIRED_GATES,
        {"worktree": str(root), "control_plane_source": control_source_hash},
        ("result", "pytest", "skill_cli"),
    )
    control.claim(args.run_id, args.owner)
    control.record_gate(
        args.run_id,
        "clean_checkout",
        not dirty,
        "Git worktree is clean" if not dirty else f"dirty paths: {dirty}",
        ["git status --porcelain"],
    )

    test_log = artifact_dir / "pytest.txt"
    tests = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(root / "tests"),
            str(repo_root / "tests"),
        ],
        cwd=root,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PYTHONPATH": f"{root / 'src'}:{repo_root / 'src'}",
        },
    )
    test_log.write_text(tests.stdout + tests.stderr, encoding="utf-8")
    control.record_gate(
        args.run_id,
        "unit_tests",
        tests.returncode == 0,
        tests.stdout.strip().splitlines()[-1] if tests.stdout.strip() else "pytest produced no output",
        [str(test_log)],
    )

    skill_log = artifact_dir / "skill-cli.txt"
    skill_test = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            str(repo_root / "tests" / "test_skill_cli.py"),
        ],
        cwd=root,
        text=True,
        capture_output=True,
        env={
            **os.environ,
            "PYTHONPATH": f"{root / 'src'}:{repo_root / 'src'}",
        },
    )
    skill_log.write_text(skill_test.stdout + skill_test.stderr, encoding="utf-8")
    control.record_gate(
        args.run_id,
        "skill_cli",
        skill_test.returncode == 0,
        "the skill wrapper completed register-through-submit for two runs and compared them"
        if skill_test.returncode == 0
        else "the skill CLI lifecycle test failed",
        [str(skill_log)],
    )
    record_pass(
        control,
        args.run_id,
        "contract_traceability",
        "each stated order-event rule has a named test or gate",
        list(CONTRACT_TRACE),
    )

    pipeline = Pipeline(database)
    base = load_jsonl(fixtures / "base.jsonl")
    late = load_jsonl(fixtures / "late.jsonl")
    duplicates = load_jsonl(fixtures / "duplicates.jsonl")
    backfill = load_jsonl(fixtures / "backfill.jsonl")
    recovery = load_jsonl(fixtures / "recovery.jsonl")
    ingest_trap = load_jsonl(fixtures / "ingest_trap.jsonl")
    timezone = load_jsonl(fixtures / "timezone.jsonl")
    empty = load_jsonl(fixtures / "empty.jsonl")

    pipeline.process(base, "base")
    noop_snapshot = pipeline.snapshot().to_dict()
    noop_fails_late = not late_data_holds(noop_snapshot)

    before_empty = snapshot_semantics(pipeline.snapshot())
    pipeline.process(empty, "empty")
    volume_pass = snapshot_semantics(pipeline.snapshot()) == before_empty
    control.record_gate(
        args.run_id,
        "volume_anomaly",
        volume_pass,
        "an empty batch leaves current grain and checksums unchanged",
        [f"empty_events={len(empty)}", f"semantics={before_empty}"],
    )

    poison_rejected = False
    try:
        load_jsonl(fixtures / "poison.jsonl")
    except ValueError as exc:
        poison_rejected = "order_id" in str(exc)
    control.record_gate(
        args.run_id,
        "poison_records",
        poison_rejected and snapshot_semantics(pipeline.snapshot()) == before_empty,
        "a missing order_id fails closed and does not write",
        ["poison.jsonl raises ValueError on empty order_id"],
    )

    before_duplicate = snapshot_semantics(pipeline.snapshot())
    before_duplicate_counts = pipeline.counts()
    pipeline.process(duplicates, "duplicates")
    duplicate_pass = (
        pipeline.counts() == before_duplicate_counts
        and snapshot_semantics(pipeline.snapshot()) == before_duplicate
    )
    control.record_gate(
        args.run_id,
        "duplicates",
        duplicate_pass,
        "duplicate event ids do not change raw counts or semantic output",
        [
            f"counts_before={before_duplicate_counts}",
            f"checksums={before_duplicate['checksums']}",
        ],
    )

    pipeline.process(late, "late")
    snapshot = pipeline.snapshot().to_dict()
    late_pass = late_data_holds(snapshot)
    control.record_gate(
        args.run_id,
        "late_data",
        late_pass,
        "late completion replaces current order state and repairs the affected daily aggregate",
        [f"order_o3={ {row['order_id']: row for row in snapshot['orders_current']}['o3'] }"],
    )
    control.record_gate(
        args.run_id,
        "evaluator_sanity",
        noop_fails_late and late_pass,
        "the no-op after base fails late_data; the reference late batch passes",
        [
            f"noop_late_data={not noop_fails_late}",
            f"reference_late_data={late_pass}",
        ],
    )
    record_pass(
        control,
        args.run_id,
        "schema_contract",
        "current and daily tables keep declared columns and integer measures",
        [f"schema_holds={schema_holds(snapshot)}"],
    ) if schema_holds(snapshot) else control.record_gate(
        args.run_id,
        "schema_contract",
        False,
        "output columns or types drifted from the contract",
        [str(snapshot.keys())],
    )
    control.record_gate(
        args.run_id,
        "value_invariants",
        invariants_hold(snapshot),
        "statuses, amounts, and daily counts stay in the declared ranges",
        [f"invariants_hold={invariants_hold(snapshot)}"],
    )
    control.record_gate(
        args.run_id,
        "aggregate_grain",
        aggregate_grain_holds(snapshot),
        "daily revenue is summed from current completed orders at UTC date grain",
        [f"aggregate_grain_holds={aggregate_grain_holds(snapshot)}"],
    )

    before_backfill = snapshot_semantics(pipeline.snapshot())
    raw_before_backfill = pipeline.counts()["raw_order_events"]
    pipeline.process(backfill, "backfill")
    backfill_snapshot = pipeline.snapshot().to_dict()
    backfill_current = {row["order_id"]: row for row in backfill_snapshot["orders_current"]}
    backfill_pass = (
        backfill_current["o2"]["event_id"] == "e3"
        and snapshot_semantics(pipeline.snapshot()) == before_backfill
        and pipeline.counts()["raw_order_events"] == raw_before_backfill + 1
    )
    control.record_gate(
        args.run_id,
        "backfill",
        backfill_pass,
        "older backfill is retained in raw history without overwriting current state",
        [
            f"order_o2={backfill_current['o2']}",
            f"raw_rows={pipeline.counts()['raw_order_events']}",
        ],
    )

    pipeline.process(ingest_trap, "ingest-trap")
    event_time_snapshot = pipeline.snapshot().to_dict()
    control.record_gate(
        args.run_id,
        "event_time_contract",
        event_time_holds(event_time_snapshot),
        "a later ingest of an earlier event cannot replace current order state",
        [f"order_o1={ {row['order_id']: row for row in event_time_snapshot['orders_current']}['o1'] }"],
    )

    pipeline.process(timezone, "timezone")
    timezone_snapshot = pipeline.snapshot().to_dict()
    control.record_gate(
        args.run_id,
        "timezone",
        timezone_holds(timezone_snapshot),
        "an offset timestamp is stored and aggregated in UTC",
        [f"order_o5={ {row['order_id']: row for row in timezone_snapshot['orders_current']}.get('o5') }"],
    )

    before_replay = snapshot_semantics(pipeline.snapshot())
    counts_before_replay = pipeline.counts()
    pipeline.process(
        base + late + duplicates + backfill + ingest_trap + timezone,
        "replay",
    )
    replay_semantics = snapshot_semantics(pipeline.snapshot())
    idempotency_pass = (
        replay_semantics == before_replay
        and pipeline.counts() == counts_before_replay
    )
    control.record_gate(
        args.run_id,
        "idempotency",
        idempotency_pass,
        "replaying the entire input leaves counts and semantic checksums unchanged",
        [f"counts={counts_before_replay}", f"checksums={before_replay['checksums']}"],
    )
    control.record_gate(
        args.run_id,
        "key_stability",
        replay_semantics["key_sets"] == before_replay["key_sets"],
        "replay keeps the same order_id and event_date key sets",
        [f"key_sets={before_replay['key_sets']}"],
    )

    before_failure = snapshot_semantics(pipeline.snapshot())
    recovery_failed_cleanly = False
    try:
        pipeline.process(recovery, "recovery-attempt", failpoint="after_stage")
    except InjectedFailure:
        recovery_failed_cleanly = (
            snapshot_semantics(pipeline.snapshot()) == before_failure
            and pipeline.run_status("recovery-attempt") == "failed"
        )
    pipeline.process(recovery, "recovery-attempt")
    final_snapshot = pipeline.snapshot()
    final_current = {row["order_id"]: row for row in final_snapshot.to_dict()["orders_current"]}
    recovery_pass = (
        recovery_failed_cleanly
        and final_current["o4"]["status"] == "completed"
        and pipeline.run_status("recovery-attempt") == "completed"
    )
    control.record_gate(
        args.run_id,
        "recovery",
        recovery_pass,
        "injected failure rolls back business state; retry completes the same run id",
        [
            f"rollback_checksums={before_failure['checksums']}",
            f"recovery_status={pipeline.run_status('recovery-attempt')}",
        ],
    )

    full_db = artifact_dir / "full-refresh.duckdb"
    if full_db.exists():
        full_db.unlink()
    full_pipeline = Pipeline(full_db)
    full_pipeline.process(
        base + late + duplicates + backfill + ingest_trap + timezone + recovery,
        "full-refresh",
    )
    incremental_equivalent = same_semantics(final_snapshot, full_pipeline.snapshot())
    control.record_gate(
        args.run_id,
        "incremental_full_equivalence",
        incremental_equivalent,
        "incremental batches match a clean full refresh on keys and checksums",
        [
            f"incremental={snapshot_semantics(final_snapshot)}",
            f"full={snapshot_semantics(full_pipeline.snapshot())}",
        ],
    )
    semantic = snapshot_semantics(final_snapshot)
    control.record_gate(
        args.run_id,
        "semantic_equality",
        incremental_equivalent
        and schema_holds(final_snapshot.to_dict())
        and invariants_hold(final_snapshot.to_dict())
        and aggregate_grain_holds(final_snapshot.to_dict()),
        "key sets and aggregate checksums agree before the canonical hash",
        [f"checksums={semantic['checksums']}", f"hash={semantic['canonical_hash']}"],
    )

    for name in (
        "delivery_semantics",
        "snapshot_isolation",
        "scheduling_semantics",
    ):
        control.record_gate(
            args.run_id,
            name,
            None,
            "this practice task is a bounded batch file, not a platform runtime",
            [BATCH_CONTRACT],
            status="not_applicable",
            applicability_basis=BATCH_CONTRACT,
        )

    result_path = artifact_dir / "result.json"
    write_json(result_path, final_snapshot.to_dict())
    control.record_artifact(args.run_id, "result", result_path)
    control.record_artifact(args.run_id, "pytest", test_log)
    control.record_artifact(args.run_id, "skill_cli", skill_log)
    control.set_result_hash(args.run_id, final_snapshot.result_hash)
    control.record_measurement(
        args.run_id,
        "orders_current_rows",
        pipeline.counts()["orders_current"],
        "rows",
        [str(result_path)],
    )
    control.record_measurement(
        args.run_id,
        "revenue_cents_checksum",
        float(semantic["checksums"]["daily_revenue.revenue_cents"]),
        "cents",
        [str(result_path)],
    )
    control.record_outcome(
        args.run_id,
        "solved",
        "the benchmark completed normally and produced all required artifacts",
        [str(result_path), str(test_log), str(skill_log)],
    )
    verification = control.verify(args.run_id)
    if not verification.passed:
        raise RuntimeError(f"benchmark verification failed: {verification.to_dict()}")
    control.approve(args.run_id, "automated-gate-review")
    record = control.submit(args.run_id)
    run_record_path = artifact_dir / "run-record.json"
    write_json(run_record_path, record.to_dict())
    return record.to_dict()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", default=".")
    parser.add_argument("--artifacts", required=True)
    parser.add_argument("--state", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--attempt", type=int, required=True)
    parser.add_argument("--owner", required=True)
    args = parser.parse_args()
    record = run_benchmark(args)
    print(json.dumps({"run_id": args.run_id, "status": record["status"], "result_hash": record["result_hash"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
