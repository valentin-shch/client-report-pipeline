from __future__ import annotations

import time
from typing import Callable


class RateLimiter:
    """Fixed window per key, in memory. One process on one free instance, so
    there's nothing to share state with."""

    def __init__(self, limit: int, window_s: float, clock: Callable[[], float] = time.monotonic):
        self.limit = limit
        self.window_s = window_s
        self.clock = clock
        self._windows: dict[str, tuple[float, int]] = {}

    def hit(self, key: str) -> float | None:
        """None if allowed, otherwise seconds until the window resets."""
        now = self.clock()
        start, count = self._windows.get(key, (now, 0))
        if now - start >= self.window_s:
            start, count = now, 0
        if count >= self.limit:
            return self.window_s - (now - start)
        if len(self._windows) > 10_000:  # forget long-gone callers
            self._windows = {k: v for k, v in self._windows.items() if now - v[0] < self.window_s}
        self._windows[key] = (start, count + 1)
        return None
