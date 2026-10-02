"""Seam 2 and 3 for the Notes to Financial Statements: searchable, cited, and used in answers."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from coa_explorer.answer import Answer, AnswerEngine
from coa_explorer.api import create_app
from coa_explorer.cli import main
from coa_explorer.index import build_index
from coa_explorer.search import MAX_NOTE_HITS, Index
from tests.fake_embedder import FakeEmbedder
from tests.fixtures import FIXTURE_NOTES, note, notes_record, write_fixture_records
from tests.scripted import ScriptedAdapter, point, search, submit

CASH_2022 = "CY 2022 AAR, Part I, Notes to Financial Statements, Note 4, pp. 33-34"


@pytest.fixture()
def index(tmp_path):
    records = write_fixture_records(tmp_path / "records", notes=FIXTURE_NOTES)
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())
    with Index.open(tmp_path / "coa.sqlite", FakeEmbedder()) as opened:
        yield opened


def test_a_note_is_found_by_its_words_and_cited_by_note_and_page(index):
    pieces = index.search("Cash Local Treasury", years=[2022], parts=["NOTES"])

    top = pieces[0]
    assert (top.aar_year, top.part, top.kind) == (2022, "NOTES", "note")
    assert top.title == "Note 4: Cash and Cash Equivalents"
    assert top.citation == CASH_2022
    assert (top.page_start, top.page_end) == (33, 34)
    assert "| Total | 8,325,730,232.46 | 10,852,325,069.13 |" in top.text


def test_a_note_is_found_by_its_title(index):
    pieces = index.search("Financial Liabilities", parts=["NOTES"])

    assert [p.citation for p in pieces] == [
        "CY 2022 AAR, Part I, Notes to Financial Statements, Note 12, p. 51"
    ]


def test_notes_come_newest_year_first_when_no_year_is_given(index):
    pieces = index.search("cash and cash equivalents", parts=["NOTES"])

    assert [p.aar_year for p in pieces] == [2023, 2023, 2022]
    assert {p.citation for p in pieces if p.aar_year == 2023} == {
        "CY 2023 AAR, Part I, Notes to Financial Statements, Note 4, p. 30",
        "CY 2023 AAR, Part I, Notes to Financial Statements, Note 4, p. 31",
    }


def test_each_passage_of_a_note_is_a_piece_with_its_own_citation(index):
    pieces = index.search("", years=[2023], parts=["NOTES"])

    assert [(p.key, p.citation[-5:]) for p in pieces] == [
        ("2023-N-4-1", "p. 30"),
        ("2023-N-4-2", "p. 31"),
    ]


def test_a_note_can_be_read_by_its_number(index):
    pieces = index.search("", years=[2022], parts=["NOTES"], observation=12)

    assert [p.title for p in pieces] == ["Note 12: Financial Liabilities (Current)"]


def test_a_note_number_is_not_an_observation_number_unless_the_notes_are_asked_for(index):
    # Part II 2023 has an Observation No. 1 and a Note 4 exists; asking for observation 4 with no
    # part must not return the Note.
    assert index.search("", years=[2023], observation=4) == []
    assert {p.part for p in index.search("", years=[2023], observation=1)} == {"II"}


def test_the_notes_stay_apart_from_the_other_parts(index):
    assert {p.part for p in index.search("cash", parts=["NOTES"])} == {"NOTES"}
    assert "NOTES" not in {p.part for p in index.search("cash", parts=["II"])}
    assert {p.part for p in index.search("notes", parts=["notes"])} <= {"NOTES"}


def test_expanding_a_note_hit_keeps_just_the_matching_passages(index):
    pieces = index.search("termination", years=[2023], parts=["NOTES"])

    [expanded] = index.expand(pieces)

    assert (expanded.aar_year, expanded.number) == (2023, 4)
    assert [p.key for p in expanded.pieces] == ["2023-N-4-2"]


def test_the_notes_are_built_into_the_index_by_the_index_step(tmp_path):
    records = write_fixture_records(tmp_path / "records", notes=FIXTURE_NOTES)

    assert (
        main(
            ["index", "--records", str(records), "--out", str(tmp_path / "x.sqlite")],
            embedder=FakeEmbedder(),
        )
        == 0
    )

    with Index.open(tmp_path / "x.sqlite") as opened:
        assert len(opened.search("", parts=["NOTES"])) == 4


# ---------------------------------------------------------------------------------------------
# Seam 3: an answer that cites a Note


def ask(index, adapter, question):
    client = TestClient(create_app(AnswerEngine(adapter, index)))
    with client.stream("POST", "/api/ask", json={"question": question}) as response:
        assert response.status_code == 200
        return [json.loads(line) for line in response.iter_lines() if line]


def test_an_answer_cites_the_note_it_drew_on(index):
    adapter = ScriptedAdapter(
        search("cash local treasury", years=[2022], parts=["NOTES"]),
        submit(
            "Cash held by the City Treasurer's Office rose in 2022.",
            [point("The Notes list Cash Local Treasury of P74,452,994.15.", "2022-N-4-1")],
        ),
    )

    events = ask(index, adapter, "What is behind the City's cash in 2022?")

    answer = Answer.model_validate(events[-1])
    [citation] = answer.key_points[0].citations
    assert citation.text == CASH_2022
    assert citation.title == "Note 4: Cash and Cash Equivalents"


def test_the_model_can_ask_for_the_notes_by_part_and_note_number(index):
    adapter = ScriptedAdapter(
        search("", years=[2022], parts=["NOTES"], observation=12),
        submit("s", [point("p", "2022-N-12-1")]),
    )

    ask(index, adapter, "What are the City's current financial liabilities?")

    system, messages, tools = adapter.requests[0]
    assert "NOTES" in system
    [search_tool] = [t for t in tools if t.name == "search"]
    assert "NOTES" in search_tool.parameters["properties"]["parts"]["items"]["enum"]
    results = adapter.requests[1][1][-1].tool_results[0].content
    assert [r["id"] for r in results] == ["2022-N-12-1"]
    assert results[0]["citation"].endswith("Note 12, p. 51")


def test_a_search_returns_only_the_best_passages_of_a_long_note_but_reading_it_returns_all(
    tmp_path,
):
    long_note = note(
        2023,
        10,
        "Property, Plant and Equipment (PPE)",
        [(39 + i, 39 + i, f"Depreciation of buildings in segment {i}.") for i in range(8)],
    )
    records = write_fixture_records(
        tmp_path / "records", notes={2023: notes_record(2023, [long_note])}
    )
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())

    with Index.open(tmp_path / "coa.sqlite", FakeEmbedder()) as opened:
        searched = opened.search("depreciation", parts=["NOTES"])
        read = opened.search("", years=[2023], parts=["NOTES"], observation=10)

    assert len(searched) == MAX_NOTE_HITS
    assert [p.key for p in read] == [f"2023-N-10-{i}" for i in range(1, 9)]
