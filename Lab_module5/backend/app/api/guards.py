"""Per-client rate limiting (single instance, in memory), one limiter per endpoint group."""

import threading
import time
from collections import defaultdict, deque
from collections.abc import Callable


class RateLimited(Exception):
    def __init__(self, retry_after_s: float, window: str) -> None:
        super().__init__(f"Too many requests this {window}; try again later.")
        self.retry_after_s = retry_after_s


class RateLimiter:
    WINDOWS = (("minute", 60.0), ("day", 86400.0))

    def __init__(
        self, per_minute: int, per_day: int, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self._limits = {"minute": per_minute, "day": per_day}
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, client: str) -> None:
        """Record one request for `client`, or raise RateLimited."""
        now = self._clock()
        with self._lock:
            hits = self._hits[client]
            while hits and now - hits[0] >= 86400:
                hits.popleft()
            for window, seconds in self.WINDOWS:
                recent = [t for t in hits if now - t < seconds]
                if len(recent) >= self._limits[window]:
                    raise RateLimited(seconds - (now - recent[0]), window)
            hits.append(now)
