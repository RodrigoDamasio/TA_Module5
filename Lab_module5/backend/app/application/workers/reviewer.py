"""Reviewer: checks the latest draft against the task and the notes (structured JSON:
verdict, issues, balance flags — the responsible-AI checklist item)."""

from app.application.prompts import PromptLibrary
from app.application.structured import StructuredCaller
from app.application.tracing import Tracer
from app.domain.ports import LLMClient
from app.domain.schemas import Review, ReviewLLM
from app.domain.transcript import WorkerResult

from .base import WorkerContext, WorkerOutput, trim


def render_review(review: Review) -> str:
    lines = [f"Verdict: {review.verdict.upper()}"]
    if review.issues:
        lines.append("Issues:")
        lines += [f"- ({i.severity}) {i.text}" for i in review.issues]
    else:
        lines.append("Issues: none")
    flags = "; ".join(review.balance_flags) if review.balance_flags else "none"
    lines.append(f"Balance: {flags}")
    return "\n".join(lines)


class Reviewer:
    name = "reviewer"
    title = "Reviewer"
    description = (
        "reviews the latest draft for completeness, clarity, citations and balanced "
        "language; returns approve or revise with issues"
    )
    needs = frozenset({"researcher", "writer"})

    def __init__(self, prompts: PromptLibrary) -> None:
        self._prompts = prompts

    def run(self, task: str, ctx: WorkerContext, llm: LLMClient) -> WorkerOutput:
        draft = ctx.results.get("writer")
        if draft is None:
            return WorkerOutput(
                WorkerResult(self.name, "There is no draft to review yet.", failed=True)
            )
        notes = ctx.results.get("researcher")
        f, budget = ctx.fence, ctx.context_chars // 2
        user = self._prompts.worker_task(
            "reviewer_task",
            user_task=f.wrap(ctx.user_task, "user_task"),
            task=task,
            notes=f.wrap(trim(notes.content, budget), "research_notes") if notes else "(none)",
            draft=f.wrap(trim(draft.content, budget), "draft"),
        )
        caller = StructuredCaller(llm, self._prompts, ctx.model or "")
        result = caller.call(
            self._prompts.worker_system(self.name, ctx.canary),
            user,
            ReviewLLM,
            Review,
            Tracer("worker.reviewer", ctx.run_id),
            max_output_tokens=3072,
        )
        review = result.value or result.last_valid
        assert review is not None  # noqa: S101 — call() raises when nothing was valid
        return WorkerOutput(
            WorkerResult(self.name, render_review(review), review.model_dump(mode="json"))
        )
