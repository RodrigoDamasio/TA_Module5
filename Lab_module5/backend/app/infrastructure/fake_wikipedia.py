"""WIKI_MODE=fake: a few built-in articles and keyword search — no network. Used by
LLM_MODE=fake (UI work, local E2E) and the tests."""

import re

from app.domain.errors import KnowledgeUnavailable
from app.domain.ports import SearchHit, SourceDraft

ARTICLES: dict[str, str] = {
    "Retrieval-augmented generation": (
        "Retrieval-augmented generation (RAG) is a technique that lets a large language model "
        "retrieve documents from an external source and use them when it generates an "
        "answer.\n\nRAG keeps answers current without retraining, because the documents can "
        "be updated at any time. It also lets a system cite where an answer came from."
    ),
    "Fine-tuning (deep learning)": (
        "Fine-tuning is the process of further training a pre-trained model on a smaller, "
        "task-specific dataset.\n\nIt adapts the model's behavior, style or format, but it "
        "needs labeled data and compute, and new facts require training again."
    ),
    "SQLite": (
        "SQLite is an embedded relational database engine that stores a whole database in a "
        "single file.\n\nIt needs no separate server process and suits small applications, "
        "but it allows only one writer at a time."
    ),
    "PostgreSQL": (
        "PostgreSQL is an open-source client-server relational database system.\n\nIt "
        "supports many concurrent writers, rich data types and extensions, and needs a "
        "server to run and maintain."
    ),
    "HTTP caching": (
        "HTTP caching stores copies of responses so later requests can be served faster.\n\n"
        "The Cache-Control header sets how long a response may be reused; validators such "
        "as ETag let a client check whether its copy is still fresh."
    ),
    "Python (programming language)": (
        "Python is a high-level programming language created by Guido van Rossum and first "
        "released in 1991.\n\nPython 3.0 was released in 2008 and was not fully backward "
        "compatible with Python 2."
    ),
}
_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if len(w) > 2}


class FakeWikipedia:
    name = "wikipedia"
    host = "https://en.wikipedia.org"

    def __init__(self, articles: dict[str, str] | None = None, down: bool = False) -> None:
        self.articles = ARTICLES if articles is None else articles
        self.down = down
        self.searches: list[str] = []
        self._ids = {title: i for i, title in enumerate(self.articles, 1)}

    def available(self) -> bool:
        return not self.down

    def search(self, query: str, limit: int) -> list[SearchHit]:
        if self.down:
            raise KnowledgeUnavailable("Fake Wikipedia is down.")
        self.searches.append(query)
        terms = _words(query)
        scored = sorted(
            ((len(terms & _words(f"{t} {body}")), t) for t, body in self.articles.items()),
            key=lambda x: (-x[0], x[1]),
        )
        return [SearchHit(t, self._ids[t]) for score, t in scored if score > 0][:limit]

    def fetch(self, hits: list[SearchHit], max_chars: int) -> list[SourceDraft]:
        return [
            SourceDraft(
                h.title,
                f"{self.host}/wiki/{h.title.replace(' ', '_')}",
                self.articles[h.title][:max_chars],
            )
            for h in hits
            if h.title in self.articles
        ]
