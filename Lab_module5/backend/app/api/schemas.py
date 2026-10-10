"""Request models and the RunView (the response shape of every run endpoint)."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.application.stats import Pricing
from app.domain.run import ResearchRun
from app.domain.transcript import entry_to_dict

MAX_TASK_FIELD_CHARS = 20_000  # hard cap before sanitizing; the real limit is TASK_MAX_CHARS


class RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(
        min_length=1,
        max_length=MAX_TASK_FIELD_CHARS,
        description="The research task, 10–2,000 characters.",
    )
    max_iterations: int | None = Field(
        None, description="Supervisor decisions before forced completion (1–8, default 5)."
    )
    require_approval: bool = Field(False, description="Pause for human approval before FINAL.")
    use_memory: bool = Field(True, description="Let the Supervisor recall earlier tasks.")


class RejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    feedback: str | None = Field(None, max_length=1000)


class Accepted(BaseModel):
    run_id: str
    status: str
    status_url: str
    events_url: str


def run_view(
    run: ResearchRun, pricing: Pricing, demo: bool, sample: bool = False
) -> dict[str, Any]:
    """The lab's response, plus everything the UI shows. Source extracts are never exposed."""
    return {
        "run_id": run.id,
        "status": run.status.value,
        "task": run.task,
        "max_iterations": run.max_iterations,
        "iteration": run.iteration,
        "iteration_limit": run.iteration_limit,
        "final_output": run.final_output,
        "sources": [{"n": s.n, "title": s.title, "url": s.url} for s in run.sources],
        "forced": run.forced,
        "degraded": run.degraded,
        "flags": run.flags,
        "transcript": [entry_to_dict(e) for e in run.transcript],
        "approval": {
            "required": run.require_approval,
            "draft": run.draft,
            "expires_at": run.approval_expires_at,
            "revisions": run.revisions,
        },
        "memory_used": [{"run_id": m["run_id"], "task": m["task"]} for m in run.memories],
        "error": run.error,
        "meta": {
            "generated_by": "demo mode (no LLM)" if demo else "AI (Gemini)",
            "models": run.models,
            "prompt_version": run.prompt_version,
            "llm_calls": run.llm_calls,
            "cached_calls": run.cached_calls,
            "tokens": {
                "input": run.tokens.input,
                "output": run.tokens.output + run.tokens.thinking,
            },
            "est_cost_usd": pricing.cost(run.tokens),
            "created_at": run.created_at,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "duration_ms": run.duration_ms,
        },
        "sample": sample,
    }
