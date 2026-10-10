"""Gemini adapter: maps the provider-neutral LLMClient port onto the google-genai SDK."""

import logging
import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from google import genai
from google.genai import errors, types
from pydantic import BaseModel

from app.domain.errors import (
    LLMOverloaded,
    LLMQuotaExceeded,
    LLMRequestRejected,
    LLMTimeout,
    LLMUnavailable,
)
from app.domain.ports import (
    AssistantMessage,
    FinishReason,
    LLMRequest,
    LLMResponse,
    Message,
    TokenUsage,
    ToolCall,
    ToolResultsMessage,
    UserMessage,
)

logger = logging.getLogger(__name__)
_PACIFIC = ZoneInfo("America/Los_Angeles")

_FINISH: dict[Any, FinishReason] = {
    types.FinishReason.STOP: "stop",
    types.FinishReason.MAX_TOKENS: "max_tokens",
}
_BLOCKED = {
    types.FinishReason.SAFETY,
    types.FinishReason.PROHIBITED_CONTENT,
    types.FinishReason.BLOCKLIST,
    types.FinishReason.SPII,
}


def thinking_config(model: str, budget: int | None) -> types.ThinkingConfig | None:
    """Gemini 2.x takes a token budget; newer families take a level."""
    if budget is None:
        return None
    if model.startswith("gemini-2."):
        if "pro" in model:
            budget = max(budget, 128)  # Pro models cannot turn thinking off
        return types.ThinkingConfig(thinking_budget=budget)
    # LOW is the lowest level every 3.x flash model accepts (gemini-3.8-flash rejects MINIMAL).
    level = types.ThinkingLevel.LOW if budget <= 1024 else types.ThinkingLevel.HIGH
    return types.ThinkingConfig(thinking_level=level)


def to_contents(messages: list[Message]) -> list[types.Content]:
    contents: list[types.Content] = []
    for m in messages:
        if isinstance(m, UserMessage):
            contents.append(types.Content(role="user", parts=[types.Part(text=m.text)]))
        elif isinstance(m, AssistantMessage):
            if m.raw_turn is not None:
                contents.append(m.raw_turn)
                continue
            # No provider turn (e.g. replayed from the response cache): rebuild it,
            # including function_call parts so the following tool results stay valid.
            parts = [types.Part(text=m.text)] if m.text else []
            parts += [
                types.Part(function_call=types.FunctionCall(id=c.id, name=c.name, args=c.args))
                for c in m.tool_calls
            ]
            contents.append(types.Content(role="model", parts=parts or [types.Part(text="")]))
        elif isinstance(m, ToolResultsMessage):
            contents.append(
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_function_response(
                            name=r.name, response={"result": r.content}
                        )
                        for r in m.results
                    ],
                )
            )
    return contents


def build_config(model: str, req: LLMRequest) -> types.GenerateContentConfig:
    tools = None
    if req.tools:
        tools = [
            types.Tool(
                function_declarations=[
                    types.FunctionDeclaration(
                        name=t.name, description=t.description, parameters_json_schema=t.parameters
                    )
                    for t in req.tools
                ]
            )
        ]
    return types.GenerateContentConfig(
        system_instruction=req.system,
        max_output_tokens=req.max_output_tokens,
        temperature=0.2,  # stable decisions and protocol replies
        # We run the tool loop ourselves (budget, trimming, round caps):
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        tools=tools,
        response_mime_type="application/json" if req.response_schema else None,
        response_schema=req.response_schema,
        thinking_config=thinking_config(model, req.thinking_budget),
    )


def to_response(r: types.GenerateContentResponse) -> LLMResponse:
    if not r.candidates:
        reason = r.prompt_feedback.block_reason if r.prompt_feedback else None
        raise LLMRequestRejected(None, f"The model returned no answer (blocked: {reason}).")
    candidate = r.candidates[0]
    if candidate.finish_reason in _BLOCKED:
        raise LLMRequestRejected(None, "The model refused to analyze this content.")
    parts = (candidate.content.parts if candidate.content else None) or []
    text = "".join(p.text for p in parts if p.text and not p.thought) or None
    calls = [ToolCall(fc.id, fc.name or "", dict(fc.args or {})) for fc in (r.function_calls or [])]
    parsed: Any = r.parsed
    if isinstance(parsed, BaseModel):
        try:
            parsed = parsed.model_dump(mode="json")
        except Exception:  # noqa: BLE001 — SDK can hand back a bare BaseModel; use the text
            parsed = None
    usage = r.usage_metadata
    return LLMResponse(
        text=text,
        tool_calls=calls,
        parsed=parsed if isinstance(parsed, dict) else None,
        usage=TokenUsage(
            input=(usage.prompt_token_count or 0) if usage else 0,
            output=(usage.candidates_token_count or 0) if usage else 0,
            thinking=(usage.thoughts_token_count or 0) if usage else 0,
        ),
        finish_reason=_FINISH.get(candidate.finish_reason, "other"),
        raw_turn=candidate.content,
    )


def seconds_until_daily_reset(now: datetime | None = None) -> float:
    """Gemini's daily quotas reset at midnight Pacific time."""
    now = now or datetime.now(_PACIFIC)
    tomorrow = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return (tomorrow - now).total_seconds()


def quota_error(err: errors.APIError, now: datetime | None = None) -> LLMQuotaExceeded:
    """Parse Gemini's 429 body: RetryInfo.retryDelay + QuotaFailure ids (minute vs day).
    Anything unrecognized is treated as the daily quota — the safe choice is to stop."""
    body = err.details if isinstance(err.details, dict) else {}
    details = body.get("error", {}).get("details", []) if isinstance(body, dict) else []
    retry_after, quota_ids = 0.0, ""
    for d in details if isinstance(details, list) else []:
        kind = d.get("@type", "")
        if kind.endswith("RetryInfo"):
            match = re.match(r"([\d.]+)s", str(d.get("retryDelay", "")))
            retry_after = float(match.group(1)) if match else 0.0
        elif kind.endswith("QuotaFailure"):
            quota_ids += " ".join(
                f"{v.get('quotaId', '')} {v.get('quotaMetric', '')}"
                for v in d.get("violations", [])
            )
    per_minute = "PerMinute" in quota_ids and "PerDay" not in quota_ids
    scope = "minute" if per_minute else "day"
    if scope == "day":
        # The retryDelay sent with a daily-quota 429 is only seconds long; retrying then just
        # hits the limit again. Wait for the real reset instead.
        retry_after = seconds_until_daily_reset(now)
    logger.warning(
        "Gemini 429: scope=%s retry_after=%.0fs quota=%s",
        scope,
        retry_after,
        quota_ids.strip() or "(none reported)",
    )
    return LLMQuotaExceeded(scope, retry_after)


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout_s: int,
        on_raw: Callable[[types.GenerateContentResponse], None] | None = None,
    ) -> None:
        self._model = model
        self._on_raw = on_raw  # used to record test cassettes
        self._client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=timeout_s * 1000,
                # The SDK retries (incl. 429) up to 5 times by default; that would spend
                # quota and hide errors. Our RetryingLLMClient decides instead.
                retry_options=types.HttpRetryOptions(attempts=1),
            ),
        )

    def generate(self, request: LLMRequest) -> LLMResponse:
        model = request.model or self._model  # model routing (per agent role)
        try:
            response = self._client.models.generate_content(
                model=model,
                contents=to_contents(request.messages),
                config=build_config(model, request),
            )
        except errors.ClientError as err:
            if err.code == 429:
                raise quota_error(err) from err
            raise LLMRequestRejected(
                err.code, f"The LLM provider rejected the request ({err.code})."
            ) from err
        except errors.ServerError as err:
            raise LLMOverloaded(f"The LLM provider is overloaded ({err.code}).") from err
        except httpx.TimeoutException as err:
            raise LLMTimeout("The LLM provider did not answer in time.") from err
        except httpx.TransportError as err:
            raise LLMUnavailable("Could not reach the LLM provider.") from err
        if self._on_raw is not None:
            self._on_raw(response)
        return to_response(response)
