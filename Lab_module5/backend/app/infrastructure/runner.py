"""Job runners (from Labs 3-4). ThreadRunner: one background worker + a bounded queue (runs
execute one at a time: the free-tier LLM quota is shared) and a periodic sweeper (approval
expiry, retention). InlineRunner: synchronous, for tests and the CLI."""

import logging
import queue
import threading
from collections.abc import Callable

from app.domain.errors import QueueFull

logger = logging.getLogger("app.runner")


class InlineRunner:
    def __init__(self, run: Callable[[str], None]) -> None:
        self._run = run

    def submit(self, job_id: str) -> None:
        self._run(job_id)

    def has_capacity(self) -> bool:
        return True

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


class ThreadRunner:
    def __init__(
        self,
        run: Callable[[str], None],
        max_queued: int,
        sweep: Callable[[], object] | None = None,
        sweep_every_s: float = 600,
    ) -> None:
        self._run = run
        self._queue: queue.Queue[str | None] = queue.Queue(maxsize=max_queued)
        self._sweep, self._every = sweep, sweep_every_s
        self._stop = threading.Event()

    def submit(self, job_id: str) -> None:
        try:
            self._queue.put_nowait(job_id)
        except queue.Full as err:
            raise QueueFull() from err

    def has_capacity(self) -> bool:
        return not self._queue.full()

    def start(self) -> None:
        threading.Thread(target=self._work, name="job-runner", daemon=True).start()
        if self._sweep is not None:
            threading.Thread(target=self._sweeper, name="sweeper", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self._queue.put_nowait(None)  # wake the worker so it can exit
        except queue.Full:
            pass

    def _work(self) -> None:
        while not self._stop.is_set():
            job_id = self._queue.get()
            if job_id is None:
                return
            try:
                self._run(job_id)
            except Exception:  # the job service records failures; never kill the worker
                logger.exception("runner crashed on %s", job_id)

    def _sweeper(self) -> None:
        while not self._stop.wait(self._every):
            try:
                assert self._sweep is not None  # noqa: S101
                self._sweep()
            except Exception:
                logger.exception("sweep failed")
