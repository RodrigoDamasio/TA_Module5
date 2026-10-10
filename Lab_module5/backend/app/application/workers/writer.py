"""Writer: turns the research notes into the answer; on a revision it also sees its previous
draft and the latest review and fact check."""

from app.application.prompts import PromptLibrary
from app.domain.ports import LLMClient, LLMRequest, UserMessage
from app.domain.transcript import WorkerResult

from .base import WorkerContext, WorkerOutput, clean_citations, text_of, trim, truncation


class Writer:
    name = "writer"
    title = "Writer"
    description = (
        "writes or revises the answer from the research notes (and from the latest review "
        "and fact check, if any), keeping the [n] citations"
    )
    needs = frozenset({"researcher", "writer", "reviewer", "fact_checker"})

    def __init__(self, prompts: PromptLibrary) -> None:
        self._prompts = prompts

    def run(self, task: str, ctx: WorkerContext, llm: LLMClient) -> WorkerOutput:
        f, budget = ctx.fence, ctx.context_chars // 3

        def block(worker: str, kind: str) -> str:
            r = ctx.results.get(worker)
            return f.wrap(trim(r.content, budget), kind) if r else "(none)"

        user = self._prompts.worker_task(
            "writer_task",
            user_task=f.wrap(ctx.user_task, "user_task"),
            task=task,
            notes=block("researcher", "research_notes"),
            review=block("reviewer", "review"),
            fact_check=block("fact_checker", "fact_check"),
            previous_draft=block("writer", "previous_draft"),
        )
        response = llm.generate(
            LLMRequest(
                system=self._prompts.worker_system(self.name, ctx.canary),
                messages=[UserMessage(user)],
                max_output_tokens=4096,
                thinking_budget=0,
                model=ctx.model,
            )
        )
        draft, cited, unknown = clean_citations(text_of(response), {s.n for s in ctx.sources})
        notices = truncation(response, self.name)
        if unknown:
            notices.append(
                (f"Removed {len(unknown)} citation(s) to unknown sources.", "unknown_citation")
            )
        return WorkerOutput(WorkerResult(self.name, draft, {}, cited), notices)
