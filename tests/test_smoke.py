"""Seam 3 for the deploy pipeline: the post-deploy smoke check against a running app."""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn

from coa_explorer import smoke
from coa_explorer.answer import AnswerEngine
from coa_explorer.api import create_app
from coa_explorer.cli import main
from coa_explorer.index import build_index
from coa_explorer.search import Index
from tests.fake_embedder import FakeEmbedder
from tests.fixtures import write_fixture_records
from tests.scripted import ScriptedAdapter, point, search, submit

IPSAS_5 = "2023-5-description-1"


@pytest.fixture()
def index(tmp_path):
    records = write_fixture_records(tmp_path / "records")
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())
    with Index.open(tmp_path / "coa.sqlite", FakeEmbedder()) as opened:
        yield opened


def serve(app) -> Iterator[str]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "the test server did not start"
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture()
def cited_app(index):
    adapter = ScriptedAdapter(
        search("IPSAS 1"),
        submit("The 2023 statements did not fully follow IPSAS 1.", [point("Omitted.", IPSAS_5)]),
    )
    yield from serve(create_app(AnswerEngine(adapter, index)))


@pytest.fixture()
def uncovered_app(index):
    adapter = ScriptedAdapter(submit("", [], covered=False, message="The AARs do not cover that."))
    yield from serve(create_app(AnswerEngine(adapter, index)))


def test_a_deployed_app_that_answers_with_citations_passes(cited_app):
    assert smoke.check(cited_app, "Did the 2023 statements follow IPSAS 1?") == []


def test_a_deployed_app_that_cannot_answer_fails_with_a_reason(uncovered_app):
    problems = smoke.check(uncovered_app, "Did the 2023 statements follow IPSAS 1?")

    assert problems and "answer" in problems[0]


def test_an_unreachable_app_fails_instead_of_raising():
    problems = smoke.check("http://127.0.0.1:9", "Anything?", timeout=2)

    assert problems and "127.0.0.1:9" in problems[0]


def test_the_smoke_command_exits_zero_when_the_app_works_and_one_when_it_does_not(
    cited_app, capsys
):
    assert main(["smoke", "--url", cited_app]) == 0
    assert main(["smoke", "--url", "http://127.0.0.1:9", "--timeout", "2"]) == 1
    assert "could not reach" in capsys.readouterr().err
