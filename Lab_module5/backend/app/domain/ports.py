"""Provider-neutral abstractions (LLM types from Labs 2-4) and the ports of this lab."""

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:
    from .run import ResearchRun, RunEvent, RunStatus

FinishReason = Literal["stop", "max_tokens", "safety", "other"]


# ---- LLM (Lab 4 + a per-request model) ------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


@dataclass(frozen=True)
class ToolCall:
    id: str | None
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    call_id: str | None
    name: str
    content: str


@dataclass(frozen=True)
class TokenUsage:
    input: int = 0
    output: int = 0
    thinking: int = 0

    def __add__(self, other: "TokenUsage") -> "TokenUsage":
        return TokenUsage(
            self.input + other.input, self.output + other.output, self.thinking + other.thinking
        )


@dataclass(frozen=True)
class UserMessage:
    text: str


@dataclass(frozen=True)
class AssistantMessage:
    text: str | None
    tool_calls: list[ToolCall]
    raw_turn: Any = None  # provider turn, echoed back unchanged in the next request


@dataclass(frozen=True)
class ToolResultsMessage:
    results: list[ToolResult]


Message = UserMessage | AssistantMessage | ToolResultsMessage


@dataclass(frozen=True)
class LLMRequest:
    system: str
    messages: list[Message]
    tools: list[ToolSpec] = field(default_factory=list)
    response_schema: type[BaseModel] | None = None
    max_output_tokens: int = 2048
    thinking_budget: int | None = None
    model: str | None = None  # model routing: None = the client's default model


@dataclass(frozen=True)
class LLMResponse:
    text: str | None
    tool_calls: list[ToolCall]
    parsed: dict[str, Any] | None
    usage: TokenUsage
    finish_reason: FinishReason
    raw_turn: Any = None
    cached: bool = False  # served by CachingLLMClient (0 real calls)

    def as_message(self) -> AssistantMessage:
        return AssistantMessage(self.text, self.tool_calls, self.raw_turn)


class LLMClient(Protocol):
    def generate(self, request: LLMRequest) -> LLMResponse: ...


# ---- knowledge source (the Researcher's Wikipedia access) ------------------------------


@dataclass(frozen=True)
class SearchHit:
    title: str
    page_id: int


@dataclass(frozen=True)
class SourceDraft:
    """A fetched source before the run numbers it."""

    title: str
    url: str
    extract: str


class KnowledgeSource(Protocol):
    name: str

    def search(self, query: str, limit: int) -> list[SearchHit]: ...

    def fetch(self, hits: list[SearchHit], max_chars: int) -> list[SourceDraft]: ...

    def available(self) -> bool: ...


# ---- memory (extension) ----------------------------------------------------------------


@dataclass(frozen=True)
class Memory:
    run_id: str
    task: str
    summary: str
    source_titles: list[str]
    created_at: str


class MemoryStore(Protocol):
    """Same shape as Lab 3's long-term memory port: recall(query, limit)."""

    def recall(self, query: str, limit: int, exclude_task: str) -> list[Memory]: ...

    def record(self, memory: Memory) -> None: ...


class MemoryRepository(Protocol):
    def record(self, memory: Memory) -> None: ...

    def recent(self, limit: int) -> list[Memory]: ...

    def delete_older_than(self, cutoff_iso: str) -> int: ...


# ---- runs ------------------------------------------------------------------------------


class RunRepository(Protocol):
    def create(self, run: "ResearchRun") -> None: ...

    def save(self, run: "ResearchRun") -> None: ...  # state + pending events, atomically

    def get(self, run_id: str) -> "ResearchRun": ...

    def events_since(self, run_id: str, after_id: int) -> list["RunEvent"]: ...

    def runs_in(self, statuses: set["RunStatus"]) -> list["ResearchRun"]: ...

    def delete_older_than(self, cutoff_iso: str) -> int: ...

    def status_counts(self) -> dict[str, int]: ...

    def recent_durations_ms(self, limit: int) -> list[float]: ...


class JobRunner(Protocol):
    def submit(self, job_id: str) -> None: ...

    def has_capacity(self) -> bool: ...
