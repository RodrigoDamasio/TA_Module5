"""What the Supervisor sees: its view of the transcript, the source list and the recalled
memories, within a token budget. Worker results are untrusted text, so each one is fenced.

Budget rule: results are first trimmed to RESULT_CHARS each, the latest Writer draft is
always shown in full (FINAL is built from it); if the prompt is still over budget, older
results are trimmed further, oldest first."""

import re

from app.domain.run import ResearchRun
from app.domain.transcript import EntryKind, TranscriptEntry

from .prompts import estimate_tokens
from .security import DataFence
from .workers.base import CITATION, trim

RESULT_CHARS = 1200
MIN_RESULT_CHARS = 300
SOURCES_HEADING = re.compile(r"^\s*(#{1,6}\s*|\*\*)\s*sources\b", re.IGNORECASE | re.MULTILINE)


def source_list(run: ResearchRun) -> str:
    if not run.sources:
        return "(none yet)"
    return "\n".join(f"[{s.n}] {s.title} — {s.url}" for s in run.sources)


def memory_block(run: ResearchRun, fence: DataFence) -> str:
    if not run.memories:
        return "(none)"
    return "\n\n".join(
        fence.wrap(f"Task: {m['task']}\nSummary: {m['summary']}", "memory", run=m["run_id"])
        for m in run.memories
    )


def _render(e: TranscriptEntry, fence: DataFence, limit: int | None) -> str:
    head = f"[iteration {e.iteration}]"
    if e.kind is EntryKind.DECISION and e.decision is not None:
        d = e.decision
        if d.final is not None:
            return f"{head} You proposed a FINAL answer (sent to the human reviewer)."
        moves = "; ".join(f"DELEGATE {x.worker} — TASK: {x.task}" for x in d.delegations)
        return f"{head} You: {moves}"
    if e.kind is EntryKind.WORKER_RESULT and e.result is not None:
        content = e.result.content if limit is None else trim(e.result.content, limit)
        status = " (failed)" if e.result.failed else ""
        body = fence.wrap(content, "worker_result", worker=e.result.worker)
        return f"{head} Result from {e.result.worker}{status}:\n{body}"
    if e.kind is EntryKind.FEEDBACK:
        return f"{head} Human reviewer feedback on your FINAL answer (revise it):\n" + fence.wrap(
            e.text or "", "human_feedback"
        )
    return f"[note] {e.text}"


def transcript_view(run: ResearchRun, fence: DataFence, budget_tokens: int) -> str:
    entries = run.transcript
    if not entries:
        return "(nothing yet: this is your first decision)"
    latest_draft = next(
        (
            e.seq
            for e in reversed(entries)
            if e.result is not None and e.result.worker == "writer" and not e.result.failed
        ),
        None,
    )
    limits: dict[int, int | None] = {
        e.seq: None if e.seq == latest_draft else RESULT_CHARS for e in entries
    }

    def render() -> str:
        return "\n\n".join(_render(e, fence, limits[e.seq]) for e in entries)

    text = render()
    for e in entries:  # oldest first
        if estimate_tokens(text) <= budget_tokens:
            break
        if e.result is not None and limits[e.seq] is not None:
            limits[e.seq] = MIN_RESULT_CHARS
            text = render()
    return text


def sources_section(run: ResearchRun, text: str) -> str:
    """A deterministic 'Sources' list for the sources cited in `text`."""
    cited = {int(n) for n in CITATION.findall(text)}
    lines = [f"{s.n}. {s.title} — {s.url}" for s in run.sources if s.n in cited]
    return "### Sources\n" + "\n".join(lines) if lines else ""


def has_sources_section(text: str) -> bool:
    return bool(SOURCES_HEADING.search(text))
