"""Researcher: Wikipedia first (deterministic, 0 LLM calls), then ONE summarizing call that
cites the sources as [n]. No source → notes from general knowledge, marked UNSOURCED."""

import re

from app.application.prompts import PromptLibrary
from app.domain.errors import KnowledgeUnavailable
from app.domain.ports import KnowledgeSource, LLMClient, LLMRequest, SourceDraft, UserMessage
from app.domain.transcript import WorkerResult

from .base import WorkerContext, WorkerOutput, clean_citations, text_of

STOP_WORDS = frozenset(
    """a an the and or but of to in on at for from by with about into over under between
    is are was were be been being do does did have has had can could should would will may
    might must this that these those it its their there here what which who whom whose when
    where why how than then so such as if not no yes very more most less least each every
    all any some few many much other another same own also just only both either neither
    i you he she we they me my your our us them his her
    find research summarize summarise explain describe compare list give provide include
    including gather collect look search identify key main facts information details notes
    sources source overview background topic topics use using used please brief short
    current recent latest example examples""".split()
)
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#.\-']*")


def build_query(text: str, max_terms: int = 8) -> str:
    """Keywords from the TASK, in order: lower case, no stop words, no duplicates."""
    terms: list[str] = []
    for word in _WORD.findall(text.lower()):
        w = word.strip(".'-")
        if len(w) > 1 and w not in STOP_WORDS and w not in terms:
            terms.append(w)
        if len(terms) == max_terms:
            break
    return " ".join(terms)


class Researcher:
    name = "researcher"
    title = "Researcher"
    description = (
        "finds Wikipedia articles for an assignment and writes research notes that cite "
        "them as [n]; give it a focused research question"
    )
    needs: frozenset[str] = frozenset()

    def __init__(
        self, prompts: PromptLibrary, source: KnowledgeSource, max_pages: int, max_chars: int
    ) -> None:
        self._prompts, self._source = prompts, source
        self._max_pages, self._max_chars = max_pages, max_chars

    def _find(self, task: str, user_task: str) -> tuple[list[SourceDraft], str, str | None]:
        """(drafts, query, notice) — never raises: no source means unsourced notes.
        Queries tried in order: the TASK (8 terms), the TASK (4 terms), the user's task."""
        queries = list(
            dict.fromkeys(
                q for q in (build_query(task), build_query(task, 4), build_query(user_task)) if q
            )
        )
        query = queries[0] if queries else ""
        if not self._source.available():
            return [], query, "Wikipedia is temporarily unavailable; the research is unsourced."
        try:
            hits = []
            for query in queries:
                if hits := self._source.search(query, self._max_pages):
                    break
            drafts = self._source.fetch(hits, self._max_chars) if hits else []
        except KnowledgeUnavailable:
            return [], query, "Wikipedia could not be reached; the research is unsourced."
        if not drafts:
            return [], query, "No Wikipedia article matched; the research is unsourced."
        return drafts, query, None

    def run(self, task: str, ctx: WorkerContext, llm: LLMClient) -> WorkerOutput:
        drafts, query, notice = self._find(task, ctx.user_task)
        sources = ctx.register_sources(drafts) if drafts else []
        user_task = ctx.fence.wrap(ctx.user_task, "user_task")
        if sources:
            per_source = max(1500, ctx.context_chars // len(sources))
            blocks = "\n\n".join(
                ctx.fence.wrap(s.extract[:per_source], "wikipedia", n=s.n, title=s.title)
                for s in sources
            )
            user = self._prompts.worker_task(
                "researcher_task", user_task=user_task, task=task, sources=blocks
            )
        else:
            user = self._prompts.worker_task("researcher_unsourced", user_task=user_task, task=task)
        response = llm.generate(
            LLMRequest(
                system=self._prompts.worker_system(self.name, ctx.canary),
                messages=[UserMessage(user)],
                max_output_tokens=1400,
                thinking_budget=0,
                model=ctx.model,
            )
        )
        notes, cited, unknown = clean_citations(text_of(response), {s.n for s in sources})
        notices = [(notice, "unsourced")] if notice else []
        if unknown:
            notices.append(
                (f"Removed {len(unknown)} citation(s) to unknown sources.", "unknown_citation")
            )
        result = WorkerResult(
            self.name,
            notes,
            {"query": query, "sources": [s.n for s in sources]},
            cited,
            unsourced=not sources,
        )
        return WorkerOutput(result, notices)
