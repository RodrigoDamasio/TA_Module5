"""Wiring: the only place that chooses concrete implementations. One Container per app
(tests build their own with temp storage, a fake LLM and fake Wikipedia).

LLM chain for one run, outermost first:
    Metered → RunCounter → Caching → Budgeted(run) → DailyCap → CircuitBreaker → Retrying
    → ConcurrencyLimited(1) → Paced → Gemini
Cache hits never reach the budget or the daily cap: re-runs cost 0 and never stop early."""

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import Request

from app.application.budget import BudgetedLLMClient, CallBudget, RunCounter
from app.application.memory import BM25Memory
from app.application.prompts import PromptLibrary
from app.application.runs import RunLimits, RunService
from app.application.service_level import ServiceLevel
from app.application.stats import (
    DailyCapLLMClient,
    MeteredLLMClient,
    Pricing,
    StatsService,
    UsageMeter,
)
from app.application.supervisor import LoopSettings, Supervisor
from app.application.workers.base import WorkerRegistry
from app.application.workers.fact_checker import FactChecker
from app.application.workers.researcher import Researcher
from app.application.workers.reviewer import Reviewer
from app.application.workers.writer import Writer
from app.config import Settings
from app.domain.errors import LLMQuotaExceeded
from app.domain.ports import KnowledgeSource, LLMClient
from app.infrastructure.caching_llm import CachingLLMClient
from app.infrastructure.demo_llm import DemoLLMClient
from app.infrastructure.fake_wikipedia import FakeWikipedia
from app.infrastructure.gemini_client import GeminiClient
from app.infrastructure.llm_decorators import (
    CircuitBreakerLLMClient,
    ConcurrencyLimitedLLMClient,
    PacedLLMClient,
    RetryingLLMClient,
)
from app.infrastructure.runner import InlineRunner, ThreadRunner
from app.infrastructure.samples import SampleStore
from app.infrastructure.sqlite_store import (
    SqliteMemoryRepository,
    SqliteResponseCache,
    SqliteRunRepository,
    SqliteSettings,
    SqliteWikiCache,
)
from app.infrastructure.wikipedia import WikipediaSource

from .guards import RateLimiter

logger = logging.getLogger(__name__)


@dataclass
class Container:
    settings: Settings
    service: RunService
    supervisor: Supervisor
    registry: WorkerRegistry
    runner: InlineRunner | ThreadRunner
    limiter: RateLimiter
    samples: SampleStore
    stats: StatsService
    prompts: PromptLibrary
    pricing: Pricing
    level: ServiceLevel
    meter: UsageMeter
    knowledge: KnowledgeSource
    response_cache: SqliteResponseCache

    def start(self) -> None:
        interrupted = self.service.recover()
        logger.info(
            "startup interrupted_runs=%d llm_mode=%s wiki=%s",
            interrupted,
            self.settings.llm_mode,
            self.settings.wiki_mode,
        )
        self.runner.start()

    def stop(self) -> None:
        self.runner.stop()

    def health(self) -> dict[str, Any]:
        s = self.settings
        level = self.level.current()
        return {
            "status": "ok",
            "service_level": level["level"],
            "service_reason": level["reason"],
            "retry_after_s": level["retry_after_s"],
            "llm_mode": s.llm_mode,
            "wikipedia": s.wiki_mode,
            "models": {
                "supervisor": s.model_label(s.model_supervisor),
                "workers": s.model_label(s.model_workers),
            },
            "prompt_version": self.prompts.version,
            "usage_today": {
                "calls": self.meter.snapshot()["real"],
                "limit": s.llm_daily_request_limit,
            },
            "limits": {
                "task_min_chars": s.task_min_chars,
                "task_max_chars": s.task_max_chars,
                "default_max_iterations": s.default_max_iterations,
                "max_iterations_limit": s.max_iterations_limit,
                "max_parallel_delegations": s.max_parallel_delegations,
                "approval_timeout_min": s.approval_timeout_min,
                "feedback_max_chars": 1000,
            },
        }


def gemini_stack(settings: Settings) -> tuple[LLMClient, CircuitBreakerLLMClient]:
    """Uncached chain, outermost first: CircuitBreaker → Retrying → Gate → Paced → Gemini."""
    if not settings.google_api_key:
        raise RuntimeError("GOOGLE_API_KEY is not set (or use LLM_MODE=fake).")
    gemini = GeminiClient(settings.google_api_key, settings.gemini_model, settings.llm_timeout_s)
    gated = ConcurrencyLimitedLLMClient(
        PacedLLMClient(gemini, settings.llm_min_interval_s),
        limit=1,  # one free-tier quota: calls stay serialized (also for parallel workers)
        wait_s=settings.llm_timeout_s * 3,
    )
    breaker = CircuitBreakerLLMClient(RetryingLLMClient(gated))
    return breaker, breaker


def build_container(
    settings: Settings, llm: LLMClient | None = None, knowledge: KnowledgeSource | None = None
) -> Container:
    db = settings.database_path
    runs = SqliteRunRepository(db)
    memories = SqliteMemoryRepository(db)
    response_cache = SqliteResponseCache(db)
    secret = SqliteSettings(db).prompt_secret(settings.prompt_secret)
    prompts = PromptLibrary()
    meter = UsageMeter()

    breaker: CircuitBreakerLLMClient | None = None
    if llm is not None:
        base = llm
    elif settings.fake:
        base = DemoLLMClient(settings.fake_llm_delay_s)
    else:
        base, breaker = gemini_stack(settings)
    capped = DailyCapLLMClient(base, meter, settings.llm_daily_request_limit)
    default_model = settings.model_label(settings.gemini_model)

    def llm_for(budget: CallBudget) -> LLMClient:
        cached = CachingLLMClient(BudgetedLLMClient(capped, budget), response_cache, default_model)
        return MeteredLLMClient(RunCounter(cached, budget), meter)

    if knowledge is None:
        if settings.wiki_mode == "fake":
            knowledge = FakeWikipedia()
        else:
            knowledge = WikipediaSource(
                SqliteWikiCache(db),
                settings.wiki_lang,
                settings.wiki_timeout_s,
                settings.wiki_cache_ttl_h * 3600,
            )
    registry = WorkerRegistry(
        [
            Researcher(
                prompts, knowledge, settings.wiki_max_pages, settings.wiki_max_chars_per_page
            ),
            Writer(prompts),
            Reviewer(prompts),
            FactChecker(prompts),
        ]
    )
    supervisor = Supervisor(
        runs,
        llm_for,
        registry,
        prompts,
        secret,
        LoopSettings(
            supervisor_model=settings.model_label(settings.model_supervisor),
            worker_model=settings.model_label(settings.model_workers),
            max_parallel=settings.max_parallel_delegations,
            task_max_chars=settings.delegation_task_max_chars,
            revision_iterations=settings.revision_iterations,
            approval_timeout_min=settings.approval_timeout_min,
            supervisor_context_tokens=settings.supervisor_context_tokens,
            worker_context_chars=int(settings.worker_context_tokens * 3.5),
            memory_limit=settings.memory_recall_limit,
        ),
        memory=BM25Memory(memories) if settings.memory_enabled else None,
    )

    def ensure_llm_available() -> None:
        if breaker is not None:
            breaker.ensure_closed()
        capped.ensure_available()

    def llm_blocked() -> float | None:
        try:
            ensure_llm_available()
        except LLMQuotaExceeded as err:
            return err.retry_after_s
        return None

    sweep_target: dict[str, RunService] = {}
    runner: InlineRunner | ThreadRunner = (
        InlineRunner(supervisor.run)
        if settings.runner_mode == "inline"
        else ThreadRunner(
            supervisor.run,
            settings.max_queued_jobs,
            sweep=lambda: sweep_target["service"].sweep(),
            sweep_every_s=settings.sweep_every_s,
        )
    )
    service = RunService(
        runs,
        runner,
        supervisor,
        RunLimits(
            settings.default_max_iterations,
            settings.max_iterations_limit,
            settings.task_min_chars,
            settings.task_max_chars,
            settings.revision_iterations,
            settings.run_retention_days,
            settings.memory_enabled,
        ),
        ensure_llm_available,
        memories,
    )
    sweep_target["service"] = service
    pricing = Pricing(
        settings.llm_daily_request_limit, settings.price_input_per_m, settings.price_output_per_m
    )
    level = ServiceLevel(llm_blocked, knowledge.available)
    container = Container(
        settings=settings,
        service=service,
        supervisor=supervisor,
        registry=registry,
        runner=runner,
        limiter=RateLimiter(settings.rate_limit_runs_per_minute, settings.rate_limit_runs_per_day),
        samples=SampleStore(),
        stats=None,  # type: ignore[arg-type] — set below (needs the container's health view)
        prompts=prompts,
        pricing=pricing,
        level=level,
        meter=meter,
        knowledge=knowledge,
        response_cache=response_cache,
    )
    container.stats = StatsService(runs, meter, pricing, container.health)
    return container


def get_container(request: Request) -> Container:
    return request.app.state.container
