"""Transactional incremental processing for immutable order events."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import duckdb
from frontier_control_plane import canonical_hash


class InjectedFailure(RuntimeError):
    """Raised at a named failpoint to prove rollback and recovery behavior."""


@dataclass(frozen=True)
class OrderEvent:
    event_id: str
    order_id: str
    event_time: str
    ingest_time: str
    status: str
    amount_cents: int

    def __post_init__(self) -> None:
        for name in ("event_id", "order_id", "event_time", "ingest_time", "status"):
            if not str(getattr(self, name)).strip():
                raise ValueError(f"{name} is required")
        if self.status not in {"created", "completed", "cancelled"}:
            raise ValueError(f"unsupported status {self.status!r}")
        if self.amount_cents < 0:
            raise ValueError("amount_cents cannot be negative")

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "OrderEvent":
        return cls(
            event_id=str(value["event_id"]),
            order_id=str(value["order_id"]),
            event_time=str(value["event_time"]),
            ingest_time=str(value["ingest_time"]),
            status=str(value["status"]),
            amount_cents=int(value["amount_cents"]),
        )


@dataclass(frozen=True)
class Snapshot:
    orders_current: tuple[dict[str, Any], ...]
    daily_revenue: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "orders_current": list(self.orders_current),
            "daily_revenue": list(self.daily_revenue),
        }

    @property
    def result_hash(self) -> str:
        return canonical_hash(self.to_dict())


def load_jsonl(path: str | Path) -> list[OrderEvent]:
    rows = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(OrderEvent.from_dict(json.loads(line)))
    return rows


class Pipeline:
    """Owns one DuckDB database and applies batches atomically."""

    def __init__(self, database: str | Path):
        self.database = Path(database)
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> duckdb.DuckDBPyConnection:
        return duckdb.connect(str(self.database))

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS raw_order_events (
                    event_id VARCHAR PRIMARY KEY,
                    order_id VARCHAR NOT NULL,
                    event_time TIMESTAMPTZ NOT NULL,
                    ingest_time TIMESTAMPTZ NOT NULL,
                    status VARCHAR NOT NULL,
                    amount_cents BIGINT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS orders_current (
                    order_id VARCHAR PRIMARY KEY,
                    event_id VARCHAR NOT NULL,
                    event_time TIMESTAMPTZ NOT NULL,
                    ingest_time TIMESTAMPTZ NOT NULL,
                    status VARCHAR NOT NULL,
                    amount_cents BIGINT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS daily_revenue (
                    event_date DATE PRIMARY KEY,
                    completed_orders BIGINT NOT NULL,
                    revenue_cents BIGINT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id VARCHAR PRIMARY KEY,
                    status VARCHAR NOT NULL,
                    input_events BIGINT NOT NULL,
                    error VARCHAR
                );
                """
            )

    def process(
        self,
        events: Iterable[OrderEvent],
        run_id: str,
        *,
        failpoint: str | None = None,
    ) -> Snapshot:
        batch = tuple(events)
        if not run_id.strip():
            raise ValueError("run_id is required")
        affected_orders = sorted({event.order_id for event in batch})
        conn = self._connect()
        try:
            conn.execute("BEGIN TRANSACTION")
            conn.execute(
                """
                INSERT INTO pipeline_runs VALUES (?, 'running', ?, NULL)
                ON CONFLICT (run_id) DO UPDATE SET
                    status = 'running', input_events = EXCLUDED.input_events, error = NULL
                """,
                [run_id, len(batch)],
            )
            old_dates = self._current_dates(conn, affected_orders)
            if batch:
                conn.executemany(
                    """
                    INSERT INTO raw_order_events VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    [
                        [
                            event.event_id,
                            event.order_id,
                            event.event_time,
                            event.ingest_time,
                            event.status,
                            event.amount_cents,
                        ]
                        for event in batch
                    ],
                )
            if failpoint == "after_stage":
                raise InjectedFailure("injected failure after raw staging")
            for order_id in affected_orders:
                conn.execute(
                    """
                    INSERT INTO orders_current
                    SELECT order_id, event_id, event_time, ingest_time, status, amount_cents
                    FROM raw_order_events
                    WHERE order_id = ?
                    ORDER BY event_time DESC, ingest_time DESC, event_id DESC
                    LIMIT 1
                    ON CONFLICT (order_id) DO UPDATE SET
                        event_id = EXCLUDED.event_id,
                        event_time = EXCLUDED.event_time,
                        ingest_time = EXCLUDED.ingest_time,
                        status = EXCLUDED.status,
                        amount_cents = EXCLUDED.amount_cents
                    """,
                    [order_id],
                )
            new_dates = self._current_dates(conn, affected_orders)
            affected_dates = sorted(old_dates | new_dates)
            for event_date in affected_dates:
                conn.execute("DELETE FROM daily_revenue WHERE event_date = ?", [event_date])
                conn.execute(
                    """
                    INSERT INTO daily_revenue
                    SELECT
                        CAST(event_time AT TIME ZONE 'UTC' AS DATE) AS event_date,
                        COUNT(*) AS completed_orders,
                        SUM(amount_cents) AS revenue_cents
                    FROM orders_current
                    WHERE status = 'completed'
                      AND CAST(event_time AT TIME ZONE 'UTC' AS DATE) = ?
                    GROUP BY 1
                    """,
                    [event_date],
                )
            if failpoint == "before_commit":
                raise InjectedFailure("injected failure before commit")
            conn.execute("UPDATE pipeline_runs SET status = 'completed' WHERE run_id = ?", [run_id])
            conn.execute("COMMIT")
        except Exception as exc:
            conn.execute("ROLLBACK")
            conn.execute(
                """
                INSERT INTO pipeline_runs VALUES (?, 'failed', ?, ?)
                ON CONFLICT (run_id) DO UPDATE SET
                    status = 'failed', input_events = EXCLUDED.input_events, error = EXCLUDED.error
                """,
                [run_id, len(batch), str(exc)],
            )
            raise
        finally:
            conn.close()
        return self.snapshot()

    @staticmethod
    def _current_dates(
        conn: duckdb.DuckDBPyConnection, order_ids: list[str]
    ) -> set[str]:
        if not order_ids:
            return set()
        placeholders = ",".join("?" for _ in order_ids)
        rows = conn.execute(
            f"""
            SELECT DISTINCT CAST(event_time AT TIME ZONE 'UTC' AS DATE)::VARCHAR
            FROM orders_current WHERE order_id IN ({placeholders})
            """,
            order_ids,
        ).fetchall()
        return {str(row[0]) for row in rows}

    def snapshot(self) -> Snapshot:
        with self._connect() as conn:
            current_rows = conn.execute(
                """
                SELECT
                    order_id,
                    event_id,
                    strftime(event_time AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%SZ'),
                    strftime(ingest_time AT TIME ZONE 'UTC', '%Y-%m-%dT%H:%M:%SZ'),
                    status,
                    amount_cents
                FROM orders_current ORDER BY order_id
                """
            ).fetchall()
            revenue_rows = conn.execute(
                """
                SELECT event_date::VARCHAR, completed_orders, revenue_cents
                FROM daily_revenue ORDER BY event_date
                """
            ).fetchall()
        return Snapshot(
            orders_current=tuple(
                {
                    "order_id": row[0],
                    "event_id": row[1],
                    "event_time": row[2],
                    "ingest_time": row[3],
                    "status": row[4],
                    "amount_cents": row[5],
                }
                for row in current_rows
            ),
            daily_revenue=tuple(
                {
                    "event_date": row[0],
                    "completed_orders": row[1],
                    "revenue_cents": row[2],
                }
                for row in revenue_rows
            ),
        )

    def counts(self) -> dict[str, int]:
        with self._connect() as conn:
            return {
                table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ("raw_order_events", "orders_current", "daily_revenue")
            }

    def run_status(self, run_id: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT status FROM pipeline_runs WHERE run_id = ?", [run_id]
            ).fetchone()
        return str(row[0]) if row else None
