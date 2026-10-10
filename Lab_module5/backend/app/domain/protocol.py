"""The Supervisor's reply protocol (the lab's DELEGATE/TASK/FINAL format).

    [REASON: <one line>]
    DELEGATE: <worker>            (1..max_delegations pairs, different workers)
    TASK: <text, may continue on following lines>
  or
    [REASON: <one line>]
    FINAL: <Markdown answer: the rest of the reply>

Pure functions. The parser — not the model — decides what is valid; every ProtocolError
message is written for the model, because it goes into the repair prompt."""

import re

from .errors import ProtocolError
from .transcript import Decision, Delegation

KEYS = ("REASON", "DELEGATE", "TASK", "FINAL")
_KEY = re.compile(r"^\s*(REASON|DELEGATE|TASK|FINAL)\s*:[ \t]?(.*)$", re.IGNORECASE)
_FENCE = re.compile(r"^```[\w-]*[ \t]*\n(.*)\n```$", re.DOTALL)
# **DELEGATE:**  __TASK__:  **FINAL**  → DELEGATE:
_EMPHASIS = re.compile(
    r"^([ \t]*)(?:[*_]{1,2})[ \t]*(REASON|DELEGATE|TASK|FINAL)"
    r"[ \t]*(:?)[ \t]*(?:[*_]{1,2})[ \t]*:?",
    re.IGNORECASE,
)
REASON_MAX_CHARS = 300


def strip_fence(text: str) -> str:
    t = text.strip()
    if m := _FENCE.match(t):
        t = m.group(1).strip()
    return t


def key_line(line: str) -> re.Match[str] | None:
    """Match a protocol key, ignoring Markdown emphasis around it (**DELEGATE:**)."""
    return _KEY.match(_EMPHASIS.sub(lambda m: f"{m.group(1)}{m.group(2)}:", line))


def worker_key(value: str) -> str:
    """'Fact-Checker' → 'fact_checker'; quotes, backticks and a trailing dot removed."""
    v = value.strip().strip("`'\"*_. ").lower()
    return re.sub(r"[\s-]+", "_", v)


def parse_decision(
    text: str,
    workers: frozenset[str],
    max_delegations: int = 1,
    task_max_chars: int = 1000,
) -> Decision:
    lines = strip_fence(text or "").splitlines()
    reason: str | None = None
    pairs: list[dict] = []
    final: str | None = None
    preamble = 0
    seen_key = False
    current: dict | None = None
    for i, line in enumerate(lines):
        m = key_line(line)
        if not m:
            if current is not None and current["task"] is not None:
                current["task"].append(line)
            elif not seen_key:
                preamble += len(line.strip())
            continue
        seen_key = True
        key, value = m.group(1).upper(), m.group(2).strip()
        if key == "FINAL":
            final = "\n".join([value, *lines[i + 1 :]]).strip()
            break
        if key == "REASON":
            reason = reason or value[:REASON_MAX_CHARS] or None
            current = None
        elif key == "DELEGATE":
            current = {"worker": worker_key(value), "raw": value, "task": None}
            pairs.append(current)
        else:  # TASK
            if current is None or current["task"] is not None:
                raise ProtocolError("Each TASK: line must come right after its DELEGATE: line.")
            current["task"] = [value]

    if final is not None:
        if pairs or any(
            (k := key_line(x)) and k.group(1).upper() == "DELEGATE" for x in lines[i + 1 :]
        ):
            raise ProtocolError("Use either DELEGATE/TASK or FINAL in one reply, not both.")
        if not final:
            raise ProtocolError("FINAL: must be followed by the complete final answer.")
        return Decision((), final, reason, preamble_chars=preamble)

    if not pairs:
        raise ProtocolError(
            "Your reply must contain 'DELEGATE: <worker>' followed by 'TASK: <instruction>', "
            "or 'FINAL:' followed by the final answer."
        )
    if len(pairs) > max_delegations:
        allowed = (
            "one DELEGATE/TASK pair"
            if max_delegations == 1
            else (f"at most {max_delegations} DELEGATE/TASK pairs")
        )
        raise ProtocolError(f"Send {allowed} per reply.")
    delegations = []
    for p in pairs:
        if p["worker"] not in workers:
            names = ", ".join(sorted(workers))
            raise ProtocolError(f"Unknown worker '{p['raw']}'. Choose one of: {names}.")
        if p["task"] is None:
            raise ProtocolError(f"DELEGATE: {p['worker']} needs a 'TASK:' line right after it.")
        task = "\n".join(p["task"]).strip()
        if not task:
            raise ProtocolError(f"The TASK for {p['worker']} is empty.")
        if len(task) > task_max_chars:
            raise ProtocolError(
                f"The TASK for {p['worker']} has {len(task)} characters; keep it under "
                f"{task_max_chars}."
            )
        delegations.append(Delegation(p["worker"], task))
    if len({d.worker for d in delegations}) != len(delegations):
        raise ProtocolError("Delegate to each worker at most once per reply.")
    return Decision(tuple(delegations), None, reason, preamble_chars=preamble)
