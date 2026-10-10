"""Graceful degradation (course §1.4): the service level reported by /health and the UI.

full     Gemini and Wikipedia available
reduced  Wikipedia down: runs work, research is unsourced
minimal  daily LLM quota used up: new runs refused (503); samples and stored runs work
offline  the process is down (seen only by the frontend's failed health check)
"""

from collections.abc import Callable
from typing import Any


class ServiceLevel:
    def __init__(
        self,
        llm_blocked: Callable[[], float | None],  # seconds until the LLM is usable, or None
        knowledge_ok: Callable[[], bool],
    ) -> None:
        self._llm_blocked, self._knowledge_ok = llm_blocked, knowledge_ok

    def current(self) -> dict[str, Any]:
        blocked = self._llm_blocked()
        if blocked is not None:
            return {
                "level": "minimal",
                "retry_after_s": round(blocked),
                "reason": "The daily LLM quota is used up.",
            }
        if not self._knowledge_ok():
            return {
                "level": "reduced",
                "retry_after_s": None,
                "reason": "Wikipedia is unavailable: research is unsourced.",
            }
        return {"level": "full", "retry_after_s": None, "reason": None}
