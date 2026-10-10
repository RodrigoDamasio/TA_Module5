"""WikipediaSource: the Researcher's knowledge source (MediaWiki Action API).

Safety: one fixed host built from config (no user-supplied URL is ever fetched → no SSRF),
read-only GETs, a descriptive User-Agent (Wikimedia policy), requests serialized and spaced,
responses cached with a TTL, and a small circuit breaker (3 failures → 5 min open)."""

import hashlib
import logging
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol

import httpx

from app.domain.errors import KnowledgeUnavailable
from app.domain.ports import SearchHit, SourceDraft

logger = logging.getLogger("app.wikipedia")
USER_AGENT = "TallerAcademyLab5/1.0 (https://github.com/RodrigoDamasio/TA_Module5)"


class TtlCache(Protocol):
    def get(self, key: str, max_age_s: float) -> dict | None: ...

    def put(self, key: str, value: dict) -> None: ...


def trim_extract(text: str, max_chars: int) -> str:
    """Cut at a paragraph boundary when one is in the second half of the limit."""
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    boundary = cut.rfind("\n\n")
    if boundary > max_chars // 2:
        cut = cut[:boundary]
    return cut.rstrip() + "\n[…]"


class WikipediaSource:
    name = "wikipedia"

    def __init__(
        self,
        cache: TtlCache,
        lang: str = "en",
        timeout_s: float = 8,
        ttl_s: float = 7 * 86400,
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        min_interval_s: float = 0.2,
        failure_threshold: int = 3,
        open_s: float = 300,
    ) -> None:
        if not lang.isalpha() or len(lang) > 10:
            raise ValueError("WIKI_LANG must be a language code such as 'en'.")
        self.host = f"https://{lang}.wikipedia.org"
        self._api = f"{self.host}/w/api.php"
        self._cache, self._ttl = cache, ttl_s
        self._client = client or httpx.Client(
            timeout=timeout_s, headers={"User-Agent": USER_AGENT}, follow_redirects=False
        )
        self._clock, self._sleep, self._interval = clock, sleep, min_interval_s
        self._threshold, self._open_s = failure_threshold, open_s
        self._failures, self._open_until, self._last = 0, 0.0, -1e9
        self._lock = threading.Lock()

    # ---- breaker ------------------------------------------------------------------------

    def available(self) -> bool:
        return self._clock() >= self._open_until

    def _failed(self) -> None:
        self._failures += 1
        if self._failures >= self._threshold:
            self._open_until = self._clock() + self._open_s
            self._failures = 0
            logger.warning("wikipedia breaker open for %.0fs", self._open_s)

    # ---- requests -------------------------------------------------------------------------

    def _get(self, params: dict[str, str]) -> dict[str, Any]:
        params = {**params, "format": "json", "formatversion": "2"}
        key = hashlib.sha256(
            str(httpx.URL(self._api, params=sorted(params.items()))).encode()
        ).hexdigest()
        if (hit := self._cache.get(key, self._ttl)) is not None:
            return hit
        if not self.available():
            raise KnowledgeUnavailable("Wikipedia is temporarily unavailable.")
        with self._lock:  # serialized and spaced (Wikimedia etiquette)
            wait = self._interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
            self._last = self._clock()
            try:
                response = self._client.get(self._api, params=params)
                response.raise_for_status()
                data = response.json()
            except (httpx.HTTPError, ValueError) as err:
                self._failed()
                logger.warning("wikipedia request failed: %s", type(err).__name__)
                raise KnowledgeUnavailable("Wikipedia could not be reached.") from err
        if not isinstance(data, dict) or "error" in data:
            self._failed()
            raise KnowledgeUnavailable("Wikipedia returned an error.")
        self._failures = 0
        self._cache.put(key, data)
        return data

    def search(self, query: str, limit: int) -> list[SearchHit]:
        data = self._get(
            {
                "action": "query",
                "list": "search",
                "srsearch": query[:300],
                "srlimit": str(limit),
                "srprop": "",
            }
        )
        results = data.get("query", {}).get("search", [])
        return [SearchHit(r["title"], int(r["pageid"])) for r in results if "pageid" in r]

    def fetch(self, hits: list[SearchHit], max_chars: int) -> list[SourceDraft]:
        drafts = []
        for hit in hits:
            data = self._get(
                {
                    "action": "query",
                    "prop": "extracts|info",
                    "explaintext": "1",
                    "inprop": "url",
                    "pageids": str(hit.page_id),
                }
            )
            pages = data.get("query", {}).get("pages", [])
            if not pages or not (extract := (pages[0].get("extract") or "").strip()):
                continue
            page = pages[0]
            url = str(page.get("fullurl") or "")
            if not url.startswith(self.host + "/"):  # only links to the configured host
                url = f"{self.host}/?curid={hit.page_id}"
            drafts.append(
                SourceDraft(page.get("title", hit.title), url, trim_extract(extract, max_chars))
            )
        return drafts
