"""D1–D4: the run aggregate."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.errors import InvalidTransition
from app.domain.ports import SourceDraft, TokenUsage
from app.domain.run import ResearchRun, RunStatus, run_from_dict, run_to_dict
from app.domain.transcript import CallMeta, Decision, Delegation, WorkerResult


def new_run(**kw) -> ResearchRun:
    return ResearchRun.create("A research task", 5, kw.get("approval", False), True)


# D1
def test_transitions_emit_one_event_each():
    run = new_run()
    run.start()
    assert run.status is RunStatus.RUNNING and [e.type for e in run.pop_events()] == ["run_started"]
    run.propose_final("Answer", forced=False, degraded=False)
    assert run.status is RunStatus.COMPLETED and run.final_output == "Answer" and run.done
    assert [e.type for e in run.pop_events()] == ["completed"]
    for action in (run.start, run.approve, lambda: run.fail("x")):
        with pytest.raises(InvalidTransition):
            action()
    with pytest.raises(InvalidTransition, match="reject"):
        run.reject("x", 2)


def test_decisions_and_results_build_the_transcript_and_totals():
    run = new_run()
    run.start()
    d = Decision((Delegation("researcher", "Find."),), None, "Facts first.")
    run.record_decision(d, CallMeta("m", TokenUsage(10, 2), real_calls=1))
    run.record_result(
        "Find.",
        WorkerResult("researcher", "notes", unsourced=True),
        CallMeta("m", TokenUsage(5, 1), cached_calls=1),
    )
    assert run.iteration == 1 and run.llm_calls == 1 and run.cached_calls == 1
    assert run.tokens == TokenUsage(15, 3) and "unsourced" in run.flags
    assert run.latest_result("researcher").content == "notes"
    assert run.latest_result("writer") is None
    clone = run_from_dict(run_to_dict(run))
    assert run_to_dict(clone) == run_to_dict(run)
    assert clone.transcript[1].meta.cached and not clone.transcript[0].meta.cached


# D2
def test_sources_are_deduplicated_and_numbered_across_rounds():
    run = new_run()
    a = run.add_sources(
        [SourceDraft("A", "https://w/a", "x"), SourceDraft("B", "https://w/b", "y")]
    )
    b = run.add_sources(
        [SourceDraft("B", "https://w/b", "y"), SourceDraft("C", "https://w/c", "z")]
    )
    assert [s.n for s in a] == [1, 2] and [s.n for s in b] == [2, 3]
    assert [s.title for s in run.sources] == ["A", "B", "C"]


# D3
def test_approval_reject_with_feedback_once_then_cancel():
    run = new_run(approval=True)
    run.start()
    run.iteration = 3
    run.propose_final("Draft", forced=True, degraded=False, approval_timeout_min=30)
    assert run.status is RunStatus.AWAITING_APPROVAL and run.draft == "Draft"
    assert run.final_output is None and "forced" in run.flags
    assert run.reject("Add an example.", 2) is True
    assert run.status is RunStatus.QUEUED and run.iteration_limit == 5 and run.revisions == 1
    assert run.feedback() == ["Add an example."]
    run.start()
    run.propose_final("Draft 2", forced=False, degraded=False)
    assert run.reject("Again", 2) is False and run.status is RunStatus.CANCELLED

    other = new_run(approval=True)
    other.start()
    other.propose_final("Draft", forced=False, degraded=False)
    other.approve()
    assert other.status is RunStatus.COMPLETED and other.final_output == "Draft"
    assert other.draft is None


def test_approval_expiry():
    run = new_run(approval=True)
    run.start()
    run.propose_final("Draft", forced=False, degraded=False, approval_timeout_min=30)
    now = datetime.now(UTC)
    assert not run.approval_expired(now)
    assert run.approval_expired(now + timedelta(minutes=31))
    assert run.reject(None, 2) is False and run.status is RunStatus.CANCELLED


# D4
def test_previous_result_matches_identical_delegations_only():
    run = new_run()
    run.start()
    run.record_result("Find X.", WorkerResult("researcher", "notes"), CallMeta())
    run.record_result("Broken.", WorkerResult("writer", "failed", failed=True), CallMeta())
    assert run.previous_result(Delegation("researcher", "Find X.")).content == "notes"
    assert run.previous_result(Delegation("researcher", "Find Y.")) is None
    assert run.previous_result(Delegation("writer", "Broken.")) is None
    assert run.latest_result("writer") is None  # failed results never count as drafts


def test_duration_and_failure():
    run = new_run()
    assert run.duration_ms is None
    run.start()
    run.fail("boom")
    assert run.status is RunStatus.FAILED and run.error == "boom" and run.duration_ms >= 0
