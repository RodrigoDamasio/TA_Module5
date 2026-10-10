"""CachingLLMClient: an identical request returns the stored response — 0 real calls.
Prompts are deterministic (versioned files + run inputs; nonces and the canary are derived,
not random), so re-running a task, a sample, or an evaluation case costs nothing."""

import hashlib
import json
from typing import Protocol

from app.domain.ports import (
    AssistantMessage,
    LLMClient,
    LLMRequest,
    LLMResponse,
    TokenUsage,
    ToolCall,
    ToolResultsMessage,
    UserMessage,
)


class ResponseStore(Protocol):
    def get(self, key: str) -> dict | None: ...

    def put(self, key: str, value: dict) -> None: ...


def _message(m) -> dict:
    if isinstance(m, UserMessage):
        return {"user": m.text}
    if isinstance(m, AssistantMessage):
        return {"assistant": m.text, "calls": [[c.name, c.args] for c in m.tool_calls]}
    if isinstance(m, ToolResultsMessage):
        return {"results": [[r.name, r.content] for r in m.results]}
    raise TypeError(type(m))


def request_key(model: str, request: LLMRequest) -> str:
    schema = request.response_schema
    payload = {
        "model": request.model or model,
        "system": request.system,
        "messages": [_message(m) for m in request.messages],
        "tools": [[t.name, t.parameters] for t in request.tools],
        "schema": [schema.__name__, schema.model_json_schema()] if schema else None,
        "max_output_tokens": request.max_output_tokens,
        "thinking": request.thinking_budget,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class CachingLLMClient:
    def __init__(self, inner: LLMClient, store: ResponseStore, model: str) -> None:
        self._inner, self._store, self._model = inner, store, model

    def generate(self, request: LLMRequest) -> LLMResponse:
        key = request_key(self._model, request)
        if (hit := self._store.get(key)) is not None:
            return LLMResponse(
                text=hit["text"],
                tool_calls=[ToolCall(c["id"], c["name"], c["args"]) for c in hit["tool_calls"]],
                parsed=hit["parsed"],
                usage=TokenUsage(**hit["usage"]),
                finish_reason=hit["finish_reason"],
                raw_turn=None,  # the adapter rebuilds tool-call turns from tool_calls
                cached=True,
            )
        response = self._inner.generate(request)
        if response.finish_reason == "stop":  # never cache truncated or blocked answers
            self._store.put(
                key,
                {
                    "text": response.text,
                    "tool_calls": [
                        {"id": c.id, "name": c.name, "args": c.args} for c in response.tool_calls
                    ],
                    "parsed": response.parsed,
                    "usage": {
                        "input": response.usage.input,
                        "output": response.usage.output,
                        "thinking": response.usage.thinking,
                    },
                    "finish_reason": response.finish_reason,
                },
            )
        return response
