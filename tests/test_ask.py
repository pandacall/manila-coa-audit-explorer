"""Seam 3: asking over HTTP, with a scripted model adapter and an index of fixture records."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from coa_explorer.answer import Answer, AnswerEngine, NotCovered
from coa_explorer.api import create_app
from coa_explorer.index import build_index
from coa_explorer.search import Index
from tests.fixtures import write_fixture_records
from tests.scripted import ScriptedAdapter, point, say, search, submit

IPSAS_5 = "2023-5-description-1"
CITATION_5 = "CY 2023 AAR, Part II, Observation No. 5, pp. 71-73"


@pytest.fixture()
def index(tmp_path):
    records = write_fixture_records(tmp_path / "records")
    build_index(records, tmp_path / "coa.sqlite")
    with Index.open(tmp_path / "coa.sqlite") as opened:
        yield opened


def ask(index, adapter, question="Did the 2023 statements follow IPSAS 1?"):
    client = TestClient(create_app(AnswerEngine(adapter, index)))
    with client.stream("POST", "/api/ask", json={"question": question}) as response:
        assert response.status_code == 200
        return [json.loads(line) for line in response.iter_lines() if line]


def final(events):
    assert events[-1]["type"] in {"answer", "not_covered"}, events
    return events[-1]


def test_streams_an_answer_whose_key_points_carry_citations(index):
    adapter = ScriptedAdapter(
        search("IPSAS 1"),
        submit(
            "COA observed that the 2023 statements did not fully comply with IPSAS 1.",
            [point("Comparative information was omitted.", IPSAS_5)],
        ),
    )

    events = ask(index, adapter)

    assert [e["type"] for e in events[:-1]] == ["status"]
    answer = Answer.model_validate(final(events))
    assert answer.key_points[0].text == "Comparative information was omitted."
    assert [c.text for c in answer.key_points[0].citations] == [CITATION_5]


def test_the_model_sees_each_search_result_with_its_citation(index):
    adapter = ScriptedAdapter(search("IPSAS 1"), submit("s", [point("p", IPSAS_5)]))

    ask(index, adapter)

    _, messages, _ = adapter.requests[1]
    results = messages[-1].tool_results[0].content
    assert results[0]["id"] == IPSAS_5
    assert results[0]["citation"] == CITATION_5


def test_key_points_without_a_citation_are_removed(index):
    adapter = ScriptedAdapter(
        search("IPSAS 1"),
        submit(
            "Summary.",
            [
                point("Grounded point.", IPSAS_5),
                point("Point with no source."),
                point("Point citing a piece the model never retrieved.", "2020-9-description-1"),
            ],
        ),
    )

    answer = Answer.model_validate(final(ask(index, adapter)))

    assert [kp.text for kp in answer.key_points] == ["Grounded point."]


def test_an_answer_left_with_no_cited_key_points_is_not_covered(index):
    adapter = ScriptedAdapter(search("IPSAS 1"), submit("Summary.", [point("Unsupported claim.")]))

    result = NotCovered.model_validate(final(ask(index, adapter)))

    assert "don't cover" in result.message


def test_the_model_can_say_the_reports_do_not_cover_the_question(index):
    adapter = ScriptedAdapter(
        search("quezon city"),
        submit("", [], covered=False, message="The AARs do not mention Quezon City."),
    )

    result = NotCovered.model_validate(
        final(ask(index, adapter, "What did COA say about Quezon City?"))
    )

    assert result.message == "The AARs do not mention Quezon City."


def test_answer_length_is_capped(index):
    adapter = ScriptedAdapter(
        search("IPSAS 1"),
        submit(
            "word " * 1000,
            [point("long " * 1000, IPSAS_5)] + [point(f"p{i}", IPSAS_5) for i in range(20)],
        ),
    )

    answer = Answer.model_validate(final(ask(index, adapter)))

    assert len(answer.summary) <= 600
    assert len(answer.key_points) <= 6
    assert all(len(kp.text) <= 500 for kp in answer.key_points)


def test_a_model_that_never_submits_an_answer_ends_as_not_covered(index):
    adapter = ScriptedAdapter(say("Here is a rambling reply."), say("Still no tool call."))

    result = NotCovered.model_validate(final(ask(index, adapter)))

    assert result.message


def test_a_model_that_searches_forever_is_stopped(index):
    adapter = ScriptedAdapter(*[search(f"cash {i}") for i in range(10)])

    events = ask(index, adapter)

    assert final(events)["type"] == "not_covered"
    assert len(adapter.requests) <= 6


def test_a_model_failure_is_reported_without_leaking_details(index):
    class Broken:
        def generate(self, system, messages, tools):
            raise RuntimeError("secret internal detail")

    events = ask(index, Broken())

    assert events[-1]["type"] == "error"
    assert "secret" not in json.dumps(events)


def test_an_empty_question_is_rejected(index):
    client = TestClient(create_app(AnswerEngine(ScriptedAdapter(), index)))

    assert client.post("/api/ask", json={"question": "   "}).status_code == 422


def test_the_web_page_is_served_by_the_same_app(index):
    client = TestClient(create_app(AnswerEngine(ScriptedAdapter(), index)))

    page = client.get("/")

    assert page.status_code == 200
    assert 'id="root"' in page.text
