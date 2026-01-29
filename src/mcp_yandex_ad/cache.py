"""Small in-memory TTL cache (process/session scoped)."""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable


@dataclass
class _Entry:
    value: Any
    expires_at: float


class TTLCache:
    def __init__(self, ttl_seconds: float, *, now: Callable[[], float] | None = None) -> None:
        self._ttl_seconds = float(ttl_seconds)
        self._now = now or time.monotonic
        self._items: dict[str, _Entry] = {}

    def get(self, key: str) -> Any | None:
        entry = self._items.get(key)
        if entry is None:
            return None
        if entry.expires_at <= self._now():
            self._items.pop(key, None)
            return None
        return entry.value

    def set(self, key: str, value: Any) -> None:
        self._items[key] = _Entry(value=value, expires_at=self._now() + self._ttl_seconds)

    def clear(self) -> None:
        self._items.clear()

    def get_or_set(self, key: str, factory: Callable[[], Any]) -> Any:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = factory()
        self.set(key, value)
        return value

