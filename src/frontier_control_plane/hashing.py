"""Canonical hashing helpers used by adapters and benchmarks."""

from __future__ import annotations

import hashlib
import json
import platform
import sqlite3
import sys
from pathlib import Path
from typing import Any, Iterable


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256_bytes(payload)


def semantic_check(
    tables: dict[str, Iterable[dict[str, Any]]],
    keys: dict[str, tuple[str, ...]],
    checksums: dict[str, tuple[str, ...]],
) -> dict[str, Any]:
    """Compare grain before hashing: key sets, then checksums, then digest."""
    key_sets: dict[str, list[list[Any]]] = {}
    sums: dict[str, int | float] = {}
    for table, rows in tables.items():
        if table not in keys:
            raise ValueError(f"no key fields declared for {table}")
        extracted: list[list[Any]] = []
        materialized = list(rows)
        for row in materialized:
            extracted.append([row[field] for field in keys[table]])
        unique = {tuple(item) for item in extracted}
        if len(unique) != len(extracted):
            raise ValueError(f"duplicate business keys in {table}")
        key_sets[table] = sorted(extracted)
        for field in checksums.get(table, ()):
            sums[f"{table}.{field}"] = sum(row[field] for row in materialized)
    return {
        "key_sets": key_sets,
        "checksums": sums,
        "canonical_hash": canonical_hash(
            {"checksums": sums, "key_sets": key_sets, "tables": tables}
        ),
    }


def semantic_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return left["key_sets"] == right["key_sets"] and left["checksums"] == right["checksums"]


def files_hash(paths: Iterable[str | Path]) -> str:
    rows = []
    for raw in sorted((Path(item).resolve() for item in paths), key=str):
        rows.append({"name": raw.name, "sha256": sha256_file(raw), "size": raw.stat().st_size})
    return canonical_hash(rows)


def environment_fingerprint(extra: dict[str, Any] | None = None) -> str:
    payload = {
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "sqlite": sqlite3.sqlite_version,
        "extra": extra or {},
    }
    return canonical_hash(payload)
