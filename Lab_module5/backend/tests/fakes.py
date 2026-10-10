"""Test doubles: a scriptable fake LLM built on the demo client (which already plays every
role from the real prompts). Override any role per test."""

import json
import threading
import time
from collections.abc import Callable
from typing import Any

from app.domain.ports import LLMRequest, LLMResponse, TokenUsage, UserMessage
from app.infrastructure.demo_llm import DemoLLMClient

USAGE = TokenUsage(input=100, output=50)
ROLES = ("supervisor", "researcher", "writer", "reviewer", "fact_checker")
Reply = str | dict | Callable[[str], Any] | Exception


def role_of(request: LLMRequest) -> str:
    if request.response_schema is not None:
        return "reviewer" if request.response_schema.__name__ == "ReviewLLM" else "fact_checker"
    for role in ("Supervisor", "Researcher", "Writer"):
        if f"You are the {role}" in request.system:
            return role.lower()
    return "other"


class FakeLLM(DemoLLMClient):
    """Demo answers by default.

    script:  {role: [reply, ...]} consumed in order (str for text roles, dict for the
             structured ones, a callable prompt → reply, or an exception to raise);
             when a role's list is empty the demo answer is used
    fail:    {role | "any": exception} raised on every call of that role
    delay:   {role: seconds} (to observe parallel workers)
    """

    def __init__(self, **options: Any) -> None:
        super().__init__()
        self.script: dict[str, list[Reply]] = {
            k: list(v) for k, v in options.get("script", {}).items()
        }
        self.fail: dict[str, Exception] = dict(options.get("fail", {}))
        self.delay: dict[str, float] = dict(options.get("delay", {}))
        self.requests: list[tuple[str, LLMRequest]] = []
        self.windows: list[tuple[str, float, float]] = []  # role, start, end
        self._lock = threading.Lock()

    def generate(self, request: LLMRequest) -> LLMResponse:
        role = role_of(request)
        with self._lock:
            self.requests.append((role, request))
            scripted = self.script.get(role)
            item = scripted.pop(0) if scripted else None
        start = time.monotonic()
        if role in self.delay:
            time.sleep(self.delay[role])
        try:
            error = self.fail.get(role) or self.fail.get("any")
            if error is not None:
                raise error
            if isinstance(item, Exception):
                raise item
            prompt = "\n".join(m.text for m in request.messages if isinstance(m, UserMessage))
            value = item(prompt) if callable(item) else item
            if value is None:
                response = super().generate(request)
                return LLMResponse(response.text, [], response.parsed, USAGE, "stop")
            if isinstance(value, dict):
                return LLMResponse(json.dumps(value), [], value, USAGE, "stop")
            return LLMResponse(value, [], None, USAGE, "stop")
        finally:
            with self._lock:
                self.windows.append((role, start, time.monotonic()))

    def calls(self, role: str | None = None) -> int:
        return sum(1 for r, _ in self.requests if role is None or r == role)

    def prompts(self, role: str) -> list[str]:
        return [
            "\n".join(m.text for m in req.messages if isinstance(m, UserMessage))
            for r, req in self.requests
            if r == role
        ]

    def systems(self, role: str) -> list[str]:
        return [req.system for r, req in self.requests if r == role]


RAG_TASK = "Topics: Retrieval-augmented generation; Fine-tuning\nFind facts about RAG and tuning."


def delegate(
    worker: str,
    task: str = RAG_TASK,
    reason: str = "Next.",
) -> str:
    return f"REASON: {reason}\nDELEGATE: {worker}\nTASK: {task}"


def final(text: str = "## Answer\n\nThe answer [1].", reason: str = "Done.") -> str:
    return f"REASON: {reason}\nFINAL:\n{text}"


def review(verdict: str = "approve", issues: list | None = None, flags: list | None = None):
    return {"verdict": verdict, "issues": issues or [], "balance_flags": flags or []}
