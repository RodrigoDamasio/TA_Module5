import dataclasses
from pathlib import Path

import pytest
from fakes import FakeLLM

from app.api.dependencies import Container, build_container
from app.config import Settings, get_settings
from app.domain.ports import KnowledgeSource
from app.infrastructure.fake_wikipedia import FakeWikipedia

TEST_SETTINGS = {
    "llm_mode": "fake",
    "wiki_mode": "fake",
    "runner_mode": "inline",
    "prompt_secret": "test-secret",
    "rate_limit_runs_per_minute": 1000,
    "rate_limit_runs_per_day": 10_000,
}


def make_settings(folder: Path, **overrides) -> Settings:
    return dataclasses.replace(
        get_settings(),
        **(TEST_SETTINGS | {"database_path": str(folder / "research.db")} | overrides),
    )


@dataclasses.dataclass
class Harness:
    """The real application services over temp storage, a fake LLM and fake Wikipedia."""

    container: Container
    llm: FakeLLM
    wiki: KnowledgeSource

    def submit(self, task: str = "When should I use RAG instead of fine-tuning?", **kw):
        kw.setdefault("max_iterations", None)
        kw.setdefault("require_approval", False)
        kw.setdefault("use_memory", False)
        return self.container.service.submit(task, **kw)

    def get(self, run_id: str):
        return self.container.service.get(run_id)

    def events(self, run_id: str) -> list[str]:
        return [e.type for e in self.container.service.runs.events_since(run_id, 0)]


@pytest.fixture
def harness(tmp_path):
    count = {"n": 0}

    def make(llm: FakeLLM | None = None, wiki: KnowledgeSource | None = None, **settings):
        count["n"] += 1
        folder = tmp_path / f"h{count['n']}"
        llm = llm or FakeLLM()
        wiki = wiki or FakeWikipedia()
        container = build_container(make_settings(folder, **settings), llm=llm, knowledge=wiki)
        return Harness(container, llm, wiki)

    return make


class Api:
    def __init__(self, client, container: Container, llm: FakeLLM) -> None:
        self.client, self.container, self.llm = client, container, llm

    def run(self, task: str = "When should I use RAG instead of fine-tuning?", **extra):
        return self.client.post("/run", json={"task": task, **extra})


@pytest.fixture
def api(tmp_path):
    from fastapi.testclient import TestClient

    from app.main import create_app

    clients = []

    def make(
        llm: FakeLLM | None = None,
        wiki: KnowledgeSource | None = None,
        raise_errors: bool = True,
        **settings,
    ) -> Api:
        llm = llm or FakeLLM()
        s = make_settings(tmp_path / f"api{len(clients)}", **settings)
        container = build_container(s, llm=llm, knowledge=wiki or FakeWikipedia())
        client = TestClient(
            create_app(s, container), raise_server_exceptions=raise_errors
        ).__enter__()
        clients.append(client)
        return Api(client, container, llm)

    yield make
    for client in clients:
        client.__exit__(None, None, None)
