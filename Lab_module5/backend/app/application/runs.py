"""RunService: the use cases behind the HTTP API — submit a task, read it, approve or reject
its answer, and the housekeeping (approval expiry, retention, restart recovery).
Every check that can reject a request for free runs before anything is queued."""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.domain.errors import InputTooLarge, InvalidField, QueueFull
from app.domain.ports import JobRunner, MemoryRepository, RunRepository
from app.domain.run import ResearchRun, RunStatus

from .security import InputValidator
from .supervisor import Supervisor

logger = logging.getLogger("app.runs")


@dataclass(frozen=True)
class RunLimits:
    default_max_iterations: int = 5
    max_iterations_limit: int = 8
    task_min_chars: int = 10
    task_max_chars: int = 2000
    revision_iterations: int = 2
    retention_days: int = 30
    memory_enabled: bool = True


class RunService:
    def __init__(
        self,
        runs: RunRepository,
        runner: JobRunner,
        supervisor: Supervisor,
        limits: RunLimits,
        ensure_llm_available: Callable[[], None] = lambda: None,
        memories: MemoryRepository | None = None,
    ) -> None:
        self.runs, self.runner, self.supervisor, self.limits = runs, runner, supervisor, limits
        self._ensure_llm = ensure_llm_available  # raises LLMQuotaExceeded (service level)
        self._memories = memories
        self._input = InputValidator()

    # ---- submit ----------------------------------------------------------------------------

    def check_input(self, task: str, max_iterations: int | None) -> tuple[str, int, list[str]]:
        """Free checks: (sanitized task, iterations, injection pattern names)."""
        clean = self._input.sanitize(task)
        if len(clean) > self.limits.task_max_chars:
            raise InputTooLarge(
                f"The task has {len(clean)} characters; the limit is {self.limits.task_max_chars}."
            )
        if len(clean) < self.limits.task_min_chars:
            raise InvalidField(
                f"Describe the task in at least {self.limits.task_min_chars} characters.", "#/task"
            )
        iterations = max_iterations or self.limits.default_max_iterations
        if not 1 <= iterations <= self.limits.max_iterations_limit:
            raise InvalidField(
                f"Must be between 1 and {self.limits.max_iterations_limit}.", "#/max_iterations"
            )
        return clean, iterations, self._input.check(clean)

    def submit(
        self, task: str, max_iterations: int | None, require_approval: bool, use_memory: bool
    ) -> ResearchRun:
        clean, iterations, patterns = self.check_input(task, max_iterations)
        self._ensure_llm()
        if not self.runner.has_capacity():
            raise QueueFull()
        run = ResearchRun.create(
            clean, iterations, require_approval, use_memory and self.limits.memory_enabled
        )
        if patterns:
            run.notice(
                "The task contains phrases often used in prompt-injection attempts "
                f"({', '.join(patterns)}); they are treated as data, not instructions.",
                "possible_injection",
            )
            logger.warning("run=%s possible_injection patterns=%s", run.id, ",".join(patterns))
        self.runs.create(run)
        self._queue(run)
        # Never log the task text: ids, sizes and flags only.
        logger.info(
            "run=%s submitted chars=%d iterations=%d approval=%s memory=%s",
            run.id,
            len(clean),
            iterations,
            require_approval,
            run.use_memory,
        )
        return self.runs.get(run.id)

    def _queue(self, run: ResearchRun) -> None:
        try:
            self.runner.submit(run.id)
        except QueueFull:
            # Rare race (the queue filled since the capacity check): never leave it queued.
            run = self.runs.get(run.id)
            run.fail("The server was too busy to start this run; please retry.")
            self.runs.save(run)
            raise

    # ---- read ------------------------------------------------------------------------------

    def get(self, run_id: str) -> ResearchRun:
        return self.runs.get(run_id)

    def wait(self, run_id: str, timeout_s: float, poll_s: float = 0.2) -> ResearchRun:
        deadline = time.monotonic() + timeout_s
        run = self.runs.get(run_id)
        while not run.done and time.monotonic() < deadline:
            time.sleep(poll_s)
            run = self.runs.get(run_id)
        return run

    # ---- human approval (extension) ------------------------------------------------------

    def approve(self, run_id: str) -> ResearchRun:
        run = self.runs.get(run_id)
        run.approve()
        self.runs.save(run)
        self.supervisor.remember(run)
        return run

    def reject(self, run_id: str, feedback: str | None) -> ResearchRun:
        run = self.runs.get(run_id)
        revising = bool(feedback) and run.revisions == 0
        if run.status is RunStatus.AWAITING_APPROVAL and revising:
            if not self.runner.has_capacity():
                raise QueueFull()
        if run.reject(feedback, self.limits.revision_iterations):
            self.runs.save(run)
            self._queue(run)
        else:
            self.runs.save(run)
        return self.runs.get(run_id)

    # ---- housekeeping ----------------------------------------------------------------------

    def recover(self) -> int:
        """Runs left queued or running by a restart cannot resume: mark them failed."""
        stuck = self.runs.runs_in({RunStatus.QUEUED, RunStatus.RUNNING})
        for run in stuck:
            run.fail("Interrupted by a server restart; please submit the task again.")
            self.runs.save(run)
        return len(stuck)

    def sweep(self, now: datetime | None = None) -> dict[str, int]:
        now = now or datetime.now(UTC)
        expired = 0
        for run in self.runs.runs_in({RunStatus.AWAITING_APPROVAL}):
            if run.approval_expired(now):
                run.cancel("The approval request expired.")
                self.runs.save(run)
                expired += 1
        cutoff = (now - timedelta(days=self.limits.retention_days)).isoformat(timespec="seconds")
        deleted = self.runs.delete_older_than(cutoff)
        forgotten = self._memories.delete_older_than(cutoff) if self._memories else 0
        if expired or deleted or forgotten:
            logger.info("sweep expired=%d deleted=%d forgotten=%d", expired, deleted, forgotten)
        return {"expired": expired, "deleted": deleted, "forgotten": forgotten}
