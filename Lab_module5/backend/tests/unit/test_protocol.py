"""P1–P5: the DELEGATE/TASK/FINAL parser."""

import pytest

from app.domain.errors import ProtocolError
from app.domain.protocol import parse_decision, worker_key
from app.domain.transcript import Delegation

WORKERS = frozenset({"researcher", "writer", "reviewer", "fact_checker"})


def parse(text: str, max_delegations: int = 1, task_max_chars: int = 1000):
    return parse_decision(text, WORKERS, max_delegations, task_max_chars)


# P1
def test_valid_delegation_and_final():
    d = parse("REASON: Facts first.\nDELEGATE: researcher\nTASK: Find costs.\nAlso compare them.")
    assert d.action == "delegate" and d.reason == "Facts first."
    assert d.delegations == (Delegation("researcher", "Find costs.\nAlso compare them."),)
    assert parse("DELEGATE: writer\nTASK: Draft it.").reason is None

    answer = "## Title\n\n| a | b |\n|---|---|\n\nText [1].\n\n### Sources\n1. X — https://x"
    f = parse(f"REASON: Done.\nFINAL:\n{answer}")
    assert f.action == "final" and f.final == answer and f.delegations == ()
    assert parse("FINAL: One line answer.").final == "One line answer."


# P2
def test_tolerant_reading():
    fenced = "```text\n**DELEGATE:** Fact-Checker\n__TASK__: Check the draft.\n```"
    assert parse(fenced, 2).delegations == (Delegation("fact_checker", "Check the draft."),)
    assert parse("delegate: Writer\n\n  task:   Write it.").delegations[0].worker == "writer"
    assert parse("**FINAL**:\nAnswer").final == "Answer"
    # emphasis inside the final answer is kept as written
    assert parse("FINAL:\n**Task:** keep me").final == "**Task:** keep me"
    assert worker_key("`Researcher`.") == "researcher"


# P3
@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("FINAL: done\nDELEGATE: writer\nTASK: more", "not both"),
        ("DELEGATE: writer\nTASK: x\nFINAL: done", "not both"),
        ("Sure, I will help!", "must contain"),
        ("", "must contain"),
        ("DELEGATE: writer", "needs a 'TASK:'"),
        ("TASK: orphan", "right after its DELEGATE"),
        ("DELEGATE: writer\nTASK: a\nTASK: b", "right after its DELEGATE"),
        ("DELEGATE: editor\nTASK: polish", "Unknown worker 'editor'"),
        ("DELEGATE: writer\nTASK:   ", "is empty"),
        ("FINAL:   ", "complete final answer"),
    ],
)
def test_invalid_replies_raise_messages_for_the_repair_prompt(text, message):
    with pytest.raises(ProtocolError, match=message):
        parse(text)


def test_task_length_limit():
    with pytest.raises(ProtocolError, match="keep it under 20"):
        parse("DELEGATE: writer\nTASK: " + "x" * 30, task_max_chars=20)


# P4
def test_parallel_delegations():
    two = "DELEGATE: reviewer\nTASK: Review.\nDELEGATE: fact_checker\nTASK: Check."
    assert [d.worker for d in parse(two, 2).delegations] == ["reviewer", "fact_checker"]
    with pytest.raises(ProtocolError, match="one DELEGATE/TASK pair"):
        parse(two, 1)
    with pytest.raises(ProtocolError, match="at most 2"):
        parse(two + "\nDELEGATE: writer\nTASK: Write.", 2)
    with pytest.raises(ProtocolError, match="at most once"):
        parse("DELEGATE: writer\nTASK: a\nDELEGATE: writer\nTASK: b", 2)


# P5
def test_preamble_is_ignored_and_counted():
    d = parse("Let me think about this.\nOK.\nDELEGATE: writer\nTASK: Write.")
    assert d.preamble_chars == len("Let me think about this.") + len("OK.")
    # a forced call accepts FINAL only: an empty worker set rejects any delegation
    with pytest.raises(ProtocolError, match="Unknown worker"):
        parse_decision("DELEGATE: writer\nTASK: x", frozenset())
