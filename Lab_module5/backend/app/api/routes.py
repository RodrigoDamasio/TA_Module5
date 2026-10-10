"""HTTP endpoints. Thin: validate, rate-limit, call a use case, shape the response."""

import asyncio
import logging
from collections.abc import AsyncIterable
from typing import Any

from fastapi import APIRouter, Depends, Header, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.sse import EventSourceResponse, ServerSentEvent
from starlette.concurrency import run_in_threadpool

from app.domain.run import ResearchRun

from .dependencies import Container, get_container
from .problems import PROBLEM_RESPONSE, WaitTimeout
from .schemas import Accepted, RejectRequest, RunRequest, run_view

router = APIRouter()
logger = logging.getLogger("app.api")
SSE_POLL_S = 0.5
TERMINAL_EVENTS = {"completed", "failed", "cancelled"}


def _problems(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: PROBLEM_RESPONSE for code in codes}


def _client(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _view(c: Container, run: ResearchRun) -> dict[str, Any]:
    return run_view(run, c.pricing, demo=c.settings.fake)


# ---- observability ---------------------------------------------------------------------------


@router.get("/health", tags=["observability"])
def health(c: Container = Depends(get_container)) -> dict[str, Any]:
    """Liveness + service level (full | reduced | minimal), models and today's usage."""
    return c.health()


@router.get("/stats", tags=["observability"])
def stats(c: Container = Depends(get_container)) -> dict[str, Any]:
    """Cost and quota monitoring: calls today vs the limit, cache hit rate, tokens, a
    paid-tier cost equivalent, runs by status and run latency."""
    return c.stats.stats()


@router.get("/agents", tags=["agents"])
def agents(c: Container = Depends(get_container)) -> list[dict[str, str]]:
    """The Supervisor and the worker registry."""
    supervisor = {
        "name": "supervisor",
        "title": "Supervisor",
        "role": "supervisor",
        "description": "decides which worker acts next (DELEGATE/TASK) and writes the final "
        "answer (FINAL)",
    }
    return [supervisor] + [
        {"name": w.name, "title": w.title, "role": "worker", "description": w.description}
        for w in c.registry.all()
    ]


# ---- runs --------------------------------------------------------------------------------


def _field_error(pointer: str, detail: str) -> RequestValidationError:
    return RequestValidationError(
        [{"type": "value_error", "loc": ("body", *pointer[2:].split("/")), "msg": detail}]
    )


@router.post(
    "/run",
    status_code=202,
    responses={200: {"description": "Finished run (with ?wait=true)"}}
    | _problems(400, 413, 422, 429, 503, 504),
    tags=["runs"],
)
def start_run(
    body: RunRequest,
    request: Request,
    response: Response,
    wait: bool = Query(False, description="Block until the run ends (needs no approval)."),
    c: Container = Depends(get_container),
) -> Accepted | dict[str, Any]:
    """Start a research run. Async by default (202 + Location + SSE events); with
    `?wait=true` the finished run is returned (200)."""
    if wait and body.require_approval:
        raise _field_error("#/require_approval", "Must be false when wait=true.")
    c.service.check_input(body.task, body.max_iterations)  # free checks first
    c.limiter.check(_client(request))  # only requests that would start a run count
    run = c.service.submit(body.task, body.max_iterations, body.require_approval, body.use_memory)
    status_url = f"/runs/{run.id}"
    response.headers["Location"] = status_url
    if wait:
        run = c.service.wait(run.id, c.settings.sync_wait_timeout_s)
        if not run.done:
            raise WaitTimeout(run.id, c.settings.sync_wait_timeout_s)
        response.status_code = 200
        return _view(c, run)
    return Accepted(
        run_id=run.id,
        status=run.status.value,
        status_url=status_url,
        events_url=f"{status_url}/events",
    )


@router.get("/runs/{run_id}", responses=_problems(404), tags=["runs"])
def get_run(run_id: str, c: Container = Depends(get_container)) -> dict[str, Any]:
    return _view(c, c.service.get(run_id))


def _existing_run(run_id: str, c: Container = Depends(get_container)) -> str:
    """Checked before the stream starts, so an unknown id is a normal 404 problem."""
    return c.service.get(run_id).id


@router.get(
    "/runs/{run_id}/events",
    response_class=EventSourceResponse,
    responses=_problems(404),
    tags=["runs"],
)
async def run_events(
    request: Request,
    run_id: str = Depends(_existing_run),
    last_event_id: str | None = Header(None),
    c: Container = Depends(get_container),
) -> AsyncIterable[ServerSentEvent]:
    """Replays the run's events after `Last-Event-ID`, then follows new ones; ends after
    `completed`, `failed` or `cancelled`. Events come from the database, so a reconnect
    loses nothing."""
    after = int(last_event_id) if last_event_id and last_event_id.isdigit() else 0
    while True:
        events = await run_in_threadpool(c.service.runs.events_since, run_id, after)
        if not events:
            run = await run_in_threadpool(c.service.get, run_id)
            if run.done:  # the terminal event was already sent (or is read just now)
                events = await run_in_threadpool(c.service.runs.events_since, run_id, after)
                if not events:
                    return
        for event in events:
            after = event.id or after
            yield ServerSentEvent(data=event.data, event=event.type, id=str(event.id))
            if event.type in TERMINAL_EVENTS:
                return
        if await request.is_disconnected():
            return
        await asyncio.sleep(SSE_POLL_S)


@router.post("/runs/{run_id}/approve", responses=_problems(404, 409), tags=["runs"])
def approve(run_id: str, c: Container = Depends(get_container)) -> dict[str, Any]:
    return _view(c, c.service.approve(run_id))


@router.post("/runs/{run_id}/reject", responses=_problems(404, 409, 422, 503), tags=["runs"])
def reject(
    run_id: str, body: RejectRequest | None = None, c: Container = Depends(get_container)
) -> dict[str, Any]:
    feedback = body.feedback.strip() if body and body.feedback else None
    return _view(c, c.service.reject(run_id, feedback or None))


# ---- samples -------------------------------------------------------------------------------


@router.get("/samples", tags=["samples"])
def list_samples(c: Container = Depends(get_container)) -> list[dict[str, Any]]:
    """Stored completed runs (0 LLM calls), replayable in the UI."""
    return c.samples.catalog()


@router.get("/samples/{sample_id}", responses=_problems(404), tags=["samples"])
def get_sample(sample_id: str, c: Container = Depends(get_container)) -> dict[str, Any]:
    return c.samples.get(sample_id)
