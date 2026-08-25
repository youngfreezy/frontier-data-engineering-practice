from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from practice_pipeline.pipeline import InjectedFailure, Pipeline, load_jsonl

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


@pytest.fixture
def pipeline() -> Pipeline:
    with tempfile.TemporaryDirectory() as directory:
        yield Pipeline(Path(directory) / "test.duckdb")


def events(name: str):
    return load_jsonl(FIXTURES / name)


def test_late_data_repairs_current_state_and_aggregate(pipeline: Pipeline) -> None:
    pipeline.process(events("base.jsonl"), "base")
    pipeline.process(events("late.jsonl"), "late")
    snapshot = pipeline.snapshot().to_dict()
    orders = {row["order_id"]: row for row in snapshot["orders_current"]}
    daily = {row["event_date"]: row for row in snapshot["daily_revenue"]}
    assert orders["o3"]["status"] == "completed"
    assert daily["2026-01-02"]["revenue_cents"] == 3000


def test_duplicates_are_ignored(pipeline: Pipeline) -> None:
    pipeline.process(events("base.jsonl"), "base")
    before = (pipeline.counts(), pipeline.snapshot().result_hash)
    pipeline.process(events("duplicates.jsonl"), "duplicates")
    assert (pipeline.counts(), pipeline.snapshot().result_hash) == before


def test_older_backfill_does_not_replace_current_state(pipeline: Pipeline) -> None:
    pipeline.process(events("base.jsonl"), "base")
    before = pipeline.snapshot().result_hash
    pipeline.process(events("backfill.jsonl"), "backfill")
    orders = {row["order_id"]: row for row in pipeline.snapshot().to_dict()["orders_current"]}
    assert orders["o2"]["event_id"] == "e3"
    assert pipeline.snapshot().result_hash == before
    assert pipeline.counts()["raw_order_events"] == 5


def test_full_replay_is_idempotent(pipeline: Pipeline) -> None:
    all_events = (
        events("base.jsonl")
        + events("late.jsonl")
        + events("duplicates.jsonl")
        + events("backfill.jsonl")
    )
    pipeline.process(all_events, "first")
    before = (pipeline.counts(), pipeline.snapshot().result_hash)
    pipeline.process(all_events, "second")
    assert (pipeline.counts(), pipeline.snapshot().result_hash) == before


def test_failure_rolls_back_and_retry_recovers(pipeline: Pipeline) -> None:
    pipeline.process(events("base.jsonl"), "base")
    before = (pipeline.counts(), pipeline.snapshot().result_hash)
    with pytest.raises(InjectedFailure):
        pipeline.process(events("recovery.jsonl"), "recovery", failpoint="after_stage")
    assert (pipeline.counts(), pipeline.snapshot().result_hash) == before
    assert pipeline.run_status("recovery") == "failed"
    pipeline.process(events("recovery.jsonl"), "recovery")
    assert pipeline.run_status("recovery") == "completed"
    assert pipeline.counts()["orders_current"] == 4

