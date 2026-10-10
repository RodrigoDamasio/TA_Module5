"""Researcher: Wikipedia first (deterministic, 0 LLM calls), then ONE summarizing call that
cites the sources as [n]. No source → notes from general knowledge, marked UNSOURCED."""

import re

from app.application.prompts import PromptLibrary
from app.domain.errors import KnowledgeUnavailable
from app.domain.ports import (
    KnowledgeSource,
    LLMClient,
    LLMRequest,
    SearchHit,
    SourceDraft,
    UserMessage,
)
from app.domain.transcript import WorkerResult

from .base import WorkerContext, WorkerOutput, clean_citations, text_of, truncation

STOP_WORDS = frozenset(
    """a an the and or but of to in on at for from by with about into over under between
    is are was were be been being do does did have has had can could should would will may
    might must this that these those it its their there here what which who whom whose when
    where why how than then so such as if not no yes very more most less least each every
    all any some few many much other another same own also just only both either neither
    i you he she we they me my your our us them his her
    find research summarize summarise explain explaining describe describing compare list
    give provide include including gather collect look search identify key main facts
    information details notes sources source overview background topic topics use using
    used please brief short current recent latest example examples wikipedia article
    articles reliable conceptual discuss discussing difference differences guideline
    guidelines guide choose choosing versus vs case cases understanding concept concepts
    related regarding various types aspects cover covering""".split()
)
_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9+#.\-']*")
_TOPICS = re.compile(r"^\s*topics?\s*:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
MAX_TOPICS = 4


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


def topics_of(task: str) -> list[str]:
    """The Supervisor's 'Topics: A; B' line (asked for in its prompt), if any."""
    m = _TOPICS.search(task)
    if not m:
        return []
    parts = (t.strip().strip("\"'`*.").strip() for t in re.split(r"[;|]", m.group(1)))
    return list(dict.fromkeys(t[:80] for t in parts if t))[:MAX_TOPICS]


def _forms(text: str) -> set[str]:
    """Words with and without their hyphen parts: 'fine-tuning' → fine-tuning, fine, tuning."""
    out = set()
    for w in re.split(r"[\s()\[\],;:/]+", text.lower()):
        w = w.strip(".'\"-")
        if w:
            out.add(w)
            out.update(p for p in w.split("-") if p)
    return out


def relevant(title: str, query: str) -> bool:
    """Keyword hits must share a term with the query (4-letter prefix: plurals, -ing) or
    match an acronym ('rag' → 'Retrieval-augmented generation')."""
    words = [w for w in re.split(r"[\s\-()]+", title.lower()) if w]
    initials = "".join(w[0] for w in words)
    terms, forms = query.split(), _forms(title)
    return any(t == initials for t in terms if len(t) >= 2) or any(
        w[:4] == t[:4] for w in forms if len(w) >= 3 for t in _forms(query) if len(t) >= 3
    )


class Researcher:
    name = "researcher"
    title = "Researcher"
    description = (
        "looks up Wikipedia articles and writes research notes that cite them as [n]; start "
        "its TASK with a line 'Topics: <topic>; <topic>' naming 1 to 3 encyclopedia topics to "
        "look up (for example 'Topics: Retrieval-augmented generation; Fine-tuning (deep "
        "learning)'), then the research question"
    )
    needs: frozenset[str] = frozenset()

    def __init__(
        self, prompts: PromptLibrary, source: KnowledgeSource, max_pages: int, max_chars: int
    ) -> None:
        self._prompts, self._source = prompts, source
        self._max_pages, self._max_chars = max_pages, max_chars

    def _search_topics(self, topics: list[str]) -> list[SearchHit]:
        """Each topic separately; results merged round-robin (comparisons get both sides)."""
        per_topic = [self._source.search(t, 2) for t in topics]
        merged: dict[int, SearchHit] = {}
        for rank in range(2):
            for hits in per_topic:
                if rank < len(hits):
                    merged.setdefault(hits[rank].page_id, hits[rank])
        return list(merged.values())[: self._max_pages]

    def _find(self, task: str, user_task: str) -> tuple[list[SourceDraft], str, str | None]:
        """(drafts, query, notice) — never raises: no source means unsourced notes.
        Order: the Supervisor's topics; then keywords from the TASK (8, then 4 terms) and
        from the user's task, keeping only hits whose title matches the keywords."""
        topics = topics_of(task)
        keyword_task = _TOPICS.sub("", task)
        queries = list(
            dict.fromkeys(
                q
                for q in (
                    build_query(keyword_task),
                    build_query(keyword_task, 4),
                    build_query(user_task),
                )
                if q
            )
        )
        query = "topics: " + "; ".join(topics) if topics else (queries[0] if queries else "")
        if not self._source.available():
            return [], query, "Wikipedia is temporarily unavailable; the research is unsourced."
        try:
            hits = self._search_topics(topics) if topics else []
            for q in queries if not hits else []:
                hits = [h for h in self._source.search(q, self._max_pages) if relevant(h.title, q)]
                if hits:
                    query = q
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
                max_output_tokens=3072,
                thinking_budget=0,
                model=ctx.model,
            )
        )
        notes, cited, unknown = clean_citations(text_of(response), {s.n for s in sources})
        notices = [(notice, "unsourced")] if notice else []
        notices += truncation(response, self.name)
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
