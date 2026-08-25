"""Atomic, lock-protected JSON storage."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback keeps atomic replace.
    fcntl = None


def empty_state() -> dict[str, Any]:
    return {"version": 1, "updated_at": None, "runs": {}, "events": []}


class AtomicJsonStore:
    def __init__(self, path: str | Path):
        self.path = Path(path).expanduser().resolve()
        self.lock_path = self.path.with_suffix(self.path.suffix + ".lock")

    @contextmanager
    def _locked(self) -> Iterator[None]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _read_unlocked(self) -> dict[str, Any]:
        if not self.path.is_file():
            return empty_state()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return empty_state()
        if not isinstance(data, dict) or data.get("version") != 1:
            return empty_state()
        data.setdefault("runs", {})
        data.setdefault("events", [])
        return data

    def load(self) -> dict[str, Any]:
        with self._locked():
            return self._read_unlocked()

    def update(self, mutate: Callable[[dict[str, Any]], Any]) -> Any:
        with self._locked():
            state = self._read_unlocked()
            result = mutate(state)
            self._write_unlocked(state)
            return result

    def _write_unlocked(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(
            dir=self.path.parent,
            prefix=f".{self.path.name}-",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, ensure_ascii=True, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
