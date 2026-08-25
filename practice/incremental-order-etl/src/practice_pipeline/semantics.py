"""Task-local grain, invariant, and semantic-equality checks."""

from __future__ import annotations

from typing import Any

from frontier_control_plane import semantic_check, semantic_equal

from .pipeline import OrderEvent, Snapshot

SNAPSHOT_KEYS = {
    "orders_current": ("order_id",),
    "daily_revenue": ("event_date",),
}
SNAPSHOT_CHECKSUMS = {
    "orders_current": ("amount_cents",),
    "daily_revenue": ("revenue_cents", "completed_orders"),
}
ORDER_COLUMNS = {
    "order_id",
    "event_id",
    "event_time",
    "ingest_time",
    "status",
    "amount_cents",
}
REVENUE_COLUMNS = {"event_date", "completed_orders", "revenue_cents"}
ALLOWED_STATUSES = {"created", "completed", "cancelled"}
CONTRACT_TRACE = (
    "latest order state uses event_time, then ingest_time, then event_id",
    "daily completed revenue is rebuilt only for affected UTC dates",
    "duplicate event_id rows do not change counts or output",
    "older backfill stays in raw history without replacing current state",
    "replay of the same input leaves canonical output unchanged",
    "an injected mid-batch failure rolls back business tables",
)


def snapshot_semantics(snapshot: Snapshot | dict[str, Any]) -> dict[str, Any]:
    data = snapshot.to_dict() if isinstance(snapshot, Snapshot) else snapshot
    return semantic_check(data, SNAPSHOT_KEYS, SNAPSHOT_CHECKSUMS)


def same_semantics(left: Snapshot | dict[str, Any], right: Snapshot | dict[str, Any]) -> bool:
    return semantic_equal(snapshot_semantics(left), snapshot_semantics(right))


def schema_holds(snapshot: dict[str, Any]) -> bool:
    orders = snapshot["orders_current"]
    revenue = snapshot["daily_revenue"]
    return (
        all(set(row) == ORDER_COLUMNS for row in orders)
        and all(set(row) == REVENUE_COLUMNS for row in revenue)
        and all(isinstance(row["amount_cents"], int) for row in orders)
        and all(isinstance(row["revenue_cents"], int) for row in revenue)
        and all(isinstance(row["completed_orders"], int) for row in revenue)
    )


def invariants_hold(snapshot: dict[str, Any]) -> bool:
    orders = snapshot["orders_current"]
    revenue = snapshot["daily_revenue"]
    return (
        all(row["amount_cents"] >= 0 for row in orders)
        and all(row["status"] in ALLOWED_STATUSES for row in orders)
        and all(row["revenue_cents"] >= 0 for row in revenue)
        and all(row["completed_orders"] >= 0 for row in revenue)
    )


def aggregate_grain_holds(snapshot: dict[str, Any]) -> bool:
    completed: dict[str, list[dict[str, Any]]] = {}
    for row in snapshot["orders_current"]:
        if row["status"] != "completed":
            continue
        event_date = row["event_time"][:10]
        completed.setdefault(event_date, []).append(row)
    revenue = {row["event_date"]: row for row in snapshot["daily_revenue"]}
    if set(completed) != set(revenue):
        return False
    for event_date, rows in completed.items():
        daily = revenue[event_date]
        if daily["completed_orders"] != len(rows):
            return False
        if daily["revenue_cents"] != sum(row["amount_cents"] for row in rows):
            return False
    return True


def late_data_holds(snapshot: dict[str, Any]) -> bool:
    orders = {row["order_id"]: row for row in snapshot["orders_current"]}
    revenue = {row["event_date"]: row for row in snapshot["daily_revenue"]}
    return orders.get("o3", {}).get("status") == "completed" and revenue.get(
        "2026-01-02"
    ) == {
        "event_date": "2026-01-02",
        "completed_orders": 2,
        "revenue_cents": 3000,
    }


def event_time_holds(snapshot: dict[str, Any]) -> bool:
    orders = {row["order_id"]: row for row in snapshot["orders_current"]}
    return orders.get("o1", {}).get("event_id") == "e2"


def timezone_holds(snapshot: dict[str, Any]) -> bool:
    orders = {row["order_id"]: row for row in snapshot["orders_current"]}
    revenue = {row["event_date"]: row for row in snapshot["daily_revenue"]}
    return (
        orders.get("o5", {}).get("event_time") == "2026-01-01T23:30:00Z"
        and "2026-01-02" in revenue
        and revenue.get("2026-01-01", {}).get("revenue_cents") == 1750
    )


def reject_poison(raw: dict[str, Any]) -> None:
    OrderEvent.from_dict(raw)
