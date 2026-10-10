"""Memory (extension): what earlier runs found, recalled for the Supervisor with BM25 (Lab 4).

Memories whose task equals the current task are excluded, so re-running a task never
changes its own prompt and the response cache stays effective (Lab 3 lesson)."""

import re

from app.domain.ports import Memory, MemoryRepository
from app.domain.run import ResearchRun, now_iso

from .retrieval.bm25 import BM25Index

RECALL_WINDOW = 500
SUMMARY_CHARS = 600
_MARKDOWN = re.compile(r"[#*_`>|]+|\[\d{1,3}\]")
_LINK = re.compile(r"\[([^\]]+)\]\([^)]+\)")


def _key(task: str) -> str:
    return " ".join(task.lower().split())


def summarize(markdown: str, limit: int = SUMMARY_CHARS) -> str:
    text = _LINK.sub(r"\1", markdown)
    text = text.split("### Sources")[0]
    text = " ".join(_MARKDOWN.sub(" ", text).split())
    return text[:limit].rsplit(" ", 1)[0] + "…" if len(text) > limit else text


def memory_from_run(run: ResearchRun) -> Memory:
    cited = {n for e in run.transcript if e.result is not None for n in e.result.source_ns}
    titles = [s.title for s in run.sources if s.n in cited] or [s.title for s in run.sources]
    return Memory(run.id, run.task, summarize(run.final_output or ""), titles[:5], now_iso())


class BM25Memory:
    """MemoryStore over a MemoryRepository."""

    def __init__(self, repo: MemoryRepository) -> None:
        self._repo = repo

    def record(self, memory: Memory) -> None:
        self._repo.record(memory)

    def recall(self, query: str, limit: int, exclude_task: str) -> list[Memory]:
        excluded = _key(exclude_task)
        newest_per_task: dict[str, Memory] = {}
        for m in self._repo.recent(RECALL_WINDOW):  # newest first
            if _key(m.task) != excluded:
                newest_per_task.setdefault(_key(m.task), m)
        candidates = {m.run_id: m for m in newest_per_task.values()}
        if not candidates or limit <= 0:
            return []
        index = BM25Index()
        for m in candidates.values():
            index.add(m.run_id, "memory", f"{m.task} {m.task} {m.summary}")
        hits = index.search(query, ["memory"], limit)
        return [candidates[h.chunk_id] for h in hits if h.score > 0]
