"""Named failures. Mapped to RFC 9457 problems only in app.api."""

from typing import Literal


class DomainError(Exception):
    """Base class for every expected failure."""


# ---- input -------------------------------------------------------------------------


class InvalidField(DomainError):
    """Invalid input that maps to one request field (JSON Pointer)."""

    def __init__(self, message: str, pointer: str) -> None:
        super().__init__(message)
        self.pointer = pointer


class InputTooLarge(DomainError):
    pass


class RunNotFound(DomainError):
    def __init__(self, run_id: str) -> None:
        super().__init__(f"No run with id '{run_id}'.")
        self.run_id = run_id


class SampleNotFound(DomainError):
    def __init__(self, sample_id: str) -> None:
        super().__init__(f"No sample with id '{sample_id}'.")


class InvalidTransition(DomainError):
    def __init__(self, current: str, action: str) -> None:
        super().__init__(f"Cannot {action} a run that is '{current}'.")
        self.current = current


class QueueFull(DomainError):
    def __init__(self) -> None:
        super().__init__("The server is busy: too many runs are waiting. Try again shortly.")


# ---- the supervisor loop -------------------------------------------------------------


class ProtocolError(DomainError):
    """The Supervisor's reply broke the DELEGATE/TASK/FINAL protocol. The message is
    written for the model: it goes into the repair prompt."""


class BudgetExceeded(DomainError):
    def __init__(self, limit: int) -> None:
        super().__init__(f"The run reached its limit of {limit} real LLM calls.")
        self.limit = limit


class CanaryLeak(DomainError):
    def __init__(self) -> None:
        super().__init__("A response leaked internal instructions; the run was stopped.")


class KnowledgeUnavailable(DomainError):
    """The knowledge source (Wikipedia) could not be reached."""


# ---- LLM provider (from Labs 2-4) ------------------------------------------------------


class LLMError(DomainError):
    """Base class for failures talking to the LLM provider."""


class LLMQuotaExceeded(LLMError):
    def __init__(self, scope: Literal["minute", "day"], retry_after_s: float) -> None:
        super().__init__(f"LLM quota exceeded ({scope}); retry after {retry_after_s:.0f}s.")
        self.scope = scope
        self.retry_after_s = retry_after_s


class LLMUnavailable(LLMError):
    def __init__(self, reason: str, retry_after_s: float = 10) -> None:
        super().__init__(reason)
        self.retry_after_s = retry_after_s


class LLMOverloaded(LLMUnavailable):
    """The provider is temporarily overloaded (HTTP 5xx) — worth a short retry."""


class LLMTimeout(LLMError):
    pass


class LLMRequestRejected(LLMError):
    """The provider refused the request (bad key, invalid request, blocked content)."""

    def __init__(self, status: int | None, reason: str) -> None:
        super().__init__(reason)
        self.status = status


class LLMBadResponse(LLMError):
    """The model's answer could not be turned into a valid result."""
