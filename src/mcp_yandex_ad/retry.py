"""Retry helpers for transient API failures."""

from __future__ import annotations

import random
import time
from typing import Any, Callable, TypeVar

import requests
from tapi_yandex_direct import exceptions as direct_exceptions
from tapi_yandex_metrika import exceptions as metrica_exceptions

T = TypeVar("T")


def _sleep_seconds(
    attempt: int,
    base_delay: float,
    max_delay: float,
) -> float:
    delay = min(max_delay, base_delay * (2 ** max(0, attempt - 1)))
    # small jitter to avoid herd behaviour
    delay *= 0.8 + random.random() * 0.4  # noqa: S311 - non-crypto jitter
    return max(0.0, delay)


def is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    if isinstance(exc, direct_exceptions.YandexDirectRequestsLimitError):
        return True
    if isinstance(exc, direct_exceptions.YandexDirectNotEnoughUnitsError):
        return True
    if isinstance(exc, metrica_exceptions.YandexMetrikaLimitError):
        return True
    if isinstance(exc, metrica_exceptions.YandexMetrikaDownloadReportError):
        # Logs API export not ready yet
        return True

    # Some tapi errors carry Response with status_code
    response = getattr(exc, "response", None)
    status_code = getattr(response, "status_code", None)
    if isinstance(status_code, int) and (status_code == 429 or 500 <= status_code <= 599):
        return True

    return False


def with_retries(
    func: Callable[[], T],
    *,
    max_attempts: int,
    base_delay_seconds: float,
    max_delay_seconds: float,
    now: Callable[[], float] | None = None,
    sleep: Callable[[float], None] | None = None,
) -> T:
    if max_attempts <= 1:
        return func()

    now_fn = now or time.monotonic
    sleep_fn = sleep or time.sleep

    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not is_transient_error(exc):
                raise
            delay = _sleep_seconds(attempt, base_delay_seconds, max_delay_seconds)
            # keep a monotonic read so tests can inject clock if needed
            _ = now_fn()
            sleep_fn(delay)
    assert last_exc is not None
    raise last_exc

