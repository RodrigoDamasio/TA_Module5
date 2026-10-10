"""Cost and quota monitoring (course §2.3, from Lab 4): real calls today vs the daily limit,
cache hit rate, tokens, a paid-tier cost equivalent, run counts and latency."""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.domain.errors import LLMQuotaExceeded
from app.domain.ports import LLMClient, LLMRequest, LLMResponse, RunRepository, TokenUsage

PACIFIC = ZoneInfo("America/Los_Angeles")  # Gemini's daily quotas reset at midnight PT


def seconds_until_midnight_pacific(now: datetime | None = None) -> float:
    now = now or datetime.now(PACIFIC)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (tomorrow - now).total_seconds()


class UsageMeter:
    """In-memory counters (reset on restart; the circuit breaker is the real quota guard)."""

    def __init__(self, clock: Callable[[], datetime] = lambda: datetime.now(PACIFIC)) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._day = ""
        self.real = self.cached = self.input_tokens = self.output_tokens = 0

    def record(self, response: LLMResponse) -> None:
        with self._lock:
            self._roll()
            if response.cached:
                self.cached += 1
            else:
                self.real += 1
                self.input_tokens += response.usage.input
                self.output_tokens += response.usage.output + response.usage.thinking

    def _roll(self) -> None:
        day = self._clock().date().isoformat()
        if day != self._day:
            self._day = day
            self.real = self.cached = self.input_tokens = self.output_tokens = 0

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            self._roll()
            return {
                "real": self.real,
                "cached": self.cached,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
            }


class MeteredLLMClient:
    """Outermost LLM wrapper: sees cache hits and real calls alike."""

    def __init__(self, inner: LLMClient, meter: UsageMeter) -> None:
        self._inner, self._meter = inner, meter

    def generate(self, request: LLMRequest) -> LLMResponse:
        response = self._inner.generate(request)
        self._meter.record(response)
        return response


class DailyCapLLMClient:
    """Below the cache: stops at our own daily limit, before Google's quota does."""

    def __init__(self, inner: LLMClient, meter: UsageMeter, limit: int) -> None:
        self._inner, self._meter, self._limit = inner, meter, limit

    def exhausted(self) -> bool:
        return self._meter.snapshot()["real"] >= self._limit

    def ensure_available(self) -> None:
        if self.exhausted():
            raise LLMQuotaExceeded("day", seconds_until_midnight_pacific())

    def generate(self, request: LLMRequest) -> LLMResponse:
        self.ensure_available()
        return self._inner.generate(request)


@dataclass(frozen=True)
class Pricing:
    daily_request_limit: int = 1000
    input_per_million: float = 0.10
    output_per_million: float = 0.40

    def cost(self, usage: TokenUsage) -> float:
        return round(
            (
                usage.input * self.input_per_million
                + (usage.output + usage.thinking) * self.output_per_million
            )
            / 1_000_000,
            6,
        )


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    k = (len(ordered) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


class StatsService:
    def __init__(
        self,
        runs: RunRepository,
        meter: UsageMeter,
        pricing: Pricing,
        health: Callable[[], dict[str, Any]],
    ) -> None:
        self._runs, self._meter, self._pricing, self._health = runs, meter, pricing, health

    def stats(self) -> dict[str, Any]:
        usage = self._meter.snapshot()
        calls = usage["real"] + usage["cached"]
        p = self._pricing
        durations = self._runs.recent_durations_ms(100)
        p50, p95 = percentile(durations, 50), percentile(durations, 95)
        return {
            "runs": self._runs.status_counts(),
            "run_duration_ms": {
                "p50": round(p50) if p50 is not None else None,
                "p95": round(p95) if p95 is not None else None,
                "window": len(durations),
            },
            "llm": {
                "calls_today": usage["real"],
                "cached_today": usage["cached"],
                "cache_hit_rate": round(usage["cached"] / calls, 3) if calls else None,
                "daily_limit": p.daily_request_limit,
                "left_today": max(0, p.daily_request_limit - usage["real"]),
                "input_tokens": usage["input_tokens"],
                "output_tokens": usage["output_tokens"],
                "paid_equivalent_usd": p.cost(
                    TokenUsage(usage["input_tokens"], usage["output_tokens"])
                ),
                "price_per_million": {
                    "input": p.input_per_million,
                    "output": p.output_per_million,
                },
            },
            "service": self._health(),
        }
