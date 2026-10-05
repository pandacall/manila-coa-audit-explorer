"""Seam 3: conversation and multilingual answers over HTTP, with a scripted model adapter.

The browser holds the conversation and sends the last few exchanges with each question; the server
keeps none of it.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from coa_explorer.answer import AnswerEngine
from coa_explorer.api import create_app
from coa_explorer.demo import Demo
from coa_explorer.index import build_index
from coa_explorer.search import Index
from tests.fake_embedder import FakeEmbedder
from tests.fake_store import FakeStore
from tests.fixtures import write_fixture_records
from tests.scripted import ScriptedAdapter, point, refuse, search, submit

IPSAS_5 = "2023-5-description-1"
CITATION_5 = "CY 2023 AAR, Part II, Observation No. 5, pp. 71-73"
EARLIER = {
    "question": "Did the 2023 statements follow IPSAS 1?",
    "answer": "COA observed that comparative information was omitted. "
    "(CY 2023 AAR, Part II, Observation No. 5, pp. 71-73)",
}


@pytest.fixture()
def index(tmp_path):
    records = write_fixture_records(tmp_path / "records")
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())
    with Index.open(tmp_path / "coa.sqlite", FakeEmbedder()) as opened:
        yield opened


def post(client, question, history=()):
    body = {"question": question, "history": list(history)}
    with client.stream("POST", "/api/ask", json=body) as response:
        return response.status_code, [json.loads(line) for line in response.iter_lines() if line]


def ask(index, adapter, question, history=()):
    status, events = post(TestClient(create_app(AnswerEngine(adapter, index))), question, history)
    assert status == 200, events
    return events


# --- Follow-up questions -----------------------------------------------------------------------


def test_the_earlier_exchanges_reach_the_model_before_the_follow_up(index):
    adapter = ScriptedAdapter(submit("", [], covered=False))

    ask(index, adapter, "What about 2022?", [EARLIER])

    _, messages, _ = adapter.requests[0]
    assert [(m.role, m.text) for m in messages] == [
        ("user", EARLIER["question"]),
        ("model", EARLIER["answer"]),
        ("user", "What about 2022?"),
    ]


def test_a_follow_up_cannot_cite_what_only_the_earlier_answer_retrieved(index):
    earlier = {**EARLIER, "answer": f"Comparative information was omitted. [{IPSAS_5}]"}
    adapter = ScriptedAdapter(submit("Same as before.", [point("Still omitted.", IPSAS_5)]))

    result = ask(index, adapter, "And was it fixed?", [earlier])[-1]

    assert result["type"] == "not_covered"


def test_each_follow_up_runs_its_own_search_and_carries_its_own_citations(index):
    adapter = ScriptedAdapter(
        search("IPSAS 1", years=[2023]),
        submit("COA observed it again.", [point("Comparative information was omitted.", IPSAS_5)]),
    )

    events = ask(index, adapter, "What about 2023?", [EARLIER])

    assert [e["type"] for e in events] == ["status", "answer"]
    assert [c["text"] for c in events[-1]["key_points"][0]["citations"]] == [CITATION_5]


def test_the_model_is_told_to_search_again_for_a_follow_up(index):
    adapter = ScriptedAdapter(submit("", [], covered=False))

    ask(index, adapter, "What about 2022?", [EARLIER])

    system, _, _ = adapter.requests[0]
    assert "follow-up" in system
    assert "search again" in system


# --- The conversation stays in the browser -----------------------------------------------------


def test_the_question_log_holds_only_the_new_question_never_the_conversation(index):
    store = FakeStore()
    demo = Demo(store, salt="test-salt")
    client = TestClient(
        create_app(AnswerEngine(ScriptedAdapter(submit("", [], covered=False)), index), demo)
    )

    status, _ = post(client, "What about 2022?", [EARLIER])

    assert status == 200
    [record] = store.questions.values()
    assert record["question"] == "What about 2022?"
    assert EARLIER["question"] not in store.everything()
    assert "comparative information" not in store.everything()


def test_only_the_last_few_exchanges_are_accepted(index):
    client = TestClient(create_app(AnswerEngine(ScriptedAdapter(), index)))

    status, _ = post(client, "What about 2022?", [EARLIER] * 4)

    assert status == 422


def test_an_overlong_earlier_answer_is_rejected(index):
    client = TestClient(create_app(AnswerEngine(ScriptedAdapter(), index)))

    status, _ = post(client, "What about 2022?", [{**EARLIER, "answer": "x" * 3001}])

    assert status == 422


# --- Answering in the language of the question ------------------------------------------------

FILIPINO = "Ano ang napansin ng COA tungkol sa IPSAS 1 noong 2023?"


def test_a_filipino_question_reaches_the_model_as_asked(index):
    adapter = ScriptedAdapter(submit("", [], covered=False))

    ask(index, adapter, FILIPINO)

    _, messages, _ = adapter.requests[0]
    assert messages[-1].text == FILIPINO


def test_the_model_is_told_to_answer_in_the_language_of_the_question_and_quote_coa_in_english(
    index,
):
    adapter = ScriptedAdapter(submit("", [], covered=False))

    ask(index, adapter, FILIPINO)

    system, _, _ = adapter.requests[0]
    assert "in the language of the question" in system
    assert "Filipino" in system and "Taglish" in system
    assert "quote" in system and "AAR's English" in system
    assert "search in English" in system
    assert "in English. Keep it short" not in system


def test_an_answer_in_filipino_reaches_the_page_unchanged_with_its_english_quote(index):
    summary = "Napansin ng COA na hindi ipinakita ang “comparative information” sa 2023."
    adapter = ScriptedAdapter(
        search("IPSAS 1", years=[2023]),
        submit(summary, [point("Hindi sumunod sa IPSAS 1 ang mga financial statement.", IPSAS_5)]),
    )

    answer = ask(index, adapter, FILIPINO)[-1]

    assert answer["summary"] == summary
    assert [c["text"] for c in answer["key_points"][0]["citations"]] == [CITATION_5]


# --- Suggested questions when nothing is found -------------------------------------------------


def test_a_not_covered_result_carries_the_questions_the_model_suggests(index):
    suggestions = [
        "What did COA observe about cash advances in 2023?",
        "Did Manila act on COA's recommendations about cash advances?",
    ]
    adapter = ScriptedAdapter(
        search("parking fees"),
        submit(
            "",
            [],
            covered=False,
            message="The AARs say nothing on parking.",
            suggestions=suggestions,
        ),
    )

    result = ask(index, adapter, "How much did Manila earn from parking?")[-1]

    assert result["type"] == "not_covered"
    assert result["suggestions"] == suggestions


def test_without_suggestions_from_the_model_the_example_questions_are_suggested(index):
    adapter = ScriptedAdapter(submit("", [], covered=False))

    result = ask(index, adapter, "How much did Manila earn from parking?")[-1]

    assert result["suggestions"] == [
        "What did COA observe about cash advances in Manila?",
        "Did Manila comply with IPSAS 1 in its financial statements? Which years?",
        "Did Manila act on COA's recommendations about cash advances?",
    ]


def test_an_answer_the_engine_could_not_ground_still_suggests_questions(index):
    adapter = ScriptedAdapter(submit("Summary.", [point("Unsupported claim.")]))

    result = ask(index, adapter, "Tell me something")[-1]

    assert result["type"] == "not_covered"
    assert len(result["suggestions"]) == 3


def test_at_most_three_short_suggestions_are_kept(index):
    adapter = ScriptedAdapter(
        submit("", [], covered=False, suggestions=["", "One?", "Two " * 100, "Three?", "Four?"])
    )

    result = ask(index, adapter, "Anything?")[-1]

    assert [s[:4] for s in result["suggestions"]] == ["One?", "Two ", "Thre"]
    assert all(len(s) <= 200 for s in result["suggestions"])


# --- Out-of-scope questions --------------------------------------------------------------------


def test_an_out_of_scope_question_is_refused_with_the_models_explanation(index):
    message = "I only cover COA's 2020-2024 audit reports on the City of Manila, not Quezon City."
    adapter = ScriptedAdapter(refuse(message))

    result = ask(index, adapter, "What did COA say about Quezon City?")[-1]

    assert result["type"] == "not_covered"
    assert result["reason"] == "out_of_scope"
    assert result["message"] == message
    assert result["suggestions"]


def test_a_refusal_without_an_explanation_says_what_the_app_covers(index):
    adapter = ScriptedAdapter(refuse())

    result = ask(index, adapter, "Who will win the next mayoral election?")[-1]

    assert result["reason"] == "out_of_scope"
    assert "Annual Audit Reports on the City of Manila, 2020–2024" in result["message"]


def test_a_question_the_reports_simply_do_not_answer_is_not_a_refusal(index):
    adapter = ScriptedAdapter(search("parking fees"), submit("", [], covered=False))

    result = ask(index, adapter, "How much did Manila earn from parking?")[-1]

    assert result["reason"] == "not_found"


def test_the_model_is_told_to_refuse_other_cities_news_and_politics(index):
    adapter = ScriptedAdapter(refuse())

    ask(index, adapter, "What is the news today?")

    system, _, tools = adapter.requests[0]
    assert "out_of_scope" in system
    assert all(topic in system for topic in ("other cities", "news", "politics"))
    [submit_tool] = [tool for tool in tools if tool.name == "submit_answer"]
    assert "out_of_scope" in submit_tool.parameters["properties"]


# --- The page ----------------------------------------------------------------------------------


def test_the_page_gets_example_questions_to_show(index):
    client = TestClient(create_app(AnswerEngine(ScriptedAdapter(), index)))

    response = client.get("/api/examples")

    assert response.status_code == 200
    assert response.json()["questions"] == [
        "What did COA observe about cash advances in Manila?",
        "Did Manila comply with IPSAS 1 in its financial statements? Which years?",
        "Did Manila act on COA's recommendations about cash advances?",
    ]
    assert "/api/examples" in client.get("/static/app.js").text


def test_the_page_sends_the_conversation_and_offers_to_start_a_new_one(index):
    client = TestClient(create_app(AnswerEngine(ScriptedAdapter(), index)))

    page = client.get("/static/app.js").text

    assert "history" in page
    assert "New conversation" in page
