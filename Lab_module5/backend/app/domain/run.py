"""ResearchRun: one task worked on by the Supervisor and its workers.

Every mutation goes through a method that validates it and appends a RunEvent; the
repository saves the state and its new events in ONE transaction (Lab 3), so the SSE
stream and GET /runs/{id} can never disagree."""

import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from .errors import InvalidTransition
from .ports import Memory, SourceDraft, TokenUsage
from .transcript import (
    CallMeta,
    Decision,
    Delegation,
    EntryKind,
    Source,
    TranscriptEntry,
    WorkerResult,
    entry_from_dict,
    entry_to_dict,
)


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL = frozenset({RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED})

_TRANSITIONS: dict[RunStatus, set[RunStatus]] = {
    RunStatus.QUEUED: {RunStatus.RUNNING, RunStatus.FAILED},
    RunStatus.RUNNING: {RunStatus.AWAITING_APPROVAL, RunStatus.COMPLETED, RunStatus.FAILED},
    # reject with feedback re-queues the run for a revision
    RunStatus.AWAITING_APPROVAL: {RunStatus.COMPLETED, RunStatus.QUEUED, RunStatus.CANCELLED},
}


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


@dataclass
class RunEvent:
    type: str
    data: dict[str, Any]
    id: int | None = None  # assigned by the repository (SSE event id)


@dataclass
class ResearchRun:
    id: str
    task: str
    max_iterations: int
    require_approval: bool
    use_memory: bool
    iteration_limit: int
    status: RunStatus = RunStatus.QUEUED
    iteration: int = 0  # Supervisor decisions made (forced call not counted)
    transcript: list[TranscriptEntry] = field(default_factory=list)
    sources: list[Source] = field(default_factory=list)
    draft: str | None = None  # FINAL waiting for approval
    approval_expires_at: str | None = None
    final_output: str | None = None
    forced: bool = False
    degraded: bool = False
    revisions: int = 0
    flags: list[str] = field(default_factory=list)
    memories: list[dict[str, str]] = field(default_factory=list)  # recalled: run_id, task, summary
    error: str | None = None
    llm_calls: int = 0
    cached_calls: int = 0
    tokens: TokenUsage = TokenUsage()
    models: dict[str, str] = field(default_factory=dict)  # role → model
    prompt_version: str = ""
    created_at: str = field(default_factory=now_iso)
    started_at: str | None = None
    finished_at: str | None = None
    updated_at: str = field(default_factory=now_iso)
    events: list[RunEvent] = field(default_factory=list)  # new, not yet persisted

    @classmethod
    def create(
        cls,
        task: str,
        max_iterations: int,
        require_approval: bool,
        use_memory: bool,
        flags: list[str] | None = None,
    ) -> "ResearchRun":
        return cls(
            id="run_" + secrets.token_hex(6),
            task=task,
            max_iterations=max_iterations,
            require_approval=require_approval,
            use_memory=use_memory,
            iteration_limit=max_iterations,
            flags=list(flags or []),
        )

    # ---- events ----------------------------------------------------------------------

    def _emit(self, type_: str, **data: Any) -> None:
        self.updated_at = now_iso()
        self.events.append(RunEvent(type_, data))

    def pop_events(self) -> list[RunEvent]:
        events, self.events = self.events, []
        return events

    def _move(self, status: RunStatus, action: str) -> None:
        if status not in _TRANSITIONS.get(self.status, set()):
            raise InvalidTransition(self.status.value, action)
        self.status = status
        if status in TERMINAL:
            self.finished_at = now_iso()

    def _flag(self, flag: str) -> None:
        if flag not in self.flags:
            self.flags.append(flag)

    def _append(self, kind: EntryKind, agent: str, **fields: Any) -> TranscriptEntry:
        entry = TranscriptEntry(len(self.transcript) + 1, self.iteration, kind, agent, **fields)
        self.transcript.append(entry)
        meta: CallMeta = entry.meta
        self.llm_calls += meta.real_calls
        self.cached_calls += meta.cached_calls
        self.tokens = self.tokens + meta.usage
        self._emit(kind.value, **entry_to_dict(entry))
        return entry

    # ---- lifecycle -----------------------------------------------------------------------

    @property
    def done(self) -> bool:
        return self.status in TERMINAL

    def start(self) -> None:
        self._move(RunStatus.RUNNING, "start")
        self.started_at = self.started_at or now_iso()
        self._emit("run_started", iteration=self.iteration, iteration_limit=self.iteration_limit)

    def use_memories(self, memories: list[Memory]) -> None:
        self.memories = [
            {"run_id": m.run_id, "task": m.task, "summary": m.summary} for m in memories
        ]
        if memories:
            self.notice(f"Used {len(memories)} memories from earlier tasks.", "memory")

    def agent_started(self, agent: str, task: str | None) -> None:
        """Live hint for the activity feed; not part of the transcript."""
        self._emit("agent_started", agent=agent, iteration=self.iteration, task=task)

    def record_decision(self, decision: Decision, meta: CallMeta, count: bool = True) -> None:
        if count:
            self.iteration += 1
        self._append(EntryKind.DECISION, "supervisor", decision=decision, meta=meta)

    def record_result(self, task: str, result: WorkerResult, meta: CallMeta) -> None:
        if result.unsourced:
            self._flag("unsourced")
        self._append(EntryKind.WORKER_RESULT, result.worker, task=task, result=result, meta=meta)

    def notice(self, text: str, flag: str | None = None, meta: CallMeta | None = None) -> None:
        if flag in ("unsourced", "redacted", "unknown_citation", "possible_injection", "truncated"):
            self._flag(flag)
        self._append(EntryKind.NOTICE, "system", text=text, flag=flag, meta=meta or CallMeta())

    def add_flag(self, flag: str) -> None:
        self._flag(flag)

    def add_sources(self, drafts: list[SourceDraft]) -> list[Source]:
        """Numbers new sources after the existing ones; a known URL keeps its number."""
        by_url = {s.url: s for s in self.sources}
        out = []
        for d in drafts:
            if d.url not in by_url:
                by_url[d.url] = Source(len(self.sources) + 1, d.title, d.url, d.extract)
                self.sources.append(by_url[d.url])
            out.append(by_url[d.url])
        return out

    def propose_final(
        self, text: str, *, forced: bool, degraded: bool, approval_timeout_min: int = 30
    ) -> None:
        self.forced = self.forced or forced
        self.degraded = self.degraded or degraded
        if forced:
            self._flag("forced")
        if degraded:
            self._flag("degraded")
        if self.require_approval:
            self._move(RunStatus.AWAITING_APPROVAL, "wait for approval of")
            self.draft = text
            expires = datetime.now(UTC) + timedelta(minutes=approval_timeout_min)
            self.approval_expires_at = expires.isoformat(timespec="seconds")
            self._emit("awaiting_approval", draft=text, expires_at=self.approval_expires_at)
            return
        self._complete(text)

    def _complete(self, text: str) -> None:
        self._move(RunStatus.COMPLETED, "complete")
        self.final_output, self.draft, self.approval_expires_at = text, None, None
        self._emit("completed", final_output=text, forced=self.forced, degraded=self.degraded)

    def approve(self) -> None:
        if self.status is not RunStatus.AWAITING_APPROVAL:
            raise InvalidTransition(self.status.value, "approve")
        self._complete(self.draft or "")

    def reject(self, feedback: str | None, revision_iterations: int) -> bool:
        """True when the run goes back to work (feedback, first rejection)."""
        if self.status is not RunStatus.AWAITING_APPROVAL:
            raise InvalidTransition(self.status.value, "reject")
        if feedback and self.revisions == 0:
            self.revisions += 1
            self.iteration_limit = self.iteration + revision_iterations
            self._append(EntryKind.FEEDBACK, "human", text=feedback)
            self._move(RunStatus.QUEUED, "revise")
            self.draft, self.approval_expires_at = None, None
            return True
        self.cancel("Rejected by the reviewer.")
        return False

    def cancel(self, reason: str) -> None:
        self._move(RunStatus.CANCELLED, "cancel")
        self.draft, self.approval_expires_at = None, None
        self._emit("cancelled", reason=reason)

    def fail(self, reason: str) -> None:
        self._move(RunStatus.FAILED, "fail")
        self.error = reason
        self._emit("failed", error=reason)

    def approval_expired(self, now: datetime) -> bool:
        return (
            self.status is RunStatus.AWAITING_APPROVAL
            and self.approval_expires_at is not None
            and datetime.fromisoformat(self.approval_expires_at) <= now
        )

    # ---- reads -------------------------------------------------------------------------

    def latest_result(self, worker: str) -> WorkerResult | None:
        for e in reversed(self.transcript):
            if e.result is not None and e.result.worker == worker and not e.result.failed:
                return e.result
        return None

    def previous_result(self, delegation: Delegation) -> WorkerResult | None:
        for e in reversed(self.transcript):
            if (
                e.result is not None
                and e.result.worker == delegation.worker
                and e.task == delegation.task
                and not e.result.failed
            ):
                return e.result
        return None

    def feedback(self) -> list[str]:
        return [e.text or "" for e in self.transcript if e.kind is EntryKind.FEEDBACK]

    @property
    def duration_ms(self) -> int | None:
        if not (self.started_at and self.finished_at):
            return None
        start, end = (datetime.fromisoformat(x) for x in (self.started_at, self.finished_at))
        return int((end - start).total_seconds() * 1000)


# ---- persistence -----------------------------------------------------------------------


def run_to_dict(run: ResearchRun) -> dict[str, Any]:
    return {
        "id": run.id,
        "task": run.task,
        "max_iterations": run.max_iterations,
        "require_approval": run.require_approval,
        "use_memory": run.use_memory,
        "iteration_limit": run.iteration_limit,
        "status": run.status.value,
        "iteration": run.iteration,
        "transcript": [entry_to_dict(e) for e in run.transcript],
        "sources": [
            {"n": s.n, "title": s.title, "url": s.url, "extract": s.extract} for s in run.sources
        ],
        "draft": run.draft,
        "approval_expires_at": run.approval_expires_at,
        "final_output": run.final_output,
        "forced": run.forced,
        "degraded": run.degraded,
        "revisions": run.revisions,
        "flags": run.flags,
        "memories": run.memories,
        "error": run.error,
        "llm_calls": run.llm_calls,
        "cached_calls": run.cached_calls,
        "tokens": {
            "input": run.tokens.input,
            "output": run.tokens.output,
            "thinking": run.tokens.thinking,
        },
        "models": run.models,
        "prompt_version": run.prompt_version,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "updated_at": run.updated_at,
    }


def run_from_dict(d: dict[str, Any]) -> ResearchRun:
    t = d["tokens"]
    return ResearchRun(
        id=d["id"],
        task=d["task"],
        max_iterations=d["max_iterations"],
        require_approval=d["require_approval"],
        use_memory=d["use_memory"],
        iteration_limit=d["iteration_limit"],
        status=RunStatus(d["status"]),
        iteration=d["iteration"],
        transcript=[entry_from_dict(e) for e in d["transcript"]],
        sources=[Source(s["n"], s["title"], s["url"], s["extract"]) for s in d["sources"]],
        draft=d["draft"],
        approval_expires_at=d["approval_expires_at"],
        final_output=d["final_output"],
        forced=d["forced"],
        degraded=d["degraded"],
        revisions=d["revisions"],
        flags=list(d["flags"]),
        memories=list(d["memories"]),
        error=d["error"],
        llm_calls=d["llm_calls"],
        cached_calls=d["cached_calls"],
        tokens=TokenUsage(t["input"], t["output"], t["thinking"]),
        models=dict(d["models"]),
        prompt_version=d.get("prompt_version", ""),
        created_at=d["created_at"],
        started_at=d["started_at"],
        finished_at=d["finished_at"],
        updated_at=d["updated_at"],
    )
