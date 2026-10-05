"""Seam 2: the retrieval tools, over an index built from small fixture records."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from coa_explorer.cli import main
from coa_explorer.index import build_index
from coa_explorer.search import Index
from tests.fake_embedder import FakeEmbedder
from tests.fixtures import observation, part2, write_fixture_records


@pytest.fixture()
def index(tmp_path):
    records = write_fixture_records(tmp_path / "records")
    db = tmp_path / "coa.sqlite"
    build_index(records, db, FakeEmbedder())
    with Index.open(db, FakeEmbedder()) as opened:
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
    pieces = index.search(
        "cash OR statements OR management OR recommended OR responsible OR transmit", limit=50
    )

    assert len(pieces) > 5
    for piece in pieces:
        pattern = {
            "II": r"CY \d{4} AAR, Part II, Observation No\. \d+, pp?\. \d+(-\d+)?",
            "III": r"CY \d{4} AAR, Part III, CY \d{4} Observation No\. \d+, pp?\. \d+(-\d+)?",
            "ES": r"CY \d{4} AAR, Executive Summary, Section [A-Z], pp?\. [ivx]+(-[ivx]+)?",
            "I": r"CY \d{4} AAR, Part I, Auditor's Report, pp?\. \d+(-\d+)?",
            "TL": r"CY \d{4} AAR, Transmittal Letter, pp?\. \d+(-\d+)?",
            "MR": r"CY \d{4} AAR, Part I, Management Responsibility for Financial Statements, p\. 1",
        }[piece.part]
        assert re.fullmatch(pattern, piece.citation), piece.citation


def test_unmatched_and_hostile_queries_return_nothing_rather_than_failing(index):
    assert index.search("zebra") == []
    assert index.search('"') == []
    assert index.search("IPSAS 1: NOT (what?) OR * NEAR") != []


def test_the_index_command_builds_the_sqlite_file_from_extracted_records(tmp_path, capsys):
    records = write_fixture_records(tmp_path / "records")
    db = tmp_path / "out" / "coa.sqlite"

    assert (
        main(["index", "--records", str(records), "--out", str(db)], embedder=FakeEmbedder()) == 0
    )

    assert "indexed" in capsys.readouterr().out
    with Index.open(db) as built:
        assert built.search("IPSAS 1")[0].observation_number == 5


def test_the_index_opens_from_a_relative_path(tmp_path, monkeypatch):
    records = write_fixture_records(tmp_path / "records")
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())
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
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())

    with Index.open(tmp_path / "coa.sqlite") as built:
        assert built.search("IPSAS 1", years=[2020, 2024])[0].aar_year == 2020


def test_everyday_wording_finds_the_passage_that_keywords_miss(index):
    pieces = index.search("money still unsettled")

    assert (pieces[0].aar_year, pieces[0].observation_number) == (2022, 3)


# ---------------------------------------------------------------------------------------------
# Executive Summary and Auditor's Report


def test_the_opinion_is_found_in_the_auditors_report_with_its_citation(index):
    pieces = index.search("qualified opinion", years=[2022], parts=["I"])

    assert [p.title for p in pieces] == ["Auditor's Report: Qualified Opinion"]
    opinion = pieces[0]
    assert (opinion.aar_year, opinion.part, opinion.kind) == (2022, "I", "auditors_report")
    assert opinion.citation == "CY 2022 AAR, Part I, Auditor's Report, p. 1"
    assert opinion.observation_number is None
    assert "except for the effects" in opinion.text


def test_a_year_filter_with_no_query_lists_the_executive_summary_in_reading_order(index):
    pieces = index.search("", years=[2023], parts=["ES"])

    assert [p.title for p in pieces] == [
        "Executive Summary: Financial Highlights",
        "Executive Summary: Operational Highlights",
    ]
    assert [p.citation for p in pieces] == [
        "CY 2023 AAR, Executive Summary, Section B, pp. i-ii",
        "CY 2023 AAR, Executive Summary, Section C, p. ii",
    ]
    assert (pieces[0].page_start, pieces[0].page_end) == (1, 2)


def test_executive_summary_highlights_without_a_year_come_newest_first(index):
    pieces = index.search("highlights", parts=["ES"])

    years = [p.aar_year for p in pieces]
    assert years == sorted(years, reverse=True)
    assert set(years) == {2022, 2023}


def test_parts_keep_the_summary_the_report_and_the_observations_apart(index):
    assert {p.part for p in index.search("financial statements", parts=["ES"])} == {"ES"}
    assert {p.part for p in index.search("financial statements", parts=["I"])} == {"I"}
    assert {p.part for p in index.search("financial statements", parts=["II"])} == {"II"}
    assert {p.part for p in index.search("financial statements", parts=["es"])} == {"ES"}


# Transmittal letters and Management Responsibility statements


def test_a_transmittal_letter_is_found_and_cited_by_its_pages(index):
    pieces = index.search("transmit Annual Audit Report", years=[2022], parts=["TL"])

    assert [p.title for p in pieces] == ["Transmittal Letter: Transmittal Letter"]
    letter = pieces[0]
    assert (letter.aar_year, letter.part, letter.kind) == (2022, "TL", "transmittal_letter")
    assert letter.citation == "CY 2022 AAR, Transmittal Letter, pp. 1-2"
    assert (letter.page_start, letter.page_end) == (1, 2)
    assert letter.observation_number is None


def test_a_management_responsibility_statement_is_found_and_cited(index):
    pieces = index.search("responsible for all information", parts=["MR"])

    assert [p.citation for p in pieces] == [
        "CY 2023 AAR, Part I, Management Responsibility for Financial Statements, p. 1"
    ]
    assert (pieces[0].part, pieces[0].kind) == ("MR", "management_responsibility")


def test_the_short_documents_stay_out_of_the_other_parts(index):
    assert {p.part for p in index.search("financial statements", parts=["I"])} == {"I"}
    assert {p.part for p in index.search("Qualified Opinion", parts=["ES", "I"])} <= {"ES", "I"}
    everything = {p.part for p in index.search("", years=[2023], parts=["TL", "MR"])}
    assert everything == {"TL", "MR"}


def test_a_year_filter_lists_that_years_letter_and_statement(index):
    pieces = index.search("", years=[2023], parts=["TL", "MR"])

    assert sorted((p.aar_year, p.part) for p in pieces) == [(2023, "MR"), (2023, "TL")]


def test_a_heading_with_no_text_makes_no_piece(index):
    pieces = index.search("", years=[2022], parts=["I"])

    assert "Auditor's Report: Report on the Financial Statements" not in [p.title for p in pieces]
    assert len(pieces) == 2


def test_the_heading_of_a_section_is_searchable(index):
    pieces = index.search("Operational Highlights")

    assert pieces[0].citation == "CY 2023 AAR, Executive Summary, Section C, p. ii"


def test_expanding_a_front_matter_hit_keeps_just_the_matching_sections(index):
    pieces = index.search("qualified opinion", years=[2022], parts=["ES", "I"])

    expanded = index.expand(pieces)

    assert sorted((o.aar_year, o.number) for o in expanded) == [(2022, None), (2022, None)]
    assert {o.pieces[0].part for o in expanded} == {"ES", "I"}


def observations_of(pieces):
    """(year, observation number) of each distinct observation, in result order."""
    seen = []
    for piece in pieces:
        identity = (piece.aar_year, piece.observation_number)
        if identity not in seen:
            seen.append(identity)
    return seen


def test_keyword_and_vector_results_are_merged_into_one_ranking(index):
    # "IPSAS 1" is a keyword hit on 2023 No. 5; "unsettled" a vector-only hit on 2022 No. 3.
    pieces = index.search("IPSAS 1 unsettled")

    assert set(observations_of(pieces)) == {(2023, 5), (2022, 3)}


def test_a_piece_found_by_both_keyword_and_vector_search_outranks_one_found_by_either(index):
    # 2023 No. 1 matches "bank reconciliation" by keyword and by meaning; No. 5 only by "statements".
    pieces = index.search("bank reconciliation statements", years=[2023])

    assert observations_of(pieces)[0] == (2023, 1)


def test_the_year_filter_applies_to_vector_results_too(index):
    assert index.search("unsettled", years=[2023]) == []
    assert observations_of(index.search("unsettled", years=[2022])) == [(2022, 3)]


def test_the_part_filter_keeps_only_that_part(index):
    assert index.search("IPSAS 1", parts=["II"])
    assert index.search("IPSAS 1", parts=["III"]) == []
    assert index.search("unsettled", parts=["III"]) == []


def test_an_observation_can_be_looked_up_directly_by_year_and_number(index):
    pieces = index.search("", years=[2023], observation=5)

    assert observations_of(pieces) == [(2023, 5)]
    assert [piece.kind for piece in pieces] == [
        "description",
        "recommendations",
        "management_comment",
    ]


def test_the_observation_filter_narrows_a_query_to_that_observation_number(index):
    pieces = index.search("cash", observation=3)

    assert observations_of(pieces) == [(2022, 3)]


def test_with_no_year_named_results_span_all_years_newest_first(tmp_path):
    most_relevant = observation(
        2020, 1, "Bank reconciliation", "Bank reconciliation statements were not prepared."
    )
    less = observation(2022, 1, "Bank accounts", "The bank balance could not be reconciled.")
    least = observation(2024, 1, "Cash controls", "Controls over bank deposits were weak.")
    records = write_fixture_records(
        tmp_path / "records",
        {
            2020: part2(2020, [most_relevant]),
            2022: part2(2022, [less]),
            2024: part2(2024, [least]),
        },
    )
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())

    with Index.open(tmp_path / "coa.sqlite", FakeEmbedder()) as built:
        everywhere = observations_of(built.search("bank reconciliation statements"))
        two_years = observations_of(
            built.search("bank reconciliation statements", years=[2020, 2022])
        )
        one_year = observations_of(built.search("bank reconciliation statements", years=[2022]))

    assert everywhere == [(2024, 1), (2022, 1), (2020, 1)]
    assert two_years == [(2020, 1), (2022, 1)]  # named years: most relevant first
    assert one_year == [(2022, 1)]


def test_a_direct_lookup_without_a_year_lists_every_year_newest_first(tmp_path):
    records = write_fixture_records(
        tmp_path / "records",
        {y: part2(y, [observation(y, 5, "Topic", "Text.")]) for y in (2021, 2023, 2022)},
    )
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())

    with Index.open(tmp_path / "coa.sqlite") as built:
        assert observations_of(built.search("", observation=5)) == [(2023, 5), (2022, 5), (2021, 5)]


def test_a_hit_on_any_piece_expands_to_the_whole_observation(index):
    hits = index.search("Section 89")  # only the description mentions it

    (whole,) = index.expand(hits)

    assert [piece.kind for piece in whole.pieces] == [
        "description",
        "recommendations",
        "management_comment",
        "auditors_rejoinder",
    ]
    assert whole.matched == {"2022-3-description-1"}
    assert (whole.aar_year, whole.number) == (2022, 3)
    assert whole.citation == "CY 2022 AAR, Part II, Observation No. 3, p. 73"


def test_several_hits_in_one_observation_expand_to_it_once(index):
    hits = index.search("Management cash advances liquidated", years=[2022])

    assert len(hits) > 1
    assert [(o.aar_year, o.number) for o in index.expand(hits)] == [(2022, 3)]


def test_a_search_returns_at_most_the_asked_number_of_observations(tmp_path):
    records = write_fixture_records(
        tmp_path / "records",
        {
            2023: part2(
                2023, [observation(2023, n, "Cash", f"Cash matter {n}.") for n in range(1, 7)]
            )
        },
    )
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())

    with Index.open(tmp_path / "coa.sqlite", FakeEmbedder()) as built:
        assert len(observations_of(built.search("cash", limit=3))) == 3
        assert len(observations_of(built.search("cash"))) == 5


def test_search_falls_back_to_keywords_when_the_embedder_fails(tmp_path, caplog):
    class Broken(FakeEmbedder):
        def embed_query(self, text):
            raise RuntimeError("embedding service down")

    records = write_fixture_records(tmp_path / "records")
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())

    with Index.open(tmp_path / "coa.sqlite", Broken()) as built:
        assert observations_of(built.search("IPSAS 1")) == [(2023, 5)]
    assert "embedding the query failed" in caplog.text


def test_an_index_and_an_embedder_of_different_dimensions_are_rejected(tmp_path):
    class Wider(FakeEmbedder):
        dimensions = 512

    records = write_fixture_records(tmp_path / "records")
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())

    with pytest.raises(ValueError, match="rebuild"):
        Index.open(tmp_path / "coa.sqlite", Wider())


def test_part_names_are_matched_whatever_their_case(index):
    assert index.search("IPSAS 1", parts=["ii"])


def test_a_vector_match_that_is_not_close_is_dropped(index):
    assert index.search("potholes") == []
