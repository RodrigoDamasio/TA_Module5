"""Tracer (course §6.2 RAGLogger, adapted): spans with timings and attributes, one JSON log
line per span and per request end. Attributes are ids, counts, scores and flags only —
callers never put question text or code in them (test Q2/Q4)."""

import json
import logging
import secrets
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

from app.domain.tracing import Span, Trace

logger = logging.getLogger("app.trace")


def new_request_id() -> str:
    return "req_" + secrets.token_hex(6)


class Tracer:
    def __init__(
        self,
        kind: str,
        request_id: str | None = None,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.kind = kind
        self.request_id = request_id or new_request_id()
        self._clock = clock
        self._start = clock()
        self.spans: list[Span] = []

    @contextmanager
    def span(self, name: str) -> Iterator[dict[str, Any]]:
        attrs: dict[str, Any] = {}
        start = self._clock()
        ok = True
        try:
            yield attrs
        except Exception as err:
            ok = False
            attrs["error"] = type(err).__name__
            raise
        finally:
            span = Span(name, (self._clock() - start) * 1000, ok, attrs)
            self.spans.append(span)
            self._log("span", {"name": name, "ms": round(span.ms, 1), "ok": ok, **attrs})

    def finish(self, **attrs: Any) -> Trace:
        trace = Trace(self.request_id, self.kind, (self._clock() - self._start) * 1000,
                      self.spans, attrs)  # fmt: skip
        self._log("request_end", {"total_ms": round(trace.total_ms, 1), **attrs})
        return trace

    def _log(self, event: str, data: dict[str, Any]) -> None:
        record = {"event": event, "kind": self.kind, "request_id": self.request_id, **data}
        logger.info(json.dumps(record, default=str))
