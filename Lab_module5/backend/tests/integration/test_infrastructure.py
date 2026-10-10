"""Q1–Q3 and the adapters: SQLite stores, caching, the Gemini adapter (recorded responses),
the quota decorators, runners, samples (0 calls)."""

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fakes import FakeLLM
from google.genai import errors, types

from app.application.memory import BM25Memory, memory_from_run, summarize
from app.application.service_level import ServiceLevel
from app.application.stats import DailyCapLLMClient, Pricing, UsageMeter, percentile
from app.domain.errors import (
    LLMOverloaded,
    LLMQuotaExceeded,
    LLMUnavailable,
    QueueFull,
    RunNotFound,
    SampleNotFound,
)
from app.domain.ports import (
    AssistantMessage,
    LLMRequest,
    LLMResponse,
    Memory,
    TokenUsage,
    ToolCall,
    ToolResult,
    ToolResultsMessage,
    UserMessage,
)
from app.domain.run import ResearchRun, RunStatus
from app.domain.schemas import ReviewLLM
from app.infrastructure.caching_llm import CachingLLMClient, request_key
from app.infrastructure.gemini_client import build_config, quota_error, to_contents, to_response
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
)

REQ = LLMRequest("sys", [UserMessage("hi")])


# Q1
def test_run_repository_saves_state_and_events_atomically(tmp_path):
    repo = SqliteRunRepository(str(tmp_path / "r.db"))
    run = ResearchRun.create("A research task", 5, False, False)
    repo.create(run)
    run.start()
    run.propose_final("Answer", forced=False, degraded=False)
    repo.save(run)
    assert run.events == []  # popped and persisted
    events = repo.events_since(run.id, 0)
    assert [e.type for e in events] == ["run_started", "completed"]
    assert [e.type for e in repo.events_since(run.id, events[0].id)] == ["completed"]
    assert repo.get(run.id).final_output == "Answer"
    assert repo.status_counts() == {"completed": 1}
    assert len(repo.recent_durations_ms(10)) == 1
    assert [r.id for r in repo.runs_in({RunStatus.COMPLETED})] == [run.id]
    with pytest.raises(RunNotFound):
        repo.get("run_missing")
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    assert repo.delete_older_than(future) == 1 and repo.events_since(run.id, 0) == []


def test_memory_repository_and_bm25_recall(tmp_path):
    repo = SqliteMemoryRepository(str(tmp_path / "m.db"))
    old = Memory(
        "run_a", "What is SQLite?", "SQLite is embedded.", ["SQLite"], "2026-01-01T00:00:00"
    )
    new = Memory("run_b", "Explain PostgreSQL", "A server database.", ["PostgreSQL"], "2026-10-01")
    for m in (old, new):
        repo.record(m)
    assert [m.run_id for m in repo.recent(10)] == ["run_b", "run_a"]
    memory = BM25Memory(repo)
    assert [m.run_id for m in memory.recall("sqlite embedded", 3, "x")] == ["run_a"]
    assert memory.recall("sqlite", 3, "what is  SQLITE?") == []  # same task excluded
    assert memory.recall("sqlite", 0, "x") == []
    assert repo.delete_older_than("2026-06-01") == 1

    run = ResearchRun.create("Task", 5, False, True)
    run.final_output = "## Title\n\n**Bold** text [1] and a [link](https://x).\n\n### Sources\n1. A"
    assert memory_from_run(run).summary == "Title Bold text and a link."
    assert summarize("word " * 200, 20).endswith("…")


def test_settings_secret_is_generated_once(tmp_path):
    db = str(tmp_path / "s.db")
    first = SqliteSettings(db).prompt_secret()
    assert len(first) == 64 and SqliteSettings(db).prompt_secret() == first
    assert SqliteSettings(db).prompt_secret("configured") == b"configured"


# Q2
def test_identical_request_is_served_from_cache(tmp_path):
    llm = FakeLLM()
    cache = CachingLLMClient(llm, SqliteResponseCache(str(tmp_path / "c.db")), "m1")
    first, second = cache.generate(REQ), cache.generate(REQ)
    assert llm.calls() == 1 and not first.cached and second.cached
    assert second.text == first.text
    routed = LLMRequest("sys", [UserMessage("hi")], model="other-model")
    assert request_key("m1", routed) != request_key("m1", REQ)
    assert request_key("m1", REQ) != request_key(
        "m1", LLMRequest("sys", [UserMessage("hi")], response_schema=ReviewLLM)
    )

    class Truncated:
        def generate(self, request):
            return LLMResponse("{", [], None, TokenUsage(), "max_tokens")

    truncated = CachingLLMClient(Truncated(), SqliteResponseCache(str(tmp_path / "t.db")), "m")
    truncated.generate(REQ)
    assert not truncated.generate(REQ).cached  # never cache a cut-off answer
    store = SqliteResponseCache(str(tmp_path / "c.db"))
    assert len(store.export()) == 1 and store.seed({"k": {"x": 1}}) == 1


# Q3
def test_gemini_adapter_mapping_routing_and_recorded_response():
    contents = to_contents(
        [
            UserMessage("task"),
            AssistantMessage(None, [ToolCall("c1", "read", {"p": 1})]),
            ToolResultsMessage([ToolResult("c1", "read", "x")]),
            AssistantMessage("notes", []),
        ]
    )
    assert [c.role for c in contents] == ["user", "model", "user", "model"]
    config = build_config("gemini-3.5-flash-lite", LLMRequest("s", [], response_schema=ReviewLLM))
    assert config.response_mime_type == "application/json"
    cassette = sorted(Path(__file__).parents[1].joinpath("cassettes").glob("*.json"))[0]
    raw = types.GenerateContentResponse.model_validate(json.loads(cassette.read_text()))
    mapped = to_response(raw)
    assert mapped.usage.input > 0


def test_daily_quota_waits_for_the_real_reset():
    body = {
        "error": {
            "code": 429,
            "details": [
                {
                    "@type": "type.googleapis.com/google.rpc.QuotaFailure",
                    "violations": [
                        {"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}
                    ],
                },
                {"@type": "type.googleapis.com/google.rpc.RetryInfo", "retryDelay": "12s"},
            ],
        }
    }
    noon = datetime(2026, 10, 5, 12, 0, tzinfo=ZoneInfo("America/Los_Angeles"))
    err = quota_error(errors.ClientError(429, body), now=noon)
    assert (err.scope, err.retry_after_s) == ("day", 43200)


class Clock:
    def __init__(self):
        self.now, self.slept = 1000.0, []

    def __call__(self):
        return self.now

    def sleep(self, s):
        self.slept.append(s)
        self.now += s


def test_quota_decorators_and_gate():
    clock = Clock()
    paced = PacedLLMClient(FakeLLM(), 6, clock, clock.sleep)
    paced.generate(REQ)
    paced.generate(REQ)
    assert clock.slept == [6]
    inner = FakeLLM(fail={"any": LLMOverloaded("503")})
    with pytest.raises(LLMOverloaded):
        RetryingLLMClient(inner, sleep=clock.sleep).generate(REQ)
    assert inner.calls() == 3
    minute = FakeLLM(fail={"any": LLMQuotaExceeded("minute", 5)})
    with pytest.raises(LLMQuotaExceeded):
        RetryingLLMClient(minute, sleep=clock.sleep).generate(REQ)
    assert minute.calls() == 3
    breaker_inner = FakeLLM(fail={"any": LLMQuotaExceeded("day", 300)})
    breaker = CircuitBreakerLLMClient(breaker_inner, clock)
    for _ in range(2):
        with pytest.raises(LLMQuotaExceeded):
            breaker.generate(REQ)
    assert breaker_inner.calls() == 1

    gate = threading.Event()

    class Slow:
        def generate(self, request):
            gate.wait(2)
            return FakeLLM().generate(request)

    limited = ConcurrencyLimitedLLMClient(Slow(), limit=1, wait_s=0.05)
    worker = threading.Thread(target=limited.generate, args=(REQ,))
    worker.start()
    with pytest.raises(LLMUnavailable):
        limited.generate(REQ)
    gate.set()
    worker.join()


def test_usage_meter_daily_cap_pricing_and_service_level():
    day = {"d": datetime(2026, 10, 5, 23, 0, tzinfo=ZoneInfo("America/Los_Angeles"))}
    meter = UsageMeter(lambda: day["d"])
    meter.record(LLMResponse("x", [], None, TokenUsage(10, 5, 1), "stop"))
    meter.record(LLMResponse("x", [], None, TokenUsage(10, 5), "stop", cached=True))
    assert meter.snapshot() == {"real": 1, "cached": 1, "input_tokens": 10, "output_tokens": 6}
    capped = DailyCapLLMClient(FakeLLM(), meter, limit=1)
    with pytest.raises(LLMQuotaExceeded):
        capped.generate(REQ)
    day["d"] = datetime(2026, 10, 6, 0, 1, tzinfo=ZoneInfo("America/Los_Angeles"))
    assert meter.snapshot()["real"] == 0 and capped.generate(REQ).text

    assert Pricing(1000, 0.10, 0.40).cost(TokenUsage(1_000_000, 500_000, 500_000)) == 0.5
    assert percentile([], 50) is None and percentile([1, 3], 50) == 2 and percentile([5], 95) == 5

    state = {"blocked": None, "wiki": True}
    level = ServiceLevel(lambda: state["blocked"], lambda: state["wiki"])
    assert level.current()["level"] == "full"
    state["wiki"] = False
    assert level.current()["level"] == "reduced"
    state["blocked"] = 120.4
    assert level.current() == {
        "level": "minimal",
        "retry_after_s": 120,
        "reason": "The daily LLM quota is used up.",
    }


def test_runners():
    done = []
    inline = InlineRunner(done.append)
    inline.start()
    inline.submit("a")
    assert done == ["a"] and inline.has_capacity()
    inline.stop()

    seen, swept = [], threading.Event()

    def run(job_id):
        if job_id == "boom":
            raise RuntimeError("crash")
        seen.append(job_id)

    runner = ThreadRunner(run, max_queued=5, sweep=swept.set, sweep_every_s=0.01)
    runner.start()
    for job_id in ("boom", "b", "c"):
        runner.submit(job_id)
    deadline = time.monotonic() + 5
    while seen != ["b", "c"] and time.monotonic() < deadline:
        time.sleep(0.01)
    assert seen == ["b", "c"] and swept.wait(2)  # a crash never kills the worker
    runner.stop()
    full = ThreadRunner(run, max_queued=1)
    full.submit("x")
    assert not full.has_capacity()
    with pytest.raises(QueueFull):
        full.submit("y")
    full.stop()


def test_sample_store(tmp_path):
    store = SampleStore(tmp_path)
    assert store.catalog() == []
    (tmp_path / "index.json").write_text(json.dumps([{"id": "rag", "title": "RAG", "task": "t"}]))
    (tmp_path / "rag.json").write_text(json.dumps({"run_id": "run_1", "sample": False}))
    assert store.get("rag") == {"run_id": "run_1", "sample": True}
    for bad in ("missing", "../rag", "RAG"):
        with pytest.raises(SampleNotFound):
            store.get(bad)


def test_gemini_client_routes_models_and_maps_errors(monkeypatch):
    import httpx

    from app.domain.errors import LLMRequestRejected, LLMTimeout
    from app.infrastructure.gemini_client import GeminiClient

    raw = types.GenerateContentResponse.model_validate(
        json.loads(
            sorted(Path(__file__).parents[1].joinpath("cassettes").glob("*.json"))[0].read_text()
        )
    )
    seen, recorded = [], []
    client = GeminiClient("fake-key", "default-model", 10, on_raw=recorded.append)

    def generate_content(model, contents, config):
        seen.append(model)
        if model == "boom-429":
            raise errors.ClientError(429, {"error": {"code": 429, "details": []}})
        if model == "boom-400":
            raise errors.ClientError(400, {"error": {"code": 400}})
        if model == "boom-503":
            raise errors.ServerError(503, {"error": {"code": 503}})
        if model == "boom-timeout":
            raise httpx.ReadTimeout("slow")
        if model == "boom-network":
            raise httpx.ConnectError("down")
        return raw

    monkeypatch.setattr(client._client.models, "generate_content", generate_content)
    client.generate(LLMRequest("s", [UserMessage("x")]))
    client.generate(LLMRequest("s", [UserMessage("x")], model="routed-model"))
    assert seen == ["default-model", "routed-model"] and len(recorded) == 2
    expected = {
        "boom-429": LLMQuotaExceeded,
        "boom-400": LLMRequestRejected,
        "boom-503": LLMOverloaded,
        "boom-timeout": LLMTimeout,
        "boom-network": LLMUnavailable,
    }
    for model, error in expected.items():
        with pytest.raises(error):
            client.generate(LLMRequest("s", [UserMessage("x")], model=model))


def test_production_wiring_builds_without_calling_anything(tmp_path):
    import dataclasses

    from conftest import make_settings

    from app.api.dependencies import build_container
    from app.infrastructure.wikipedia import WikipediaSource

    settings = make_settings(
        tmp_path,
        llm_mode="gemini",
        wiki_mode="live",
        google_api_key="fake-key",
        model_supervisor="gemini-3.8-flash",
        runner_mode="thread",
    )
    container = build_container(settings)
    assert isinstance(container.knowledge, WikipediaSource)
    assert container.health()["models"] == {
        "supervisor": "gemini-3.8-flash",
        "workers": "gemini-3.5-flash-lite",
    }
    assert container.health()["service_level"] == "full"
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY"):
        build_container(dataclasses.replace(settings, google_api_key=None))
