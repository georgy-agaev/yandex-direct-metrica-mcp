"""Simple per-process rate limiter."""

from __future__ import annotations

import time
from typing import Callable


class RateLimiter:
    def __init__(self, rps: int, *, now: Callable[[], float] | None = None, sleep: Callable[[float], None] | None = None) -> None:
        self._rps = max(0, int(rps))
        self._now = now or time.monotonic
        self._sleep = sleep or time.sleep
        self._timestamps: list[float] = []

    @property
    def enabled(self) -> bool:
        return self._rps > 0

    def acquire(self) -> None:
        if self._rps <= 0:
            return
        now = self._now()
        window_start = now - 1.0
        while self._timestamps and self._timestamps[0] <= window_start:
            self._timestamps.pop(0)
        if len(self._timestamps) >= self._rps:
            wait_time = self._timestamps[0] - window_start
            if wait_time > 0:
                self._sleep(wait_time)
                now = self._now()
                window_start = now - 1.0
                while self._timestamps and self._timestamps[0] <= window_start:
                    self._timestamps.pop(0)
        self._timestamps.append(self._now())

