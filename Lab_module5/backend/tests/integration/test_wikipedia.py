"""K1–K5: the Wikipedia adapter over recorded responses (httpx.MockTransport, 0 network)."""

import httpx
import pytest

from app.domain.errors import KnowledgeUnavailable
from app.domain.ports import SearchHit
from app.infrastructure.sqlite_store import SqliteWikiCache
from app.infrastructure.wikipedia import USER_AGENT, WikipediaSource, trim_extract

SEARCH = {
    "batchcomplete": True,
    "query": {"search": [{"ns": 0, "title": "Retrieval-augmented generation", "pageid": 75566}]},
}
EXTRACT = {
    "batchcomplete": True,
    "query": {
        "pages": [
            {
                "pageid": 75566,
                "title": "Retrieval-augmented generation",
                "extract": "RAG lets a model use documents.\n\nIt keeps answers current.",
                "fullurl": "https://en.wikipedia.org/wiki/Retrieval-augmented_generation",
            }
        ]
    },
}


class Recorder:
    def __init__(self, fail: int = 0, status: int = 200) -> None:
        self.requests: list[httpx.Request] = []
        self.fail, self.status = fail, status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            self.fail -= 1
            raise httpx.ConnectTimeout("timeout", request=request)
        if self.status != 200:
            return httpx.Response(self.status, request=request)
        body = SEARCH if request.url.params.get("list") == "search" else EXTRACT
        return httpx.Response(200, json=body, request=request)


class Clock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def source(tmp_path, recorder: Recorder, clock: Clock | None = None, **kw) -> WikipediaSource:
    client = httpx.Client(
        transport=httpx.MockTransport(recorder), headers={"User-Agent": USER_AGENT}
    )
    clock = clock or Clock()
    cache = SqliteWikiCache(str(tmp_path / "w.db"), clock=lambda: clock.now)
    return WikipediaSource(cache, client=client, clock=clock, sleep=lambda s: None, **kw)


# K1
def test_search_and_extract_mapping(tmp_path):
    rec = Recorder()
    wiki = source(tmp_path, rec)
    hits = wiki.search("rag fine-tuning", 3)
    assert hits == [SearchHit("Retrieval-augmented generation", 75566)]
    (draft,) = wiki.fetch(hits, 6000)
    assert draft.url == "https://en.wikipedia.org/wiki/Retrieval-augmented_generation"
    assert draft.extract.startswith("RAG lets") and draft.title == "Retrieval-augmented generation"
    search, extract = rec.requests
    assert (
        search.url.params["srsearch"] == "rag fine-tuning" and search.url.params["srlimit"] == "3"
    )
    assert extract.url.params["pageids"] == "75566" and extract.url.params["explaintext"] == "1"


# K2
def test_extract_trimmed_at_a_paragraph_boundary():
    text = "A" * 60 + "\n\n" + "B" * 60
    assert trim_extract(text, 100) == "A" * 60 + "\n[…]"
    assert trim_extract("C" * 120, 100) == "C" * 100 + "\n[…]"
    assert trim_extract("short", 100) == "short"


# K3
def test_cache_within_ttl_then_refetch(tmp_path):
    rec, clock = Recorder(), Clock()
    wiki = source(tmp_path, rec, clock, ttl_s=60)
    wiki.search("rag", 3)
    wiki.search("rag", 3)
    assert len(rec.requests) == 1
    clock.now += 61
    wiki.search("rag", 3)
    assert len(rec.requests) == 2


# K4
def test_failures_open_the_breaker(tmp_path):
    rec, clock = Recorder(fail=3), Clock()
    wiki = source(tmp_path, rec, clock, open_s=300)
    for query in ("a", "b", "c"):
        with pytest.raises(KnowledgeUnavailable):
            wiki.search(query, 3)
    assert not wiki.available()
    with pytest.raises(KnowledgeUnavailable):
        wiki.search("d", 3)
    assert len(rec.requests) == 3  # open: no request sent
    clock.now += 301
    assert wiki.available() and wiki.search("e", 3)

    errors = source(tmp_path / "e", Recorder(status=503))
    with pytest.raises(KnowledgeUnavailable):
        errors.search("x", 3)

    class ApiError(Recorder):
        def __call__(self, request):
            return httpx.Response(200, json={"error": {"code": "bad"}}, request=request)

    with pytest.raises(KnowledgeUnavailable, match="error"):
        source(tmp_path / "x", ApiError()).search("x", 3)


# K5
def test_fixed_host_user_agent_and_foreign_urls(tmp_path):
    rec = Recorder()
    wiki = source(tmp_path, rec, lang="pt")
    wiki.search("x", 1)
    assert rec.requests[0].url.host == "pt.wikipedia.org"
    assert rec.requests[0].headers["User-Agent"] == USER_AGENT
    with pytest.raises(ValueError):
        source(tmp_path / "b", Recorder(), lang="evil.com/")

    class Foreign(Recorder):
        def __call__(self, request):
            body = {
                "query": {
                    "pages": [{"title": "T", "extract": "x", "fullurl": "https://evil.example/x"}]
                }
            }
            return httpx.Response(200, json=body, request=request)

    (draft,) = source(tmp_path / "f", Foreign()).fetch([SearchHit("T", 7)], 100)
    assert draft.url == "https://en.wikipedia.org/?curid=7"
    empty = {"query": {"pages": [{"title": "T", "extract": ""}]}}

    class Empty(Recorder):
        def __call__(self, request):
            return httpx.Response(200, json=empty, request=request)

    assert source(tmp_path / "g", Empty()).fetch([SearchHit("T", 8)], 100) == []


@pytest.mark.live_wiki
def test_live_wikipedia_contract(tmp_path):  # pragma: no cover — opt-in, real network
    wiki = WikipediaSource(SqliteWikiCache(str(tmp_path / "live.db")))
    hits = wiki.search("retrieval augmented generation", 2)
    drafts = wiki.fetch(hits, 2000)
    assert hits and drafts and drafts[0].url.startswith("https://en.wikipedia.org/")
