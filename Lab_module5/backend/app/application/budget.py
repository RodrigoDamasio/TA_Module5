"""Per-run LLM call control (the Lab 3 loop guard; from Lab 4).

Wiring for one run, outermost first:
    RunCounter → Caching → Budgeted(max_calls) → CircuitBreaker → Retrying → Gate → Paced → Gemini
Cache hits never reach the budget, so a re-run of a cached evaluation costs 0 and never
stops early; real calls stop at `max_calls` with BudgetExceeded."""

import threading

from app.domain.errors import BudgetExceeded
from app.domain.ports import LLMClient, LLMRequest, LLMResponse


class CallBudget:
    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.real = 0
        self.cached = 0
        self._lock = threading.Lock()

    def take(self) -> None:
        with self._lock:
            if self.real >= self.limit:
                raise BudgetExceeded(self.limit)
            self.real += 1

    def count_cached(self) -> None:
        with self._lock:
            self.cached += 1

    def remaining(self) -> int:
        with self._lock:
            return self.limit - self.real


class BudgetedLLMClient:
    """Sits below the cache: every request reaching it is a real call."""

    def __init__(self, inner: LLMClient, budget: CallBudget) -> None:
        self._inner, self._budget = inner, budget

    def generate(self, request: LLMRequest) -> LLMResponse:
        self._budget.take()
        return self._inner.generate(request)


class RunCounter:
    """Sits above the cache: counts the hits (real calls are counted by the budget)."""

    def __init__(self, inner: LLMClient, budget: CallBudget) -> None:
        self._inner, self._budget = inner, budget

    def generate(self, request: LLMRequest) -> LLMResponse:
        response = self._inner.generate(request)
        if response.cached:
            self._budget.count_cached()
        return response
