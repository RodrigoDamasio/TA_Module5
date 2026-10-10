"""Traces (course §6.1): spans with timings and attributes — never question text or code."""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Span:
    name: str
    ms: float
    ok: bool = True
    attrs: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "ms": round(self.ms, 1), "ok": self.ok, **self.attrs}


@dataclass
class Trace:
    request_id: str
    kind: str  # query | search | index | evaluate
    total_ms: float
    spans: list[Span]
    attrs: dict[str, Any] = field(default_factory=dict)  # counts, scores, cache flags

    def span(self, name: str) -> Span | None:
        return next((s for s in self.spans if s.name == name), None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "request_id": self.request_id,
            "total_ms": round(self.total_ms, 1),
            "spans": [s.as_dict() for s in self.spans],
            **self.attrs,
        }


@dataclass
class PromptDebug:
    system: str
    user: str
    prompt_version: str
    est_tokens: int
    chunks_sent: int
    chunks_dropped: int


@dataclass
class LLMAttempt:
    raw_output: str | None
    errors: list[str] = field(default_factory=list)
    repair_message: str | None = None


@dataclass
class PipelineDebug:
    """Every transformation of one question (§10.1). Returned only with ?debug=true;
    never logged, never stored."""

    question: str
    query_rewrite: dict | None = None  # reserved: there is no rewrite step
    retrieval: Any = None  # RetrievalDebug
    prompt: PromptDebug | None = None
    attempts: list[LLMAttempt] = field(default_factory=list)
    llm_cached: bool | None = None
    input_tokens: int = 0
    output_tokens: int = 0
