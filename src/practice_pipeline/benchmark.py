"""Execute the semantic gates and write a signed control-plane run record."""

from __future__ import annotations

import argparse
import json
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

REQUIRED_GATES = (
    "clean_checkout",
    "unit_tests",
    "late_data",
    "duplicates",
    "backfill",
    "idempotency",
    "recovery",
)


def git_value(root: Path, *args: str) -> str:
    proc = subprocess.run(
        ["git", *args], cwd=root, text=True, capture_output=True, check=True
    )
    return proc.stdout.strip()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    root = Path(args.worktree).resolve()
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
                "benchmark": "incremental-order-etl-v1",
                "control_plane_source": control_source_hash,
            }
        ),
    )
    control = ControlPlane(args.state)
    control.register(
        identity,
        REQUIRED_GATES,
        {"worktree": str(root), "control_plane_source": control_source_hash},
    )
    control.claim(args.run_id, args.owner)
    control.record_gate(
        args.run_id,
        "clean_checkout",
        not dirty,
        "Git worktree is clean" if not dirty else f"dirty paths: {dirty}",
    )

    test_log = artifact_dir / "pytest.txt"
    tests = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(root / "tests")],
        cwd=root,
        text=True,
        capture_output=True,
        env={**__import__("os").environ, "PYTHONPATH": str(root / "src")},
    )
    test_log.write_text(tests.stdout + tests.stderr, encoding="utf-8")
    control.record_gate(
        args.run_id,
        "unit_tests",
        tests.returncode == 0,
        tests.stdout.strip().splitlines()[-1] if tests.stdout.strip() else "pytest produced no output",
        [str(test_log)],
    )

    pipeline = Pipeline(database)
    base = load_jsonl(fixtures / "base.jsonl")
    late = load_jsonl(fixtures / "late.jsonl")
    duplicates = load_jsonl(fixtures / "duplicates.jsonl")
    backfill = load_jsonl(fixtures / "backfill.jsonl")
    recovery = load_jsonl(fixtures / "recovery.jsonl")

    pipeline.process(base, "base")
    before_duplicate_counts = pipeline.counts()
    before_duplicate_hash = pipeline.snapshot().result_hash
    pipeline.process(duplicates, "duplicates")
    duplicate_pass = (
        pipeline.counts() == before_duplicate_counts
        and pipeline.snapshot().result_hash == before_duplicate_hash
    )
    control.record_gate(
        args.run_id,
        "duplicates",
        duplicate_pass,
        "duplicate event ids do not change raw counts or materialized output",
    )

    pipeline.process(late, "late")
    snapshot = pipeline.snapshot().to_dict()
    current = {row["order_id"]: row for row in snapshot["orders_current"]}
    revenue = {row["event_date"]: row for row in snapshot["daily_revenue"]}
    late_pass = current["o3"]["status"] == "completed" and revenue["2026-01-02"] == {
        "event_date": "2026-01-02",
        "completed_orders": 2,
        "revenue_cents": 3000,
    }
    control.record_gate(
        args.run_id,
        "late_data",
        late_pass,
        "late completion replaces current order state and repairs the affected daily aggregate",
    )

    before_backfill = pipeline.snapshot().result_hash
    raw_before_backfill = pipeline.counts()["raw_order_events"]
    pipeline.process(backfill, "backfill")
    backfill_snapshot = pipeline.snapshot().to_dict()
    backfill_current = {row["order_id"]: row for row in backfill_snapshot["orders_current"]}
    backfill_pass = (
        backfill_current["o2"]["event_id"] == "e3"
        and pipeline.snapshot().result_hash == before_backfill
        and pipeline.counts()["raw_order_events"] == raw_before_backfill + 1
    )
    control.record_gate(
        args.run_id,
        "backfill",
        backfill_pass,
        "older backfill is retained in raw history without overwriting current state",
    )

    before_replay = pipeline.snapshot().result_hash
    counts_before_replay = pipeline.counts()
    pipeline.process(base + late + duplicates + backfill, "replay")
    idempotency_pass = (
        pipeline.snapshot().result_hash == before_replay
        and pipeline.counts() == counts_before_replay
    )
    control.record_gate(
        args.run_id,
        "idempotency",
        idempotency_pass,
        "replaying the entire input leaves row counts and result hash unchanged",
    )

    before_failure = pipeline.snapshot().result_hash
    recovery_failed_cleanly = False
    try:
        pipeline.process(recovery, "recovery-attempt", failpoint="after_stage")
    except InjectedFailure:
        recovery_failed_cleanly = (
            pipeline.snapshot().result_hash == before_failure
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
    )

    result_path = artifact_dir / "result.json"
    write_json(result_path, final_snapshot.to_dict())
    control.record_artifact(args.run_id, "result", result_path)
    control.record_artifact(args.run_id, "pytest", test_log)
    control.set_result_hash(args.run_id, final_snapshot.result_hash)
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
