from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from practice_pipeline.pipeline import InjectedFailure, Pipeline, load_jsonl
from practice_pipeline.semantics import (
    aggregate_grain_holds,
    event_time_holds,
    invariants_hold,
    late_data_holds,
    same_semantics,
    schema_holds,
    snapshot_semantics,
    timezone_holds,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def pipeline() -> Pipeline:
    with tempfile.TemporaryDirectory() as directory:
        yield Pipeline(Path(directory) / "test.duckdb")


def events(name: str):
    return load_jsonl(FIXTURES / name)


def test_late_data_repairs_current_state_and_aggregate(pipeline: Pipeline) -> None:
    pipeline.process(events("base.jsonl"), "base")
    assert not late_data_holds(pipeline.snapshot().to_dict())
    pipeline.process(events("late.jsonl"), "late")
    snapshot = pipeline.snapshot().to_dict()
    assert late_data_holds(snapshot)
    assert schema_holds(snapshot)
    assert invariants_hold(snapshot)
    assert aggregate_grain_holds(snapshot)


def test_duplicates_are_ignored(pipeline: Pipeline) -> None:
    pipeline.process(events("base.jsonl"), "base")
    before = (pipeline.counts(), snapshot_semantics(pipeline.snapshot()))
    pipeline.process(events("duplicates.jsonl"), "duplicates")
    assert (pipeline.counts(), snapshot_semantics(pipeline.snapshot())) == before


def test_older_backfill_does_not_replace_current_state(pipeline: Pipeline) -> None:
    pipeline.process(events("base.jsonl"), "base")
    before = snapshot_semantics(pipeline.snapshot())
    pipeline.process(events("backfill.jsonl"), "backfill")
    orders = {row["order_id"]: row for row in pipeline.snapshot().to_dict()["orders_current"]}
    assert orders["o2"]["event_id"] == "e3"
    assert snapshot_semantics(pipeline.snapshot()) == before
    assert pipeline.counts()["raw_order_events"] == 5


def test_event_time_beats_later_ingest(pipeline: Pipeline) -> None:
    pipeline.process(events("base.jsonl"), "base")
    pipeline.process(events("ingest_trap.jsonl"), "ingest-trap")
    snapshot = pipeline.snapshot().to_dict()
    assert event_time_holds(snapshot)
    assert pipeline.counts()["raw_order_events"] == 5


def test_timezone_offset_lands_on_utc_date(pipeline: Pipeline) -> None:
    pipeline.process(events("base.jsonl"), "base")
    pipeline.process(events("timezone.jsonl"), "timezone")
    snapshot = pipeline.snapshot().to_dict()
    assert timezone_holds(snapshot)
    assert aggregate_grain_holds(snapshot)


def test_empty_batch_does_not_clear_state(pipeline: Pipeline) -> None:
    pipeline.process(events("base.jsonl"), "base")
    before = (pipeline.counts(), snapshot_semantics(pipeline.snapshot()))
    pipeline.process(events("empty.jsonl"), "empty")
    assert (pipeline.counts(), snapshot_semantics(pipeline.snapshot())) == before


def test_poison_row_is_rejected_without_writing(pipeline: Pipeline) -> None:
    pipeline.process(events("base.jsonl"), "base")
    before = snapshot_semantics(pipeline.snapshot())
    with pytest.raises(ValueError, match="order_id"):
        events("poison.jsonl")
    assert snapshot_semantics(pipeline.snapshot()) == before


def test_incremental_matches_full_refresh() -> None:
    all_events = (
        events("base.jsonl")
        + events("late.jsonl")
        + events("duplicates.jsonl")
        + events("backfill.jsonl")
        + events("ingest_trap.jsonl")
        + events("timezone.jsonl")
        + events("recovery.jsonl")
    )
    with tempfile.TemporaryDirectory() as directory:
        incremental = Pipeline(Path(directory) / "incremental.duckdb")
        incremental.process(events("base.jsonl"), "base")
        incremental.process(events("late.jsonl"), "late")
        incremental.process(events("duplicates.jsonl"), "duplicates")
        incremental.process(events("backfill.jsonl"), "backfill")
        incremental.process(events("ingest_trap.jsonl"), "ingest-trap")
        incremental.process(events("timezone.jsonl"), "timezone")
        incremental.process(events("recovery.jsonl"), "recovery")
        full = Pipeline(Path(directory) / "full.duckdb")
        full.process(all_events, "full")
        assert same_semantics(incremental.snapshot(), full.snapshot())
        assert aggregate_grain_holds(full.snapshot().to_dict())


def test_full_replay_is_idempotent(pipeline: Pipeline) -> None:
    all_events = (
        events("base.jsonl")
        + events("late.jsonl")
        + events("duplicates.jsonl")
        + events("backfill.jsonl")
    )
    pipeline.process(all_events, "first")
    before = (pipeline.counts(), snapshot_semantics(pipeline.snapshot()))
    pipeline.process(all_events, "second")
    assert (pipeline.counts(), snapshot_semantics(pipeline.snapshot())) == before


def test_failure_rolls_back_and_retry_recovers(pipeline: Pipeline) -> None:
    pipeline.process(events("base.jsonl"), "base")
    before = (pipeline.counts(), snapshot_semantics(pipeline.snapshot()))
    with pytest.raises(InjectedFailure):
        pipeline.process(events("recovery.jsonl"), "recovery", failpoint="after_stage")
    assert (pipeline.counts(), snapshot_semantics(pipeline.snapshot())) == before
    assert pipeline.run_status("recovery") == "failed"
    pipeline.process(events("recovery.jsonl"), "recovery")
    assert pipeline.run_status("recovery") == "completed"
    assert pipeline.counts()["orders_current"] == 4
