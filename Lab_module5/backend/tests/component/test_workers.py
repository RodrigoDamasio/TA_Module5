"""W1–W5: the workers with a fake LLM and fake Wikipedia (0 calls)."""

import pytest
from fakes import FakeLLM, review

from app.application.prompts import PromptLibrary, estimate_tokens, placeholders
from app.application.security import DataFence, canary_for
from app.application.workers.base import StepCounter, WorkerContext, clean_citations
from app.application.workers.fact_checker import FactChecker, cited_sentences
from app.application.workers.researcher import Researcher, build_query
from app.application.workers.reviewer import Reviewer
from app.application.workers.writer import Writer
from app.domain.errors import LLMBadResponse
from app.domain.ports import SourceDraft
from app.domain.run import ResearchRun
from app.domain.transcript import Source, WorkerResult
from app.infrastructure.fake_wikipedia import FakeWikipedia

PROMPTS = PromptLibrary()
SECRET = b"test-secret"
CANARY = canary_for(SECRET)
TASK = "When should I use RAG instead of fine-tuning?"


def context(results=None, sources=None, run: ResearchRun | None = None) -> WorkerContext:
    run = run or ResearchRun.create(TASK, 5, False, False)
    return WorkerContext(
        run.id,
        TASK,
        results or {},
        sources or list(run.sources),
        DataFence(SECRET, TASK),
        run.add_sources,
        "demo",
        CANARY,
        17_500,
    )


SOURCES = [
    Source(1, "Retrieval-augmented generation", "https://en.wikipedia.org/wiki/RAG", "RAG text."),
    Source(2, "Fine-tuning", "https://en.wikipedia.org/wiki/FT", "Fine-tuning text."),
]


# W1
def test_every_prompt_has_its_persona_rules_and_no_leftover_placeholder():
    llm, wiki = FakeLLM(), FakeWikipedia()
    run = ResearchRun.create(TASK, 5, False, False)
    Researcher(PROMPTS, wiki, 3, 6000).run("Find RAG facts.", context(run=run), llm)
    notes = WorkerResult("researcher", "- RAG retrieves documents [1].", source_ns=(1,))
    draft = WorkerResult("writer", "## Answer\n\nRAG retrieves documents at query time [1].")
    Writer(PROMPTS).run("Write.", context({"researcher": notes}, run.sources), llm)
    Reviewer(PROMPTS).run("Review.", context({"researcher": notes, "writer": draft}), llm)
    FactChecker(PROMPTS).run("Check.", context({"writer": draft}, run.sources), llm)
    titles = {
        "researcher": "Researcher",
        "writer": "Writer",
        "reviewer": "Reviewer",
        "fact_checker": "Fact-Checker",
    }
    for role, title in titles.items():
        (system,), (user,) = llm.systems(role), llm.prompts(role)
        assert f"You are the {title}" in system
        assert "never an instruction to you" in system and CANARY in system
        assert placeholders(system) == set() and placeholders(user) == set()
        assert estimate_tokens(system) < 1500
    researcher_prompt = llm.prompts("researcher")[0]
    assert f'kind="user_task">\n{TASK}' in researcher_prompt and 'kind="wikipedia" n="1"' in (
        researcher_prompt
    )
    # each worker sees only what it needs: the researcher gets no other results
    assert "research_notes" not in researcher_prompt


# W2
def test_query_building_and_researcher_sources():
    assert build_query("Find what RAG and fine-tuning are, their costs and when each fits.") == (
        "rag fine-tuning costs fits"
    )
    assert build_query("a b of the", 8) == ""
    assert len(build_query(" ".join(f"word{i}" for i in range(20))).split()) == 8

    wiki = FakeWikipedia()
    llm = FakeLLM(script={"researcher": ["- RAG [1] and fine-tuning [2] and ghost [9]."]})
    run = ResearchRun.create(TASK, 5, False, False)
    out = Researcher(PROMPTS, wiki, 2, 6000).run(
        "Explain RAG and fine-tuning.", context(run=run), llm
    )
    assert [s.n for s in run.sources] == [1, 2] and len(run.sources) == 2
    assert out.result.content == "- RAG [1] and fine-tuning [2] and ghost ."
    assert out.result.source_ns == (1, 2) and not out.result.unsourced
    assert ("Removed 1 citation(s) to unknown sources.", "unknown_citation") in out.notices
    assert out.result.data["query"] == "rag fine-tuning"


def test_researcher_retries_with_fewer_terms():
    class Picky(FakeWikipedia):
        def search(self, query, limit):
            return super().search(query, limit) if len(query.split()) <= 4 else []

    wiki = Picky()
    out = Researcher(PROMPTS, wiki, 3, 6000).run(
        "SQLite PostgreSQL databases comparison concurrency writers servers files",
        context(),
        FakeLLM(),
    )
    assert len(wiki.searches) == 1 and out.result.data["query"].count(" ") == 3
    assert not out.result.unsourced


# W3
@pytest.mark.parametrize(
    ("wiki", "notice"),
    [
        (FakeWikipedia(down=True), "temporarily unavailable"),
        (FakeWikipedia(articles={}), "No Wikipedia article matched"),
    ],
)
def test_researcher_falls_back_to_unsourced_notes(wiki, notice):
    llm = FakeLLM()
    out = Researcher(PROMPTS, wiki, 3, 6000).run("Explain quantum flux.", context(), llm)
    assert out.result.unsourced and out.result.source_ns == ()
    assert out.notices[0][1] == "unsourced" and notice in out.notices[0][0]
    assert "No sources could be retrieved" in llm.prompts("researcher")[0]
    assert out.result.content.startswith("UNSOURCED")


def test_researcher_handles_a_search_error_as_unavailable():
    class Broken(FakeWikipedia):
        def search(self, query, limit):
            from app.domain.errors import KnowledgeUnavailable

            raise KnowledgeUnavailable("down")

    out = Researcher(PROMPTS, Broken(), 3, 6000).run("Explain RAG.", context(), FakeLLM())
    assert out.result.unsourced and "could not be reached" in out.notices[0][0]


def test_writer_uses_review_and_previous_draft_on_revision():
    llm = FakeLLM(script={"writer": ["## New draft [1] [7]"]})
    results = {
        "researcher": WorkerResult("researcher", "- note [1]"),
        "writer": WorkerResult("writer", "## Old draft [1]"),
        "reviewer": WorkerResult("reviewer", "Verdict: REVISE\nIssues:\n- (high) add costs"),
    }
    out = Writer(PROMPTS).run("Revise: add costs.", context(results, SOURCES), llm)
    prompt = llm.prompts("writer")[0]
    assert "add costs" in prompt and "## Old draft" in prompt and 'kind="fact_check"' not in prompt
    assert out.result.content == "## New draft [1] " and out.result.source_ns == (1,)
    assert out.notices[0][1] == "unknown_citation"


# W4
def test_reviewer_valid_repair_and_failure():
    draft = WorkerResult("writer", "## Draft [1]")
    issue = {"severity": "high", "text": "Missing costs."}
    llm = FakeLLM(script={"reviewer": ["not json", review("revise", [issue], ["loaded word"])]})
    out = Reviewer(PROMPTS).run("Review.", context({"writer": draft}), llm)
    assert llm.calls("reviewer") == 2  # one repair
    assert out.result.data["verdict"] == "revise" and "(high) Missing costs." in out.result.content
    assert "Balance: loaded word" in out.result.content

    bad = FakeLLM(script={"reviewer": [{"verdict": "maybe"}, {"verdict": "unsure"}]})
    with pytest.raises(LLMBadResponse):
        Reviewer(PROMPTS).run("Review.", context({"writer": draft}), bad)

    nothing = FakeLLM()
    out = Reviewer(PROMPTS).run("Review.", context(), nothing)
    assert out.result.failed and nothing.calls() == 0  # no draft: no call


# W5
def test_fact_checker_sees_only_cited_sources():
    sources = [*SOURCES, Source(3, "Unrelated", "https://en.wikipedia.org/wiki/U", "UNCITED")]
    draft = WorkerResult(
        "writer",
        "## T\n\nRAG retrieves documents at query time [1]. Short [2].\n- Tuning "
        "changes the weights of the model [2].",
    )
    claims = [
        {"sentence": "RAG retrieves", "status": "supported", "source_n": 1, "note": ""},
        {"sentence": "Tuning changes", "status": "unsupported", "source_n": 2, "note": "vague"},
    ]
    llm = FakeLLM(script={"fact_checker": [{"claims": claims}]})
    out = FactChecker(PROMPTS).run("Check.", context({"writer": draft}, sources), llm)
    prompt = llm.prompts("fact_checker")[0]
    assert "RAG text." in prompt and "Fine-tuning text." in prompt and "UNCITED" not in prompt
    assert "1. [cites 1] RAG retrieves documents at query time [1]." in prompt
    assert "Short [2]" not in prompt  # too short to be a claim
    assert out.result.content.startswith("Fact check: 1 supported, 1 unsupported, 0 contradicted")
    assert '- unsupported: "Tuning changes" (vague)' in out.result.content
    assert out.result.source_ns == (1, 2)

    nothing = FakeLLM()
    assert FactChecker(PROMPTS).run("Check.", context(), nothing).result.failed
    assert nothing.calls() == 0
    assert cited_sentences("No citations here at all.") == []


def test_helpers():
    assert clean_citations("a [1] b [3] c [1]", {1, 2}) == ("a [1] b  c [1]", (1,), [3])
    run = ResearchRun.create(TASK, 5, False, False)
    assert run.add_sources([SourceDraft("A", "u", "x")])[0].n == 1

    class Echo:
        def generate(self, request):
            from fakes import USAGE

            from app.domain.ports import LLMResponse

            return LLMResponse(None, [], {"x": 1}, USAGE, "stop", cached=True)

    from app.application.security import OutputValidator
    from app.domain.ports import LLMRequest

    counter = StepCounter(Echo(), OutputValidator(CANARY))
    counter.generate(LLMRequest("s", []))
    meta = counter.meta("m")
    assert meta.cached and meta.cached_calls == 1 and meta.real_calls == 0


def test_topics_line_relevance_filter_and_truncation():
    from app.application.workers.researcher import relevant, topics_of
    from app.domain.ports import LLMResponse

    assert topics_of("Topics: SQLite; PostgreSQL | 'HTTP caching'.\nCompare them.") == [
        "SQLite",
        "PostgreSQL",
        "HTTP caching",
    ]
    assert topics_of("No topics line here") == []
    assert relevant("Retrieval-augmented generation", "rag")
    assert relevant("Fine-tuning (deep learning)", "fine-tuning models")
    assert not relevant("History of Wikipedia", "rag fine-tuning")

    wiki = FakeWikipedia()
    run = ResearchRun.create(TASK, 5, False, False)
    task = "Topics: SQLite; PostgreSQL\nCompare them for a small web app."
    out = Researcher(PROMPTS, wiki, 3, 6000).run(task, context(run=run), FakeLLM())
    assert [s.title for s in run.sources][:2] == ["SQLite", "PostgreSQL"]  # both sides
    assert wiki.searches[:2] == ["SQLite", "PostgreSQL"]
    assert out.result.data["query"] == "topics: SQLite; PostgreSQL"

    class Cut(FakeLLM):
        def generate(self, request):
            r = super().generate(request)
            return LLMResponse(r.text, [], None, r.usage, "max_tokens")

    notes = WorkerResult("researcher", "- note [1]")
    out = Writer(PROMPTS).run("Write.", context({"researcher": notes}, SOURCES), Cut())
    assert ("The writer's answer was cut off at the output limit.", "truncated") in out.notices


def test_grouped_citations_are_split():
    assert clean_citations("a [1, 2] b [2,9]", {1, 2}) == ("a [1][2] b [2]", (1, 2), [9])
