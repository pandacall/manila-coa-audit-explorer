"""Seam 3: asking over HTTP, with a scripted model adapter and an index of fixture records."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from coa_explorer.answer import Answer, AnswerEngine, NotCovered
from coa_explorer.api import create_app
from coa_explorer.index import build_index
from coa_explorer.models import ModelTurn, ToolCall
from coa_explorer.search import Index
from tests.fake_embedder import FakeEmbedder
from tests.fixtures import write_fixture_records
from tests.monitoring_fixtures import FIXTURE_MONITORING
from tests.scripted import ScriptedAdapter, point, say, search, submit, submit_with_city

IPSAS_5 = "2023-5-description-1"
CITATION_5 = "CY 2023 AAR, Part II, Observation No. 5, pp. 71-73"


@pytest.fixture()
def index(tmp_path):
    records = write_fixture_records(tmp_path / "records")
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())
    with Index.open(tmp_path / "coa.sqlite", FakeEmbedder()) as opened:
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
    assert len(adapter.requests) <= 8


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


def test_malformed_search_arguments_are_reported_to_the_model_not_fatal(index):
    adapter = ScriptedAdapter(
        search("IPSAS 1", years=["not a year"]),
        search("IPSAS 1", years=[2023]),
        submit("Summary.", [point("Grounded point.", IPSAS_5)]),
    )

    events = ask(index, adapter)

    assert final(events)["type"] == "answer"
    _, messages, _ = adapter.requests[1]
    assert "error" in messages[-1].tool_results[0].content


def test_covered_must_be_a_real_boolean_and_sources_a_list(index):
    string_false = ScriptedAdapter(
        search("IPSAS 1"), submit("Summary.", [point("Point.", IPSAS_5)], covered="false")
    )
    assert final(ask(index, string_false))["type"] == "not_covered"

    one_source = ScriptedAdapter(
        search("IPSAS 1"),
        submit("Summary.", [{"text": "Point.", "sources": IPSAS_5}]),
    )
    answer = Answer.model_validate(final(ask(index, one_source)))
    assert [c.text for c in answer.key_points[0].citations] == [CITATION_5]


# --- Follow-up timelines (Part III) ---------------------------------------------------------

CASH_ADVANCES_2023 = "2023-III-1"
CASH_ADVANCES_2024 = "2024-III-1"


def timeline_call(year: int, observation: int) -> ModelTurn:
    args = {"origin_year": year, "origin_observation": observation}
    return ModelTurn(text=None, tool_calls=[ToolCall("timeline", args)])


def submit_with_timelines(summary, key_points, timelines):
    turn = submit(summary, key_points)
    turn.tool_calls[0].args["timelines"] = timelines
    return turn


def test_a_follow_up_question_is_answered_with_a_timeline_the_tool_assembled(index):
    adapter = ScriptedAdapter(
        search("cash advances", parts=["III"]),
        timeline_call(2022, 3),
        submit_with_timelines(
            "COA's Status of Implementation went from partial to not implemented.",
            [
                point(
                    "In 2023 COA recorded the recommendation as partially implemented.",
                    CASH_ADVANCES_2023,
                ),
                point("By 2024 COA recorded it as not implemented.", CASH_ADVANCES_2024),
            ],
            [{"origin_year": 2022, "origin_observation": 3}],
        ),
    )

    events = ask(index, adapter, "Did Manila act on COA's recommendations about cash advances?")

    assert [e["type"] for e in events[:-1]] == ["status", "status"]
    assert "Observation No. 3" in events[1]["message"]
    answer = Answer.model_validate(final(events))
    assert [c.text for c in answer.key_points[0].citations] == [
        "CY 2023 AAR, Part III, CY 2022 Observation No. 3, p. 91"
    ]
    (timeline,) = answer.timelines
    assert timeline.raised.citation == "CY 2022 AAR, Part II, Observation No. 3, p. 73"
    assert [(s.aar_year, s.follow_ups[0].status) for s in timeline.steps] == [
        (2023, "Partially Implemented"),
        (2024, "Not Implemented"),
    ]
    assert timeline.steps[0].follow_ups[0].management_action.startswith("The City liquidated")


def test_the_model_sees_the_timeline_with_an_id_and_citation_for_every_step(index):
    adapter = ScriptedAdapter(timeline_call(2022, 3), submit("s", [point("p", CASH_ADVANCES_2024)]))

    ask(index, adapter)

    _, messages, tools = adapter.requests[1]
    assert {"search", "timeline", "submit_answer"} == {t.name for t in adapter.requests[0][2]}
    timeline = messages[-1].tool_results[0].content["timeline"]
    assert [f["key"] for step in timeline["steps"] for f in step["follow_ups"]] == [
        CASH_ADVANCES_2023,
        CASH_ADVANCES_2024,
    ]
    assert timeline["steps"][0]["follow_ups"][0]["status"] == "Partially Implemented"


def test_search_results_name_the_observation_so_the_model_can_ask_for_its_timeline(index):
    adapter = ScriptedAdapter(search("cash advances"), submit("s", [point("p", IPSAS_5)]))

    ask(index, adapter)

    results = adapter.requests[1][1][-1].tool_results[0].content
    part_iii = next(r for r in results if r["id"] == CASH_ADVANCES_2023)
    assert (part_iii["origin_year"], part_iii["origin_observation"]) == (2022, 3)


def test_search_can_filter_one_years_follow_up_by_status(index):
    adapter = ScriptedAdapter(
        search("", years=[2024], parts=["III"], status="Not Implemented", limit=25),
        submit("s", [point("p", CASH_ADVANCES_2024)]),
    )

    answer = Answer.model_validate(final(ask(index, adapter)))

    results = adapter.requests[1][1][-1].tool_results[0].content
    assert [r["id"] for r in results] == [CASH_ADVANCES_2024]
    assert answer.key_points[0].citations[0].text.startswith("CY 2024 AAR, Part III")


def test_a_timeline_the_model_never_retrieved_is_not_shown(index):
    adapter = ScriptedAdapter(
        search("cash advances"),
        submit_with_timelines(
            "s",
            [point("p", CASH_ADVANCES_2023)],
            [
                {"origin_year": 2022, "origin_observation": 3},
                {"origin_year": 1, "origin_observation": "x"},
                "junk",
            ],
        ),
    )

    answer = Answer.model_validate(final(ask(index, adapter)))

    assert answer.timelines == []


def test_at_most_three_timelines_are_shown(index):
    adapter = ScriptedAdapter(
        timeline_call(2022, 3),
        timeline_call(2019, 4),
        timeline_call(2023, 5),
        timeline_call(2023, 1),
        submit_with_timelines(
            "s",
            [point("p", CASH_ADVANCES_2023)],
            [
                {"origin_year": 2022, "origin_observation": 3},
                {"origin_year": 2019, "origin_observation": 4},
                {"origin_year": 2023, "origin_observation": 5},
                {"origin_year": 2023, "origin_observation": 1},
            ],
        ),
    )

    answer = Answer.model_validate(final(ask(index, adapter)))

    assert [(t.origin_year, t.origin_observation) for t in answer.timelines] == [
        (2022, 3),
        (2019, 4),
        (2023, 5),
    ]


def test_a_timeline_for_an_unknown_observation_is_reported_to_the_model_not_fatal(index):
    adapter = ScriptedAdapter(
        timeline_call(2021, 99),
        ModelTurn(text=None, tool_calls=[ToolCall("timeline", {"origin_year": "later"})]),
        timeline_call(2022, 3),
        submit("s", [point("p", CASH_ADVANCES_2023)]),
    )

    events = ask(index, adapter)

    assert final(events)["type"] == "answer"
    assert "nothing on CY 2021" in adapter.requests[1][1][-1].tool_results[0].content["error"]
    assert "must be integers" in adapter.requests[2][1][-1].tool_results[0].content["error"]


def test_a_pre_2020_observation_is_shown_cited_to_the_aars_that_track_it(index):
    adapter = ScriptedAdapter(
        timeline_call(2019, 4),
        submit_with_timelines(
            "s",
            [point("Not implemented in 2023.", "2023-III-2")],
            [{"origin_year": 2019, "origin_observation": 4}],
        ),
    )

    answer = Answer.model_validate(final(ask(index, adapter)))

    (timeline,) = answer.timelines
    assert timeline.in_collection is False and timeline.raised is None
    assert [c.text for c in answer.key_points[0].citations] == [
        "CY 2023 AAR, Part III, CY 2019 Observation No. 4, p. 92"
    ]


def test_a_hit_gives_the_model_the_whole_observation_to_cite(index):
    adapter = ScriptedAdapter(
        search("Section 89"),  # only the description matches
        submit(
            "Summary.",
            [point("Management said liquidation is ongoing.", "2022-3-management_comment-1")],
        ),
    )

    answer = Answer.model_validate(final(ask(index, adapter)))

    _, messages, _ = adapter.requests[1]
    passages = messages[-1].tool_results[0].content
    assert [p["kind"] for p in passages] == [
        "description",
        "recommendations",
        "management_comment",
        "auditors_rejoinder",
    ]
    assert [p["matched"] for p in passages] == [True, False, False, False]
    assert all(p["citation"] == passages[0]["citation"] for p in passages)
    assert (
        answer.key_points[0].citations[0].text == "CY 2022 AAR, Part II, Observation No. 3, p. 73"
    )


def test_with_no_year_named_the_model_sees_the_newest_year_first(index):
    adapter = ScriptedAdapter(
        search("cash"), submit("Summary.", [point("Point.", "2022-3-description-1")])
    )

    ask(index, adapter)

    _, messages, _ = adapter.requests[1]
    years = [p["citation"].split()[1] for p in messages[-1].tool_results[0].content]
    assert years == sorted(years, reverse=True)
    assert {"2022", "2023"} <= set(years)


def test_the_model_can_filter_by_year_part_and_observation_number(index):
    adapter = ScriptedAdapter(
        search("", years=[2023], observation=5, parts=["II"]),
        search("cash", parts=["III"]),
        submit("Summary.", [point("Point.", IPSAS_5)]),
    )

    ask(index, adapter)

    _, messages, _ = adapter.requests[1]
    assert {p["citation"] for p in messages[-1].tool_results[0].content} == {CITATION_5}
    _, messages, _ = adapter.requests[2]
    assert {p["id"] for p in messages[-1].tool_results[0].content} == {"2023-III-1", "2024-III-1"}


def test_the_model_is_told_to_name_the_years_a_topic_appeared_in(index):
    adapter = ScriptedAdapter(search("cash"), submit("Summary.", [point("P.", IPSAS_5)]))

    ask(index, adapter)

    system, _, _ = adapter.requests[0]
    assert "newest first" in system
    assert "say which years" in system


def test_an_absurdly_large_number_in_a_tool_argument_is_reported_to_the_model_not_fatal(index):
    adapter = ScriptedAdapter(
        search("cash", years=[10**30]),
        timeline_call(10**30, 3),
        submit("s", [point("p", CASH_ADVANCES_2023)]),
    )

    events = ask(index, adapter)

    assert final(events)["type"] != "error"
    assert "error" in adapter.requests[1][1][-1].tool_results[0].content
    assert "error" in adapter.requests[2][1][-1].tool_results[0].content


# --- "What the City said": Management's side, from the AAPSI and APMT ------------------------


@pytest.fixture()
def monitored_index(tmp_path):
    records = write_fixture_records(tmp_path / "records", monitoring=FIXTURE_MONITORING)
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())
    with Index.open(tmp_path / "coa.sqlite", FakeEmbedder()) as opened:
        yield opened


def test_what_the_city_said_is_shown_apart_with_its_own_citations(monitored_index):
    adapter = ScriptedAdapter(
        timeline_call(2022, 3),
        submit_with_city(
            "COA assessed the cash advances recommendation as not implemented.",
            [point("COA assessed it as Not Implemented in the 2023 APMT.", "2023-APMT-1")],
            [point("Management reported it as fully implemented.", "2023-AAPSI-1", "2023-APMT-1")],
        ),
    )

    answer = Answer.model_validate(final(ask(monitored_index, adapter)))

    assert [p.text for p in answer.city_said] == ["Management reported it as fully implemented."]
    assert [c.text for c in answer.city_said[0].citations] == [
        "CY 2023 AAPSI, CY 2022 Observation No. 3, p. 2",
        "CY 2023 APMT, CY 2022 Observation No. 3, p. 2",
    ]
    assert [c.text for c in answer.key_points[0].citations] == [
        "CY 2023 APMT, CY 2022 Observation No. 3, p. 2"
    ]


def test_a_what_the_city_said_point_without_a_citation_is_removed(monitored_index):
    adapter = ScriptedAdapter(
        timeline_call(2022, 3),
        submit_with_city(
            "Summary.",
            [point("Grounded.", "2023-APMT-1")],
            [point("Uncited claim.", "2023-AAPSI-99"), point("Cited claim.", "2023-AAPSI-1")],
        ),
    )

    answer = Answer.model_validate(final(ask(monitored_index, adapter)))

    assert [p.text for p in answer.city_said] == ["Cited claim."]


def test_an_answer_without_what_the_city_said_has_none(monitored_index):
    adapter = ScriptedAdapter(
        timeline_call(2022, 3), submit("Summary.", [point("p", "2023-APMT-1")])
    )

    answer = Answer.model_validate(final(ask(monitored_index, adapter)))

    assert answer.city_said == []


def test_the_model_sees_the_disagreement_between_reported_status_and_COAs_status(monitored_index):
    adapter = ScriptedAdapter(timeline_call(2022, 3), submit("s", [point("p", "2023-APMT-1")]))

    ask(monitored_index, adapter)

    _, messages, _ = adapter.requests[1]
    timeline = messages[-1].tool_results[0].content["timeline"]
    validation = timeline["steps"][0]["validations"][0]
    assert validation["status"] == "Not Implemented"
    assert validation["reported_status_text"] == "Fully Implemented"
    assert validation["disagreement"] == (
        "Management reported this as implemented; COA assessed it as not implemented"
    )
    assert timeline["steps"][0]["action_plans"][0]["action_plan"].startswith("Demand letters")


def test_the_timeline_shown_with_the_answer_carries_the_action_plans_and_validations(
    monitored_index,
):
    adapter = ScriptedAdapter(
        timeline_call(2022, 3),
        ModelTurn(
            text=None,
            tool_calls=[
                ToolCall(
                    "submit_answer",
                    {
                        "covered": True,
                        "summary": "s",
                        "key_points": [point("p", "2023-APMT-1")],
                        "timelines": [{"origin_year": 2022, "origin_observation": 3}],
                    },
                )
            ],
        ),
    )

    events = ask(monitored_index, adapter)

    step = final(events)["timelines"][0]["steps"][0]
    assert step["action_plans"][0]["citation"] == "CY 2023 AAPSI, CY 2022 Observation No. 3, p. 2"
    assert step["validations"][0]["disagreement"].startswith("Management reported this as")


def test_the_model_can_search_the_aapsi_and_apmt_and_is_told_how_to_attribute_them(
    monitored_index,
):
    adapter = ScriptedAdapter(
        search("demand letters", parts=["AAPSI"]), submit("s", [point("p", "2023-AAPSI-1")])
    )

    ask(monitored_index, adapter)

    system, messages, tools = adapter.requests[0]
    parts = next(t for t in tools if t.name == "search").parameters["properties"]["parts"]
    assert parts["items"]["enum"] == ["II", "III", "AAPSI", "APMT"]
    assert "Reported Status" in system
    assert "never merge" in system.lower()
    assert "disagree" in system
    results = adapter.requests[1][1][-1].tool_results[0].content
    assert [r["id"] for r in results] == ["2023-AAPSI-1"]
    assert results[0]["citation"] == "CY 2023 AAPSI, CY 2022 Observation No. 3, p. 2"
