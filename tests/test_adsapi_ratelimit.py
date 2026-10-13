import pytest

from adsapi.ratelimit import RateLimiter


def make(limit):
    t = [0.0]
    return RateLimiter(limit, 60, clock=lambda: t[0]), t


def test_allows_up_to_limit_then_blocks():
    rl, _ = make(3)
    assert [rl.hit("a") for _ in range(3)] == [None, None, None]
    assert rl.hit("a") == pytest.approx(60)


def test_retry_after_counts_down():
    rl, t = make(1)
    rl.hit("a")
    t[0] = 45.0
    assert rl.hit("a") == pytest.approx(15)


def test_keys_are_independent():
    rl, _ = make(1)
    rl.hit("a")
    assert rl.hit("b") is None


def test_window_resets():
    rl, t = make(1)
    rl.hit("a")
    t[0] = 61.0
    assert rl.hit("a") is None
