"""Structured LLM call (Labs 2-4): lenient schema to the model, strict model locally, one
repair with the exact errors. Every attempt is recorded (raw output, errors)."""

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from app.domain.errors import LLMBadResponse
from app.domain.ports import (
    AssistantMessage,
    LLMClient,
    LLMRequest,
    LLMResponse,
    Message,
    TokenUsage,
    UserMessage,
)
from app.domain.tracing import LLMAttempt

from .prompts import PromptLibrary
from .tracing import Tracer

Check = Callable[[Any], list[str]]  # extra rules on the strict model → error messages


@dataclass
class StructuredResult[T: BaseModel]:
    value: T | None  # None only when the second answer still broke an extra rule
    attempts: list[LLMAttempt]
    usage: TokenUsage = field(default_factory=TokenUsage)
    cached: bool = True  # every call was a cache hit
    rule_errors: list[str] = field(default_factory=list)  # from the last attempt
    last_valid: T | None = None


def _parse(response: LLMResponse) -> dict[str, Any] | None:
    if response.parsed is not None:
        return dict(response.parsed)
    try:
        value = json.loads(response.text or "")
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _validation_messages(err: ValidationError) -> list[str]:
    return [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in err.errors()[:10]]


class StructuredCaller:
    def __init__(self, llm: LLMClient, prompts: PromptLibrary, model: str) -> None:
        self._llm, self._prompts, self.model = llm, prompts, model

    def call[T: BaseModel](
        self,
        system: str,
        user: str,
        lenient: type[BaseModel],
        strict: type[T],
        tracer: Tracer,
        max_output_tokens: int = 1500,
        check: Check | None = None,
    ) -> StructuredResult[T]:
        messages: list[Message] = [UserMessage(user)]
        result: StructuredResult[T] = StructuredResult(None, [])
        for attempt in (1, 2):
            with tracer.span("generate") as s:
                response = self._llm.generate(
                    LLMRequest(
                        system=system,
                        messages=list(messages),
                        response_schema=lenient,
                        max_output_tokens=max_output_tokens,
                        thinking_budget=0,
                        model=self.model,
                    )
                )
                s |= {
                    "model": self.model,
                    "input_tokens": response.usage.input,
                    "output_tokens": response.usage.output + response.usage.thinking,
                    "cached": response.cached,
                    "repair": attempt == 2,
                }
            result.usage = result.usage + response.usage
            result.cached = result.cached and response.cached
            errors, value = self._check(response, strict, check)
            raw = response.text if response.text is not None else json.dumps(response.parsed)
            result.attempts.append(LLMAttempt(raw_output=raw, errors=errors))
            if value is not None:
                result.last_valid = value
            if not errors:
                result.value = value
                return result
            result.rule_errors = errors
            if attempt == 1:
                repair = self._prompts.repair("\n".join(f"- {e}" for e in errors))
                result.attempts[-1].repair_message = repair
                messages = [*messages, AssistantMessage(raw or "", []), UserMessage(repair)]
        if result.last_valid is None:
            raise LLMBadResponse("The model's answer was invalid twice.")
        return result

    @staticmethod
    def _check[T: BaseModel](
        response: LLMResponse, strict: type[T], check: Check | None
    ) -> tuple[list[str], T | None]:
        if response.finish_reason == "max_tokens":
            return ["Your answer was cut off (too long). Return a shorter complete answer."], None
        data = _parse(response)
        if data is None:
            return ["The answer was not a JSON object."], None
        try:
            value = strict.model_validate(data)
        except ValidationError as err:
            return _validation_messages(err), None
        return (check(value) if check else []), value
