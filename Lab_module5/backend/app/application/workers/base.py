"""The Worker interface (the lab's "accept task + context, return result"), the registry,
and helpers shared by the workers."""

import json
import re
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

from app.application.security import DataFence, OutputValidator
from app.domain.errors import LLMBadResponse
from app.domain.ports import LLMClient, LLMRequest, LLMResponse, SourceDraft, TokenUsage
from app.domain.transcript import CallMeta, Source, WorkerResult

CITATION = re.compile(r"\[(\d{1,3})\]")
_CITATION_LIST = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})+)\]")


def split_citations(text: str) -> str:
    """'[1, 2]' → '[1][2]' (models often group citations)."""
    return _CITATION_LIST.sub(
        lambda m: "".join(f"[{n.strip()}]" for n in m.group(1).split(",")), text
    )


@dataclass(frozen=True)
class WorkerContext:
    """Built by the app, not the model: the user task, the latest result of each worker
    this one needs, the run's sources, and the tools to fence untrusted text."""

    run_id: str
    user_task: str
    results: dict[str, WorkerResult]
    sources: list[Source]
    fence: DataFence
    register_sources: Callable[[list[SourceDraft]], list[Source]]
    model: str | None
    canary: str
    context_chars: int  # character budget for the worker's variable inputs


@dataclass
class WorkerOutput:
    result: WorkerResult
    notices: list[tuple[str, str]] = field(default_factory=list)  # (text, flag)


class Worker(Protocol):
    name: str  # registry key
    title: str
    description: str  # one line, shown to the Supervisor and in GET /agents
    needs: frozenset[str]  # whose latest results go into the context

    def run(self, task: str, ctx: WorkerContext, llm: LLMClient) -> WorkerOutput: ...


class WorkerRegistry:
    def __init__(self, workers: list[Worker]) -> None:
        self._workers = {w.name: w for w in workers}

    @property
    def names(self) -> frozenset[str]:
        return frozenset(self._workers)

    def get(self, name: str) -> Worker:
        return self._workers[name]

    def all(self) -> list[Worker]:
        return list(self._workers.values())

    def describe(self) -> str:
        return "\n".join(f"- {w.name}: {w.description}" for w in self._workers.values())


class StepCounter:
    """Wraps the run's LLM client for ONE step: counts real vs cached calls and tokens,
    and checks every answer for the canary (a leak raises CanaryLeak)."""

    def __init__(self, inner: LLMClient, output: OutputValidator) -> None:
        self._inner, self._output = inner, output
        self._lock = threading.Lock()
        self.real = self.cached = 0
        self.usage = TokenUsage()
        self._start = time.perf_counter()

    def generate(self, request: LLMRequest) -> LLMResponse:
        response = self._inner.generate(request)
        self._output.check_canary(response.text)
        if response.parsed is not None:
            self._output.check_canary(json.dumps(response.parsed))
        with self._lock:
            if response.cached:
                self.cached += 1
            else:
                self.real += 1
            self.usage = self.usage + response.usage
        return response

    def meta(self, model: str | None) -> CallMeta:
        ms = int((time.perf_counter() - self._start) * 1000)
        return CallMeta(model, self.usage, self.real, self.cached, ms)


def text_of(response: LLMResponse) -> str:
    text = (response.text or "").strip()
    if not text:
        raise LLMBadResponse("The model returned an empty answer.")
    return text


def truncation(response: LLMResponse, worker: str) -> list[tuple[str, str]]:
    """Thinking tokens count against the output limit: say so when an answer was cut off."""
    if response.finish_reason != "max_tokens":
        return []
    return [(f"The {worker}'s answer was cut off at the output limit.", "truncated")]


def clean_citations(text: str, valid: set[int]) -> tuple[str, tuple[int, ...], list[int]]:
    """Drop [n] markers that point to no known source. Returns (text, cited, unknown)."""
    cited: list[int] = []
    unknown: list[int] = []

    def keep(m: re.Match[str]) -> str:
        n = int(m.group(1))
        if n in valid:
            if n not in cited:
                cited.append(n)
            return m.group(0)
        unknown.append(n)
        return ""

    out = CITATION.sub(keep, split_citations(text))
    return out, tuple(sorted(cited)), unknown


def trim(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return f"{text[:max_chars].rstrip()}\n[… {len(text) - max_chars} more characters]"


def or_none(value: str | None) -> str:
    return value if value else "(none)"
