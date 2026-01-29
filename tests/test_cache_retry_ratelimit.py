import requests

from mcp_yandex_ad.cache import TTLCache
from mcp_yandex_ad.ratelimit import RateLimiter
from mcp_yandex_ad.retry import with_retries


def test_ttl_cache_get_or_set_expires():
    now = 100.0

    def clock():
        return now

    cache = TTLCache(10, now=clock)
    calls = {"count": 0}

    def factory():
        calls["count"] += 1
        return {"ok": True}

    assert cache.get_or_set("k", factory) == {"ok": True}
    assert cache.get_or_set("k", factory) == {"ok": True}
    assert calls["count"] == 1

    now = 111.0
    assert cache.get("k") is None
    assert cache.get_or_set("k", factory) == {"ok": True}
    assert calls["count"] == 2


def test_rate_limiter_sleeps_when_exceeded():
    now = 0.0
    sleeps: list[float] = []

    def clock():
        return now

    def sleeper(seconds: float):
        sleeps.append(seconds)

    limiter = RateLimiter(2, now=clock, sleep=sleeper)
    limiter.acquire()
    limiter.acquire()
    limiter.acquire()
    assert sleeps, "expected a sleep to enforce RPS window"


def test_with_retries_retries_transient_then_succeeds():
    calls = {"n": 0}
    slept: list[float] = []

    def sleeper(seconds: float):
        slept.append(seconds)

    def func():
        calls["n"] += 1
        if calls["n"] < 3:
            raise requests.Timeout("timeout")
        return "ok"

    assert (
        with_retries(
            func,
            max_attempts=5,
            base_delay_seconds=0.01,
            max_delay_seconds=0.02,
            sleep=sleeper,
        )
        == "ok"
    )
    assert calls["n"] == 3
    assert slept

