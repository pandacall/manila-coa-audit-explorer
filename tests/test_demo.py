"""Seam 3: the public-demo guard rails over HTTP, with a scripted model and a fake Firestore."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from coa_explorer.answer import Answer, AnswerEngine
from coa_explorer.api import create_app
from coa_explorer.demo import Demo, SavedAnswer
from coa_explorer.index import build_index
from coa_explorer.models import ModelTurn, Usage
from coa_explorer.search import Index
from tests.fake_embedder import FakeEmbedder
from tests.fake_store import FakeStore
from tests.fixtures import write_fixture_records
from tests.scripted import ScriptedAdapter, point, search, submit

IPSAS_5 = "2023-5-description-1"
CITATION_5 = "CY 2023 AAR, Part II, Observation No. 5, pp. 71-73"
IP_A, IP_B = "203.0.113.7", "198.51.100.23"


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 2, 9, 30, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **delta) -> None:
        self.now += timedelta(**delta)


class NotCoveredAdapter:
    """A model that always says the reports don't cover it, counting how often it was asked."""

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, system, messages, tools) -> ModelTurn:
        self.calls += 1
        return submit("", [], covered=False, message="Not in the AARs.")


@pytest.fixture()
def index(tmp_path):
    records = write_fixture_records(tmp_path / "records")
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())
    with Index.open(tmp_path / "coa.sqlite", FakeEmbedder()) as opened:
        yield opened


@pytest.fixture()
def store():
    return FakeStore()


@pytest.fixture()
def clock():
    return Clock()


def make_demo(store, clock, **overrides) -> Demo:
    settings = {"hourly_limit": 3, "daily_cap": 5, "salt": "test-salt", "clock": clock}
    return Demo(store, **{**settings, **overrides})


def client_for(adapter, index, demo) -> TestClient:
    return TestClient(create_app(AnswerEngine(adapter, index), demo=demo))


def ask(client, question="What about cash advances?", ip=IP_A):
    with client.stream(
        "POST", "/api/ask", json={"question": question}, headers={"X-Forwarded-For": ip}
    ) as response:
        events = [json.loads(line) for line in response.iter_lines() if line]
        return response.status_code, events


def test_a_question_under_the_limits_is_answered(index, store, clock):
    client = client_for(NotCoveredAdapter(), index, make_demo(store, clock))

    status, events = ask(client)

    assert status == 200
    assert events[-1]["type"] == "not_covered"


# --- Per-IP hourly limit -----------------------------------------------------------------------


def test_an_ip_over_its_hourly_limit_is_turned_away_without_running_the_model(index, store, clock):
    adapter = NotCoveredAdapter()
    client = client_for(adapter, index, make_demo(store, clock, hourly_limit=3))

    for _ in range(3):
        assert ask(client)[0] == 200
    status, events = ask(client)

    assert status == 429
    assert [e["type"] for e in events] == ["rate_limited"]
    assert "3 questions an hour" in events[0]["message"]
    assert adapter.calls == 3


def test_another_ip_is_not_affected_by_the_limit(index, store, clock):
    client = client_for(NotCoveredAdapter(), index, make_demo(store, clock, hourly_limit=1))
    ask(client, ip=IP_A)

    assert ask(client, ip=IP_A)[0] == 429
    assert ask(client, ip=IP_B)[0] == 200


def test_the_hourly_limit_resets_in_the_next_hour(index, store, clock):
    client = client_for(NotCoveredAdapter(), index, make_demo(store, clock, hourly_limit=1))
    ask(client)
    assert ask(client)[0] == 429

    clock.advance(hours=1)

    assert ask(client)[0] == 200


def test_the_visitor_is_the_last_forwarded_address_which_cloud_run_added(index, store, clock):
    client = client_for(NotCoveredAdapter(), index, make_demo(store, clock, hourly_limit=1))
    ask(client, ip=f"6.6.6.6, {IP_A}")

    assert ask(client, ip=f"7.7.7.7, {IP_A}")[0] == 429  # a spoofed first entry changes nothing
    assert ask(client, ip=f"7.7.7.7, {IP_B}")[0] == 200


def test_the_ip_is_only_ever_stored_hashed_and_never_with_a_logged_question(index, store, clock):
    client = client_for(NotCoveredAdapter(), index, make_demo(store, clock))

    ask(client, ip=IP_A)

    assert IP_A not in store.everything()
    assert "203.0.113" not in store.everything()
    assert any(name.startswith("ip-") for name in store.counters)
    (record,) = store.questions.values()
    assert not any("ip" in name or name == "user_id" for name in record)


def test_the_ip_hash_depends_on_the_salt(clock):
    stores = FakeStore(), FakeStore()
    for store, salt in zip(stores, ("one", "two"), strict=True):
        assert make_demo(store, clock, salt=salt).admit(IP_A) == "ok"

    assert set(stores[0].counters) != set(stores[1].counters)


# --- Global daily cap --------------------------------------------------------------------------


def test_the_daily_cap_stops_questions_across_instances_and_restarts(index, store, clock):
    adapter = NotCoveredAdapter()
    settings = {"hourly_limit": 99, "daily_cap": 3}
    first = client_for(adapter, index, make_demo(store, clock, **settings))
    ask(first, ip="10.0.0.1")
    ask(first, ip="10.0.0.2")
    restarted = client_for(adapter, index, make_demo(store, clock, **settings))

    assert ask(restarted, ip="10.0.0.3")[0] == 200
    status, events = ask(first, ip="10.0.0.4")

    assert status == 429
    assert events[0]["type"] == "demo_limit"
    assert adapter.calls == 3


def test_the_daily_cap_starts_again_the_next_day(index, store, clock):
    demo = make_demo(store, clock, hourly_limit=99, daily_cap=1)
    client = client_for(NotCoveredAdapter(), index, demo)
    ask(client)
    assert ask(client)[0] == 429

    clock.advance(days=1)

    assert ask(client)[0] == 200


def test_questions_over_the_hourly_limit_do_not_use_up_the_daily_cap(index, store, clock):
    client = client_for(
        NotCoveredAdapter(), index, make_demo(store, clock, hourly_limit=1, daily_cap=2)
    )
    ask(client, ip=IP_A)
    for _ in range(5):
        ask(client, ip=IP_A)

    assert ask(client, ip=IP_B)[0] == 200


def test_the_daily_cap_defaults_to_about_three_hundred(store, clock):
    assert Demo(store, salt="s", clock=clock).daily_cap == 300


def test_when_capped_the_page_gets_example_questions_with_their_saved_answers(index, store, clock):
    saved = SavedAnswer(
        question="Did the 2023 statements follow IPSAS 1?",
        answer=Answer.model_validate(
            {
                "summary": "COA observed partial compliance.",
                "key_points": [
                    {
                        "text": "Comparative information was omitted.",
                        "citations": [{"text": CITATION_5, "title": "IPSAS 1"}],
                    }
                ],
            }
        ),
    )
    unanswered = SavedAnswer(question="What about cash advances?", answer=None)
    demo = make_demo(store, clock, daily_cap=0, examples=[saved, unanswered])
    client = client_for(NotCoveredAdapter(), index, demo)

    status, events = ask(client)

    assert status == 429
    (event,) = events
    assert event["message"] == "Demo limit reached for today"
    assert [e["question"] for e in event["examples"]] == [saved.question, unanswered.question]
    assert event["examples"][0]["answer"]["key_points"][0]["citations"][0]["text"] == CITATION_5
    assert event["examples"][1]["answer"] is None


def test_a_store_that_is_down_fails_closed_without_running_the_model(index, store, clock):
    adapter = NotCoveredAdapter()
    client = client_for(adapter, index, make_demo(store, clock))
    store.broken = True

    status, events = ask(client)

    assert status == 503
    assert events[0]["type"] == "error"
    assert "store is down" not in json.dumps(events)
    assert adapter.calls == 0


# --- The question log --------------------------------------------------------------------------


def test_each_answered_question_is_logged_with_citations_latency_and_token_cost(
    index, store, clock
):
    first = search("IPSAS 1")
    first.usage = Usage(input_tokens=1200, output_tokens=80)
    last = submit("COA observed it.", [point("Comparative information was omitted.", IPSAS_5)])
    last.usage = Usage(input_tokens=2500, output_tokens=150)
    client = client_for(ScriptedAdapter(first, last), index, make_demo(store, clock))

    _, events = ask(client, "Did the 2023 statements follow IPSAS 1?")

    (record,) = store.questions.values()
    assert record["question"] == "Did the 2023 statements follow IPSAS 1?"
    assert record["outcome"] == "answer"
    assert record["citations"] == [CITATION_5]
    assert record["input_tokens"] == 3700
    assert record["output_tokens"] == 230
    assert record["latency_ms"] >= 0
    assert record["asked_at"] == clock.now
    assert events[-1]["question_id"] in store.questions


def test_a_log_record_expires_after_thirty_days(index, store, clock):
    client = client_for(NotCoveredAdapter(), index, make_demo(store, clock))

    ask(client)

    (record,) = store.questions.values()
    assert record["expire_at"] == clock.now + timedelta(days=30)


def test_not_covered_and_failed_questions_are_logged_too(index, store, clock):
    class Broken:
        def generate(self, system, messages, tools):
            raise RuntimeError("secret internal detail")

    demo = make_demo(store, clock)
    ask(client_for(NotCoveredAdapter(), index, demo), "Out of scope?")
    _, events = ask(client_for(Broken(), index, demo), "Broken one?")

    assert [r["outcome"] for r in store.questions.values()] == ["not_covered", "error"]
    assert all(r["citations"] == [] for r in store.questions.values())
    assert "secret" not in json.dumps(events)


def test_questions_turned_away_by_the_limits_are_not_logged(index, store, clock):
    client = client_for(NotCoveredAdapter(), index, make_demo(store, clock, hourly_limit=0))

    ask(client)

    assert store.questions == {}


def test_a_log_failure_does_not_stop_the_visitor_getting_their_answer(index, store, clock):
    client = client_for(NotCoveredAdapter(), index, make_demo(store, clock))

    def broken_save(question_id, record):
        raise ConnectionError("log write failed")

    store.save_question = broken_save
    status, events = ask(client)

    assert status == 200
    assert events[-1]["type"] == "not_covered"
    assert "question_id" not in events[-1]


# --- Feedback ----------------------------------------------------------------------------------


def rate(client, question_id, rating):
    return client.post("/api/feedback", json={"question_id": question_id, "rating": rating})


def test_a_thumbs_up_or_down_is_stored_against_the_logged_question(index, store, clock):
    client = client_for(NotCoveredAdapter(), index, make_demo(store, clock))
    question_id = ask(client)[1][-1]["question_id"]

    assert rate(client, question_id, "up").status_code == 204
    assert store.questions[question_id]["rating"] == "up"

    assert rate(client, question_id, "down").status_code == 204
    assert store.questions[question_id]["rating"] == "down"


def test_feedback_for_an_unknown_question_or_a_bad_rating_is_rejected(index, store, clock):
    client = client_for(NotCoveredAdapter(), index, make_demo(store, clock))
    question_id = ask(client)[1][-1]["question_id"]

    assert rate(client, "f" * 32, "up").status_code == 404
    assert rate(client, "../other/doc", "up").status_code == 422
    assert rate(client, question_id, "meh").status_code == 422
    assert "rating" not in store.questions[question_id]


# --- Without the demo guard rails (local development) ------------------------------------------


def test_without_a_demo_the_app_answers_with_no_limits_and_no_logging(index):
    client = TestClient(create_app(AnswerEngine(NotCoveredAdapter(), index)))

    response = client.post("/api/ask", json={"question": "What about cash advances?"})

    assert response.status_code == 200
    assert "question_id" not in response.text
    assert rate(client, "a" * 32, "up").status_code == 404


# --- The page ----------------------------------------------------------------------------------


def test_the_footer_carries_the_disclaimer_and_the_logging_notice(index):
    client = TestClient(create_app(AnswerEngine(NotCoveredAdapter(), index)))

    page = client.get("/static/app.js").text

    assert (
        "Independent project, not affiliated with COA. Answers are AI-generated from the "
        "2020–2024 AARs; verify against the cited source."
    ) in page
    assert "Questions are logged anonymously and deleted after 30 days." in page


# --- Saved example answers ---------------------------------------------------------------------


def test_the_committed_saved_answers_load_and_cover_every_example_question():
    from coa_explorer.config import DEFAULT_SAVED_ANSWERS
    from coa_explorer.demo import EXAMPLE_QUESTIONS, load_saved_answers

    saved = load_saved_answers(DEFAULT_SAVED_ANSWERS)

    assert [item.question for item in saved] == list(EXAMPLE_QUESTIONS)
    assert all(item.answer and item.answer.key_points for item in saved)


def test_saved_answers_survive_a_round_trip_and_a_missing_file_is_just_empty(tmp_path):
    from coa_explorer.demo import load_saved_answers, save_answers

    answer = Answer.model_validate(
        {
            "summary": "s",
            "key_points": [{"text": "t", "citations": [{"text": CITATION_5, "title": "T"}]}],
        }
    )
    save_answers(tmp_path / "saved.json", [SavedAnswer(question="q?", answer=answer)])

    assert load_saved_answers(tmp_path / "saved.json") == [
        SavedAnswer(question="q?", answer=answer)
    ]
    assert load_saved_answers(tmp_path / "missing.json") == []


def test_serving_without_a_firestore_database_fails_closed_unless_opted_out(monkeypatch):
    from coa_explorer.cli import main

    monkeypatch.setenv("GCP_PROJECT_ID", "p")
    monkeypatch.setenv("GEMINI_ANSWER_MODEL", "m")
    monkeypatch.setenv("FIRESTORE_DATABASE", "")

    with pytest.raises(SystemExit) as stopped:
        main(["serve"])

    assert "FIRESTORE_DATABASE" in str(stopped.value)
    assert "--no-demo-limits" in str(stopped.value)
