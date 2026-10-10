"""Wrappers that add quota protection to any LLMClient (open/closed principle).

Production wiring (outermost first):
    CircuitBreaker → Retrying → ConcurrencyLimited → Paced → GeminiClient
"""

import logging
import threading
import time
from collections.abc import Callable

from app.domain.errors import LLMOverloaded, LLMQuotaExceeded, LLMUnavailable
from app.domain.ports import LLMClient, LLMRequest, LLMResponse

logger = logging.getLogger(__name__)


class PacedLLMClient:
    """Keeps consecutive calls at least `min_interval_s` apart (stays under per-minute limits)."""

    def __init__(
        self,
        inner: LLMClient,
        min_interval_s: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner, self._interval, self._clock, self._sleep = inner, min_interval_s, clock, sleep
        self._lock = threading.Lock()
        self._last: float | None = None

    def generate(self, request: LLMRequest) -> LLMResponse:
        with self._lock:
            if self._last is not None:
                wait = self._interval - (self._clock() - self._last)
                if wait > 0:
                    self._sleep(wait)
            self._last = self._clock()
        return self._inner.generate(request)


class RetryingLLMClient:
    """Retries short per-minute quota errors and brief provider overloads (5xx);
    never retries the daily quota."""

    OVERLOAD_BACKOFF_S = 5.0

    def __init__(
        self,
        inner: LLMClient,
        max_retries: int = 2,
        max_wait_s: float = 30,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._inner, self._max_retries, self._max_wait, self._sleep = (
            inner,
            max_retries,
            max_wait_s,
            sleep,
        )

    def generate(self, request: LLMRequest) -> LLMResponse:
        for attempt in range(self._max_retries + 1):
            try:
                return self._inner.generate(request)
            except LLMQuotaExceeded as err:
                retryable = err.scope == "minute" and err.retry_after_s <= self._max_wait
                if not retryable or attempt == self._max_retries:
                    raise
                logger.warning("Per-minute quota hit; retrying in %.0fs", err.retry_after_s)
                self._sleep(err.retry_after_s + 0.5)
            except LLMOverloaded:
                if attempt == self._max_retries:
                    raise
                wait = self.OVERLOAD_BACKOFF_S * (attempt + 1)
                logger.warning("LLM provider overloaded; retrying in %.0fs", wait)
                self._sleep(wait)
        raise AssertionError("unreachable")  # pragma: no cover


class ConcurrencyLimitedLLMClient:
    """At most `limit` calls in flight; waiting too long becomes a 503 instead of a pile-up."""

    def __init__(self, inner: LLMClient, limit: int = 1, wait_s: float = 30) -> None:
        self._inner, self._semaphore, self._wait = inner, threading.BoundedSemaphore(limit), wait_s

    def generate(self, request: LLMRequest) -> LLMResponse:
        if not self._semaphore.acquire(timeout=self._wait):
            raise LLMUnavailable("Too many LLM calls in progress.", retry_after_s=15)
        try:
            return self._inner.generate(request)
        finally:
            self._semaphore.release()


class CircuitBreakerLLMClient:
    """After the daily quota is hit, fail fast (no call) until the reported retry time."""

    DEFAULT_OPEN_S = 3600.0

    def __init__(self, inner: LLMClient, clock: Callable[[], float] = time.monotonic) -> None:
        self._inner, self._clock = inner, clock
        self._open_until = 0.0

    def ensure_closed(self) -> None:
        """Raise LLMQuotaExceeded while open — lets the API refuse new jobs up front."""
        remaining = self._open_until - self._clock()
        if remaining > 0:
            raise LLMQuotaExceeded("day", remaining)

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.ensure_closed()
        try:
            return self._inner.generate(request)
        except LLMQuotaExceeded as err:
            if err.scope == "day":
                self._open_until = self._clock() + (err.retry_after_s or self.DEFAULT_OPEN_S)
            raise
