"""Seam 2: the retrieval tools, over an index built from small fixture records."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from coa_explorer.cli import main
from coa_explorer.index import build_index
from coa_explorer.search import Index
from tests.fixtures import observation, part2, write_fixture_records


@pytest.fixture()
def index(tmp_path):
    records = write_fixture_records(tmp_path / "records")
    db = tmp_path / "coa.sqlite"
    build_index(records, db)
    with Index.open(db) as opened:
        yield opened


def test_keyword_search_hits_an_exact_term_with_a_complete_citation(index):
    pieces = index.search("IPSAS 1")

    top = pieces[0]
    assert top.aar_year == 2023
    assert top.observation_number == 5
    assert top.citation == "CY 2023 AAR, Part II, Observation No. 5, pp. 71-73"
    assert "IPSAS 1" in top.text


def test_description_recommendations_and_management_comment_are_separate_pieces(index):
    pieces = index.search("Section 89 liquidate", years=[2022])

    kinds = {piece.kind: piece for piece in pieces}
    assert {"description", "management_comment", "auditors_rejoinder"} <= set(kinds)
    comment = kinds["management_comment"]
    assert "liquidation is ongoing" in comment.text
    assert "Section 89" not in comment.text
    description = kinds["description"]
    assert (comment.aar_year, comment.observation_number) == (2022, 3)
    assert (description.aar_year, description.observation_number) == (2022, 3)
    assert comment.citation == description.citation


def test_recommendations_are_their_own_piece(index):
    pieces = index.search("Reconcile variances bank confirmations")

    top = pieces[0]
    assert top.kind == "recommendations"
    assert top.observation_number == 1
    assert "We recommended that Management direct the City Treasurer to:" in top.text


def test_year_filter_restricts_results(index):
    pieces = index.search("cash", years=[2022])

    assert pieces
    assert {piece.aar_year for piece in pieces} == {2022}


def test_observation_filter_without_a_query_returns_the_whole_observation(index):
    pieces = index.search("", years=[2023], observation=5)

    assert {piece.observation_number for piece in pieces} == {5}
    assert {piece.kind for piece in pieces} == {
        "description",
        "recommendations",
        "management_comment",
    }


def test_every_result_carries_a_complete_citation(index):
    pieces = index.search("cash OR statements OR management OR recommended", limit=50)

    assert len(pieces) > 5
    for piece in pieces:
        assert re.fullmatch(
            r"CY \d{4} AAR, Part II, Observation No\. \d+, pp?\. \d+(-\d+)?", piece.citation
        ), piece.citation
        assert piece.part == "II"


def test_unmatched_and_hostile_queries_return_nothing_rather_than_failing(index):
    assert index.search("zebra") == []
    assert index.search('"') == []
    assert index.search("IPSAS 1: NOT (what?) OR * NEAR") != []


def test_the_index_command_builds_the_sqlite_file_from_extracted_records(tmp_path, capsys):
    records = write_fixture_records(tmp_path / "records")
    db = tmp_path / "out" / "coa.sqlite"

    assert main(["index", "--records", str(records), "--out", str(db)]) == 0

    assert "indexed" in capsys.readouterr().out
    with Index.open(db) as built:
        assert built.search("IPSAS 1")[0].observation_number == 5


def test_the_index_opens_from_a_relative_path(tmp_path, monkeypatch):
    records = write_fixture_records(tmp_path / "records")
    build_index(records, tmp_path / "coa.sqlite")
    monkeypatch.chdir(tmp_path)

    with Index.open(Path("coa.sqlite")) as opened:
        assert opened.search("IPSAS 1")


def test_an_exact_phrase_outranks_pieces_that_only_share_its_words(tmp_path):
    scattered = observation(
        2024, 1, "Unrelated", "IPSAS 12 was applied. Paragraph 1 refers to Section 7 of IPSAS 3."
    )
    exact = observation(2020, 2, "Presentation", "The statements did not follow IPSAS 1 in 2020.")
    records = write_fixture_records(
        tmp_path / "records", {2020: part2(2020, [exact]), 2024: part2(2024, [scattered])}
    )
    build_index(records, tmp_path / "coa.sqlite")

    with Index.open(tmp_path / "coa.sqlite") as built:
        assert built.search("IPSAS 1")[0].aar_year == 2020
