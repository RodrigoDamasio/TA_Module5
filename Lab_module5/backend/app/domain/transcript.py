"""The conversation history of a run: Supervisor decisions, worker results, human feedback
and system notices. It is also the run's audit trail (who decided what, with which model)."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .ports import TokenUsage


@dataclass(frozen=True)
class Delegation:
    worker: str  # registry key: researcher | writer | reviewer | fact_checker
    task: str


@dataclass(frozen=True)
class Decision:
    delegations: tuple[Delegation, ...]  # empty when the action is FINAL
    final: str | None  # Markdown answer when the action is FINAL
    reason: str | None
    repaired: bool = False  # needed the repair call
    forced: bool = False  # came from the forced-completion call
    preamble_chars: int = 0  # text before the first key (prompt-drift signal)

    @property
    def action(self) -> str:
        return "final" if self.final is not None else "delegate"


@dataclass(frozen=True)
class Source:
    n: int  # citation number, unique within the run
    title: str
    url: str
    extract: str  # the text given to the model; kept for the Fact-Checker, never in the API


@dataclass(frozen=True)
class WorkerResult:
    worker: str
    content: str  # Markdown (Researcher, Writer) or a rendered summary (Reviewer, Fact-Checker)
    data: dict[str, Any] = field(default_factory=dict)  # structured output or {}
    source_ns: tuple[int, ...] = ()  # sources this result cites
    unsourced: bool = False  # the Researcher fell back to model knowledge
    failed: bool = False  # the worker could not produce a valid result


@dataclass(frozen=True)
class CallMeta:
    """What one step cost: the model, tokens, and real vs cached calls."""

    model: str | None = None
    usage: TokenUsage = TokenUsage()
    real_calls: int = 0
    cached_calls: int = 0
    duration_ms: int = 0

    @property
    def cached(self) -> bool:
        return self.real_calls == 0 and self.cached_calls > 0

    def __add__(self, other: "CallMeta") -> "CallMeta":
        return CallMeta(
            self.model or other.model,
            self.usage + other.usage,
            self.real_calls + other.real_calls,
            self.cached_calls + other.cached_calls,
            self.duration_ms + other.duration_ms,
        )


class EntryKind(StrEnum):
    DECISION = "decision"
    WORKER_RESULT = "worker_result"
    FEEDBACK = "feedback"
    NOTICE = "notice"


@dataclass(frozen=True)
class TranscriptEntry:
    seq: int
    iteration: int
    kind: EntryKind
    agent: str  # supervisor | <worker> | human | system
    task: str | None = None  # the TASK given to a worker
    decision: Decision | None = None
    result: WorkerResult | None = None
    text: str | None = None  # feedback or notice text
    flag: str | None = None  # notices: unsourced, forced, repeated, memory, …
    meta: CallMeta = CallMeta()


# ---- (de)serialization: state_json and the public view --------------------------------


def _usage(d: dict[str, int]) -> TokenUsage:
    return TokenUsage(d.get("input", 0), d.get("output", 0), d.get("thinking", 0))


def _usage_dict(u: TokenUsage) -> dict[str, int]:
    return {"input": u.input, "output": u.output, "thinking": u.thinking}


def entry_to_dict(e: TranscriptEntry) -> dict[str, Any]:
    """Public and stored shape (it holds no source extracts)."""
    out: dict[str, Any] = {
        "seq": e.seq,
        "iteration": e.iteration,
        "kind": e.kind.value,
        "agent": e.agent,
        "task": e.task,
        "text": e.text,
        "flag": e.flag,
        "model": e.meta.model,
        "tokens": _usage_dict(e.meta.usage),
        "llm_calls": e.meta.real_calls,
        "cached_calls": e.meta.cached_calls,
        "cached": e.meta.cached,
        "duration_ms": e.meta.duration_ms,
        "decision": None,
        "result": None,
    }
    if e.decision is not None:
        d = e.decision
        out["decision"] = {
            "action": d.action,
            "delegations": [{"worker": x.worker, "task": x.task} for x in d.delegations],
            "final": d.final,
            "reason": d.reason,
            "repaired": d.repaired,
            "forced": d.forced,
            "preamble_chars": d.preamble_chars,
        }
    if e.result is not None:
        r = e.result
        out["result"] = {
            "worker": r.worker,
            "content": r.content,
            "data": r.data,
            "sources": list(r.source_ns),
            "unsourced": r.unsourced,
            "failed": r.failed,
        }
    return out


def entry_from_dict(d: dict[str, Any]) -> TranscriptEntry:
    decision = result = None
    if (dd := d.get("decision")) is not None:
        decision = Decision(
            tuple(Delegation(x["worker"], x["task"]) for x in dd["delegations"]),
            dd["final"],
            dd["reason"],
            dd["repaired"],
            dd["forced"],
            dd.get("preamble_chars", 0),
        )
    if (rd := d.get("result")) is not None:
        result = WorkerResult(
            rd["worker"],
            rd["content"],
            rd["data"],
            tuple(rd["sources"]),
            rd["unsourced"],
            rd["failed"],
        )
    meta = CallMeta(
        d["model"], _usage(d["tokens"]), d["llm_calls"], d["cached_calls"], d["duration_ms"]
    )
    return TranscriptEntry(
        d["seq"],
        d["iteration"],
        EntryKind(d["kind"]),
        d["agent"],
        d["task"],
        decision,
        result,
        d["text"],
        d["flag"],
        meta,
    )
