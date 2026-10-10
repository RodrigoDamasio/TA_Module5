"""Structured worker output (Labs 2-4 pattern): a lenient twin is sent to Gemini as the
response schema (no length limits, plain strings), the strict model is validated locally,
and a failure triggers one repair call with the exact errors."""

from typing import Literal

from pydantic import BaseModel, Field

# ---- Reviewer ------------------------------------------------------------------------


class ReviewIssueLLM(BaseModel):
    severity: str
    text: str


class ReviewLLM(BaseModel):
    verdict: str
    issues: list[ReviewIssueLLM]
    balance_flags: list[str]


class ReviewIssue(BaseModel):
    severity: Literal["high", "medium", "low"]
    text: str = Field(min_length=1, max_length=400)


class Review(BaseModel):
    verdict: Literal["approve", "revise"]
    issues: list[ReviewIssue] = Field(max_length=8)
    balance_flags: list[str] = Field(max_length=5)


# ---- Fact-Checker (extension) ----------------------------------------------------------


class ClaimLLM(BaseModel):
    sentence: str
    status: str
    source_n: int | None
    note: str


class FactCheckLLM(BaseModel):
    claims: list[ClaimLLM]


class Claim(BaseModel):
    sentence: str = Field(min_length=1, max_length=600)
    status: Literal["supported", "unsupported", "contradicted"]
    source_n: int | None = None
    note: str = Field(default="", max_length=300)


class FactCheck(BaseModel):
    claims: list[Claim] = Field(max_length=12)
