"""Keyword search (extension: hybrid search): a code-aware tokenizer and an incremental
BM25 index (Okapi, Lucene IDF). Own code instead of rank-bm25 because files are re-indexed
and codebases expire: documents must be added and removed without rebuilding (§8.2)."""

import math
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass

_WORD = re.compile(r"[A-Za-z0-9_]+")
_CAMEL = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+")
STOP_WORDS = frozenset(
    "the a an and or of to in on for is are be by it as at with from this that what how "
    "does do which where when who why self this return const let var def import export "
    "function class async await new none null true false".split()
)


def tokenize(text: str) -> list[str]:
    """`processOrder` → process, order, processorder; `get_current_user` → get, current,
    user, get_current_user. Lowercase; stop words and 1-char tokens dropped."""
    tokens: list[str] = []
    for word in _WORD.findall(text):
        parts = [p for chunk in word.split("_") for p in _CAMEL.findall(chunk)]
        lowered = [p.lower() for p in parts]
        tokens += lowered
        joined = word.lower()
        if len(lowered) > 1:
            tokens.append(joined)
    return [t for t in tokens if len(t) > 1 and t not in STOP_WORDS]


@dataclass(frozen=True)
class KeywordHit:
    chunk_id: str
    score: float
    matched_terms: list[str]


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1, self.b = k1, b
        self._docs: dict[str, tuple[str, Counter[str], int]] = {}  # id → (codebase, tf, len)
        self._postings: dict[str, set[str]] = defaultdict(set)
        self._by_file: dict[tuple[str, str], set[str]] = defaultdict(set)
        self._file_of: dict[str, tuple[str, str]] = {}
        self._total_len = 0
        self._lock = threading.Lock()

    def __len__(self) -> int:
        return len(self._docs)

    def add(self, chunk_id: str, codebase: str, text: str, path: str = "") -> None:
        tokens = tokenize(text)
        with self._lock:
            if chunk_id in self._docs:
                self._remove(chunk_id)
            tf = Counter(tokens)
            self._docs[chunk_id] = (codebase, tf, len(tokens))
            self._by_file[(codebase, path)].add(chunk_id)
            self._file_of[chunk_id] = (codebase, path)
            self._total_len += len(tokens)
            for term in tf:
                self._postings[term].add(chunk_id)

    def remove(self, chunk_id: str) -> None:
        with self._lock:
            self._remove(chunk_id)

    def remove_file(self, codebase: str, path: str) -> int:
        with self._lock:
            ids = list(self._by_file.get((codebase, path), ()))
            for i in ids:
                self._remove(i)
            return len(ids)

    def remove_codebase(self, codebase: str) -> int:
        with self._lock:
            ids = [i for i, (cb, _, _) in self._docs.items() if cb == codebase]
            for i in ids:
                self._remove(i)
            return len(ids)

    def _remove(self, chunk_id: str) -> None:
        doc = self._docs.pop(chunk_id, None)
        if doc is None:
            return
        _, tf, length = doc
        self._total_len -= length
        key = self._file_of.pop(chunk_id, None)
        if key is not None:
            self._by_file[key].discard(chunk_id)
            if not self._by_file[key]:
                del self._by_file[key]
        for term in tf:
            ids = self._postings.get(term)
            if ids is not None:
                ids.discard(chunk_id)
                if not ids:
                    del self._postings[term]

    def search(self, query: str, codebases: list[str], n: int) -> list[KeywordHit]:
        terms = list(dict.fromkeys(tokenize(query)))
        allowed = set(codebases)
        with self._lock:
            total = len(self._docs)
            if not total or not terms:
                return []
            avg_len = self._total_len / total
            scores: dict[str, float] = defaultdict(float)
            matched: dict[str, list[str]] = defaultdict(list)
            for term in terms:
                ids = self._postings.get(term, set())
                if not ids:
                    continue
                idf = math.log(1 + (total - len(ids) + 0.5) / (len(ids) + 0.5))
                for chunk_id in ids:
                    codebase, tf, length = self._docs[chunk_id]
                    if codebase not in allowed:
                        continue
                    f = tf[term]
                    norm = (
                        f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / avg_len))
                    )
                    scores[chunk_id] += idf * norm
                    matched[chunk_id].append(term)
        ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:n]
        return [KeywordHit(i, s, matched[i]) for i, s in ranked]
