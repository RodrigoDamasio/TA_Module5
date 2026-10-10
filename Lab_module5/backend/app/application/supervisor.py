"""The supervisor loop (the lab's core): each iteration the Supervisor decides — via the
DELEGATE/TASK/FINAL protocol — which worker acts next, or writes the final answer.

Guards: one repair call for an invalid reply; an iteration limit and a per-run call budget,
both ending in a forced FINAL call; and a deterministic fallback (latest draft, then the
research notes) when even that fails or the quota runs out. The loop can never spin."""

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace

from app.domain.errors import (
    BudgetExceeded,
    CanaryLeak,
    LLMBadResponse,
    LLMError,
    LLMRequestRejected,
    ProtocolError,
)
from app.domain.ports import (
    AssistantMessage,
    LLMClient,
    LLMRequest,
    MemoryStore,
    RunRepository,
    SourceDraft,
    UserMessage,
)
from app.domain.protocol import parse_decision
from app.domain.run import ResearchRun, RunStatus
from app.domain.transcript import CallMeta, Decision, Delegation, Source, WorkerResult

from .budget import CallBudget
from .context import (
    has_sources_section,
    memory_block,
    source_list,
    sources_section,
    transcript_view,
)
from .memory import memory_from_run
from .prompts import PromptLibrary
from .security import DataFence, OutputValidator, canary_for
from .workers.base import (
    StepCounter,
    WorkerContext,
    WorkerOutput,
    WorkerRegistry,
    clean_citations,
)

logger = logging.getLogger("app.supervisor")


@dataclass(frozen=True)
class LoopSettings:
    supervisor_model: str | None = None
    worker_model: str | None = None
    max_parallel: int = 2
    task_max_chars: int = 1000
    revision_iterations: int = 2
    approval_timeout_min: int = 30
    supervisor_context_tokens: int = 6000
    worker_context_chars: int = 17_500
    memory_limit: int = 3


class Supervisor:
    def __init__(
        self,
        runs: RunRepository,
        llm_for: Callable[[CallBudget], LLMClient],  # the per-run client over a budget
        registry: WorkerRegistry,
        prompts: PromptLibrary,
        secret: bytes,
        settings: LoopSettings,
        memory: MemoryStore | None = None,
    ) -> None:
        self.runs, self._llm_for, self.registry = runs, llm_for, registry
        self.prompts, self._secret, self.s, self.memory = prompts, secret, settings, memory
        self.canary = canary_for(secret)
        self.output = OutputValidator(self.canary)

    # ---- entry point (runner thread) -------------------------------------------------------

    def run(self, run_id: str) -> None:
        run = self.runs.get(run_id)
        if run.status is not RunStatus.QUEUED:
            return  # cancelled or already handled
        lock = threading.Lock()
        budget = CallBudget(2 * max(run.iteration_limit - run.iteration, 1) + 3)
        llm = self._llm_for(budget)
        fence = DataFence(self._secret, run.task)
        run.models = {
            "supervisor": self.s.supervisor_model or "",
            "workers": self.s.worker_model or "",
        }
        run.prompt_version = self.prompts.version
        run.start()
        self._save(run, lock)
        try:
            if run.iteration == 0 and run.use_memory and self.memory and not run.memories:
                run.use_memories(self.memory.recall(run.task, self.s.memory_limit, run.task))
                self._save(run, lock)
            self._loop(run, llm, budget, fence, lock)
        except (LLMError, BudgetExceeded) as err:
            self._degrade(run, _why(err))
        except CanaryLeak as err:
            run.add_flag("canary_leak")
            if not run.done:
                run.fail(str(err))
        except Exception:  # never kill the runner; the run records the failure
            logger.exception("run %s crashed", run.id)
            if not run.done:
                run.fail("Unexpected error while running the agents.")
        self._save(run, lock)
        if run.status is RunStatus.COMPLETED:
            self.remember(run)
        logger.info(
            "run=%s status=%s iterations=%d calls=%d cached=%d forced=%s flags=%s",
            run.id,
            run.status.value,
            run.iteration,
            run.llm_calls,
            run.cached_calls,
            run.forced,
            ",".join(run.flags),
        )

    def remember(self, run: ResearchRun) -> None:
        if self.memory is not None and run.use_memory and run.final_output:
            self.memory.record(memory_from_run(run))

    # ---- the loop ----------------------------------------------------------------------

    def _loop(
        self,
        run: ResearchRun,
        llm: LLMClient,
        budget: CallBudget,
        fence: DataFence,
        lock: threading.Lock,
    ) -> None:
        while run.status is RunStatus.RUNNING:
            if run.iteration >= run.iteration_limit:
                return self._force(run, llm, fence, lock, "the iteration limit was reached")
            if budget.remaining() <= 1:
                return self._force(run, llm, fence, lock, "the LLM call budget was reached")
            run.agent_started("supervisor", None)
            self._save(run, lock)
            decision, meta = self._decide(run, llm, budget, fence)
            if decision is None:
                run.notice("The Supervisor's reply broke the protocol twice.", "protocol", meta)
                return self._force(run, llm, fence, lock, "the Supervisor's replies were invalid")
            run.record_decision(decision, meta)
            self._save(run, lock)
            if decision.final is not None:
                self._propose(run, decision.final, forced=False, degraded=False)
                return None
            self._run_workers(run, decision.delegations, llm, fence, lock)
        return None

    def _system(self) -> str:
        parallel = (
            f"You may send up to {self.s.max_parallel} DELEGATE/TASK pairs in one reply, to "
            "different workers, when their work is independent (for example reviewer and "
            "fact_checker on the same draft)."
            if self.s.max_parallel > 1
            else ""
        )
        hint = " (and fact_checker)" if "fact_checker" in self.registry.names else ""
        return self.prompts.supervisor_system(self.registry.describe(), parallel, hint, self.canary)

    def _task_prompt(self, run: ResearchRun, fence: DataFence, forced: bool = False) -> str:
        left = 0 if forced else max(0, run.iteration_limit - run.iteration)
        return self.prompts.supervisor_task(
            user_task=fence.wrap(run.task, "user_task"),
            memories=memory_block(run, fence),
            sources=source_list(run),
            transcript=transcript_view(run, fence, self.s.supervisor_context_tokens),
            iterations_left=left,
            last_hint=" This is your last one: reply with FINAL." if left == 1 else "",
        )

    def _request(self, messages: list) -> LLMRequest:
        return LLMRequest(
            system=self._system(),
            messages=messages,
            max_output_tokens=4096,
            thinking_budget=0,
            model=self.s.supervisor_model,
        )

    def _decide(
        self, run: ResearchRun, llm: LLMClient, budget: CallBudget, fence: DataFence
    ) -> tuple[Decision | None, CallMeta]:
        """One Supervisor call + parse; on a protocol error, ONE repair call."""
        counter = StepCounter(llm, self.output)
        user = UserMessage(self._task_prompt(run, fence))
        response = counter.generate(self._request([user]))
        reply = response.text or ""
        try:
            return self._parse(reply, cut=response.finish_reason == "max_tokens"), counter.meta(
                self.s.supervisor_model
            )
        except ProtocolError as err:
            if budget.remaining() <= 1:  # keep the last call for the forced completion
                return None, counter.meta(self.s.supervisor_model)
            logger.info("run=%s protocol error, repairing", run.id)
            repair = UserMessage(self.prompts.supervisor_repair(str(err)))
            again = counter.generate(self._request([user, AssistantMessage(reply, []), repair]))
            try:
                cut = again.finish_reason == "max_tokens"
                decision = replace(self._parse(again.text or "", cut=cut), repaired=True)
            except ProtocolError:
                return None, counter.meta(self.s.supervisor_model)
            return decision, counter.meta(self.s.supervisor_model)

    def _parse(
        self, reply: str, workers: frozenset[str] | None = None, cut: bool = False
    ) -> Decision:
        if cut:
            raise ProtocolError("Your reply was cut off because it was too long; keep it shorter.")
        return parse_decision(
            reply,
            self.registry.names if workers is None else workers,
            self.s.max_parallel,
            self.s.task_max_chars,
        )

    # ---- workers -------------------------------------------------------------------------

    def _run_workers(
        self,
        run: ResearchRun,
        delegations: tuple[Delegation, ...],
        llm: LLMClient,
        fence: DataFence,
        lock: threading.Lock,
    ) -> None:
        results = {
            name: r for name in self.registry.names if (r := run.latest_result(name)) is not None
        }
        snapshot = list(run.sources)

        def register(drafts: list[SourceDraft]) -> list[Source]:
            with lock:
                return run.add_sources(drafts)

        def one(d: Delegation) -> tuple[Delegation, WorkerOutput, CallMeta, bool]:
            previous = run.previous_result(d)
            if previous is not None:  # the same TASK again: reuse, 0 calls
                return d, WorkerOutput(previous), CallMeta(self.s.worker_model), True
            worker = self.registry.get(d.worker)
            with lock:
                run.agent_started(d.worker, d.task)
                self._save_locked(run)
            ctx = WorkerContext(
                run.id,
                run.task,
                {k: v for k, v in results.items() if k in worker.needs},
                list(snapshot),
                fence,
                register,
                self.s.worker_model,
                self.canary,
                self.s.worker_context_chars,
            )
            counter = StepCounter(llm, self.output)
            try:
                out = worker.run(d.task, ctx, counter)
            except (LLMBadResponse, LLMRequestRejected) as err:
                logger.info("run=%s worker=%s failed: %s", run.id, d.worker, type(err).__name__)
                out = WorkerOutput(WorkerResult(d.worker, f"Worker failed: {err}", failed=True))
            return d, out, counter.meta(self.s.worker_model), False

        if len(delegations) == 1:
            outcomes = [one(delegations[0])]
        else:  # extension: parallel workers (same context snapshot, results in order)
            with ThreadPoolExecutor(len(delegations), thread_name_prefix="worker") as pool:
                futures = [pool.submit(one, d) for d in delegations]
                outcomes = [f.result() for f in futures]
        for d, out, meta, repeated in outcomes:
            content, redacted = self.output.clean(out.result.content)
            with lock:
                if repeated:
                    run.notice(
                        f"Repeated delegation to {d.worker}: the earlier result was "
                        "reused (0 calls).",
                        "repeated",
                    )
                for text, flag in out.notices:
                    run.notice(text, flag)
                if redacted:
                    run.notice("Sensitive-looking data was redacted from a result.", "redacted")
                run.record_result(d.task, replace(out.result, content=content), meta)
                self._save_locked(run)

    # ---- completion ----------------------------------------------------------------------

    def _force(
        self, run: ResearchRun, llm: LLMClient, fence: DataFence, lock: threading.Lock, why: str
    ) -> None:
        """One call that may ONLY answer FINAL; anything else → the fallback chain."""
        run.notice(f"Forced completion: {why}.", "forced")
        run.agent_started("supervisor", None)
        self._save(run, lock)
        counter = StepCounter(llm, self.output)
        user = (
            self._task_prompt(run, fence, forced=True) + "\n\n" + self.prompts.supervisor_forced()
        )
        response = counter.generate(self._request([UserMessage(user)]))
        try:
            cut = response.finish_reason == "max_tokens"
            decision = replace(self._parse(response.text or "", frozenset(), cut), forced=True)
        except ProtocolError:
            run.notice(
                "The forced reply was not a valid FINAL.",
                "protocol",
                counter.meta(self.s.supervisor_model),
            )
            return self._degrade(run, f"{why} and the forced answer was invalid")
        run.record_decision(decision, counter.meta(self.s.supervisor_model), count=False)
        self._propose(run, decision.final or "", forced=True, degraded=False)
        return None

    def _propose(self, run: ResearchRun, text: str, *, forced: bool, degraded: bool) -> None:
        text, _, unknown = clean_citations(text, {s.n for s in run.sources})
        if unknown:
            run.notice(
                f"Removed {len(unknown)} citation(s) to unknown sources from the final answer.",
                "unknown_citation",
            )
        text, redacted = self.output.clean(text)
        if redacted:
            run.notice("Sensitive-looking data was redacted from the answer.", "redacted")
        if not has_sources_section(text) and (section := sources_section(run, text)):
            text = f"{text.rstrip()}\n\n{section}"
        run.propose_final(
            text, forced=forced, degraded=degraded, approval_timeout_min=self.s.approval_timeout_min
        )

    def _degrade(self, run: ResearchRun, why: str) -> None:
        """Fallback chain (course §1.3): latest Writer draft → Researcher notes → fail."""
        if run.status is not RunStatus.RUNNING:
            return
        draft, notes = run.latest_result("writer"), run.latest_result("researcher")
        if draft is not None:
            body = draft.content
        elif notes is not None:
            body = "## Research notes\n\n" + notes.content
        else:
            run.fail(f"No result could be produced: {why}.")
            return
        run.notice(f"Answer assembled automatically: {why}.", "degraded")
        note = (
            f"> **Note:** this answer was assembled automatically because {why}. "
            "It was not finalized by the Supervisor and may be incomplete.\n\n"
        )
        self._propose(run, note + body, forced=True, degraded=True)

    # ---- persistence -----------------------------------------------------------------------

    def _save(self, run: ResearchRun, lock: threading.Lock) -> None:
        with lock:
            self._save_locked(run)

    def _save_locked(self, run: ResearchRun) -> None:
        self.runs.save(run)


def _why(err: Exception) -> str:
    if isinstance(err, BudgetExceeded):
        return "the LLM call budget was used up"
    name = type(err).__name__
    if name == "LLMQuotaExceeded":
        return "the LLM quota was reached"
    if name in ("LLMUnavailable", "LLMOverloaded", "LLMTimeout"):
        return "the LLM service was unavailable"
    return "the LLM service refused the request"
