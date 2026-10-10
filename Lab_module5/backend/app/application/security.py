"""Module 5 §2 defenses: input validation, prompt isolation (data fences), a canary in every
system prompt, and output validation (secret redaction).

Nonces and the canary are DERIVED (HMAC of a server secret), not random per run: the same
task gives the same prompts, so the response cache keeps working, and a source author
still cannot guess them."""

import hashlib
import hmac
import re

from app.domain.errors import CanaryLeak

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

# The course's InputValidator patterns (§2.2), named so flags and logs carry names only.
INJECTION_PATTERNS: dict[str, re.Pattern[str]] = {
    name: re.compile(pattern, re.IGNORECASE)
    for name, pattern in {
        "ignore_instructions": r"ignore.*(?:previous|above|prior).*instructions",
        "disregard_previous": r"disregard.*(?:previous|above|prior)",
        "forget_instructions": r"forget.*(?:everything|all|instructions)",
        "system_prompt": r"system.*prompt",
        "you_are_now": r"you.*are.*now",
        "pretend": r"pretend.*(?:to|you)",
        "repeat_back": r"repeat.*(?:above|everything|back)",
    }.items()
}

# The course's OutputValidator patterns + Google API keys.
SECRET_PATTERNS = [
    re.compile(p, re.IGNORECASE)
    for p in (
        r"api[_-]?key\s*[:=]\s*[\w-]+",
        r"password\s*[:=]\s*\S+",
        r"secret\s*[:=]\s*\S+",
        r"sk-ant-[a-zA-Z0-9_-]+",
        r"sk-[a-zA-Z0-9]{16,}",
        r"AIza[0-9A-Za-z_-]{35}",
    )
]


class InputValidator:
    def sanitize(self, text: str) -> str:
        return _CONTROL.sub("", text).strip()

    def check(self, text: str) -> list[str]:
        """Names of the injection patterns found. They FLAG a run, never block it:
        'system prompt design' is a legitimate research topic."""
        return [name for name, p in INJECTION_PATTERNS.items() if p.search(text)]


class OutputValidator:
    def __init__(self, canary: str) -> None:
        self.canary = canary

    def check_canary(self, text: str | None) -> None:
        if text and self.canary in text:
            raise CanaryLeak()

    def redact(self, text: str) -> tuple[str, bool]:
        out = text
        for p in SECRET_PATTERNS:
            out = p.sub("[REDACTED]", out)
        return out, out != text

    def clean(self, text: str) -> tuple[str, bool]:
        """Canary check (raises) + redaction. Returns (text, redacted?)."""
        self.check_canary(text)
        return self.redact(text)


def _hmac(secret: bytes, message: str) -> str:
    return hmac.new(secret, message.encode(), hashlib.sha256).hexdigest()


def canary_for(secret: bytes) -> str:
    return "CNRY-" + _hmac(secret, "canary")[:16]


class DataFence:
    """Wraps untrusted text: <data id="nonce" kind="wikipedia" n="2"> … </data id="nonce">.
    Markers inside the text are escaped, so the text cannot close its own block."""

    def __init__(self, secret: bytes, task: str) -> None:
        self.nonce = _hmac(secret, "fence:" + task)[:12]

    def wrap(self, text: str, kind: str, **attrs: object) -> str:
        escaped = re.sub(r"<(/?)data\b", r"&lt;\1data", text, flags=re.IGNORECASE)
        extra = "".join(f' {k}="{_attr(v)}"' for k, v in attrs.items())
        opening = f'<data id="{self.nonce}" kind="{kind}"{extra}>'
        return f'{opening}\n{escaped}\n</data id="{self.nonce}">'


def _attr(value: object) -> str:
    return str(value).replace('"', "'").replace("\n", " ")[:200]
