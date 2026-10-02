"""Seam 2: Part III rows are searchable and timelines are assembled from the link records."""

from __future__ import annotations

from pathlib import Path

import pytest

from coa_explorer.index import build_index
from coa_explorer.search import Index
from tests import fixtures as fx
from tests.fake_embedder import FakeEmbedder

COMMITTED = Path(__file__).resolve().parents[1] / "data" / "extracted"


@pytest.fixture()
def index(tmp_path):
    records = fx.write_fixture_records(tmp_path / "records")
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())
    with Index.open(tmp_path / "coa.sqlite") as opened:
        yield opened


def test_part_iii_rows_are_searchable_with_a_citation_to_their_own_aar_and_page(index):
    pieces = index.search("liquidate cash advances", parts=["III"], years=[2023])

    assert len(pieces) == 1
    piece = pieces[0]
    assert (piece.part, piece.aar_year, piece.kind) == ("III", 2023, "prior_years_recommendation")
    assert piece.citation == "CY 2023 AAR, Part III, CY 2022 Observation No. 3, p. 91"
    assert (piece.origin_year, piece.origin_observation) == (2022, 3)
    assert piece.status == "Partially Implemented"


def test_a_part_iii_piece_labels_whose_words_each_part_is(index):
    (piece,) = index.search("liquidate cash advances", parts=["III"], years=[2023])

    assert "Status of Implementation (COA): Partially Implemented" in piece.text
    assert "Management action: The City liquidated P8 million of the advances." in piece.text
    assert "Reason for partial or non-implementation: P4.5 million" in piece.text
    assert "Observation: Cash advances of P12.5 million had not been settled" in piece.text


def test_the_status_filter_lists_one_years_recommendations_with_that_status(index):
    pieces = index.search("", years=[2024], status="Not Implemented")

    assert [p.citation for p in pieces] == [
        "CY 2024 AAR, Part III, CY 2022 Observation No. 3, p. 91"
    ]
    assert index.search("", years=[2024], status="Implemented")[0].origin_year == 2019


def test_the_parts_filter_separates_part_ii_from_part_iii(index):
    assert {p.part for p in index.search("cash advances")} == {"II", "III"}
    assert {p.part for p in index.search("cash advances", parts=["II"])} == {"II"}
    assert {p.part for p in index.search("cash advances", parts=["III"])} == {"III"}


def test_the_observation_filter_is_about_part_ii_observation_numbers_only(index):
    pieces = index.search("", years=[2023], observation=3)

    assert pieces == []
    assert {p.part for p in index.search("", years=[2022], observation=3)} == {"II"}


def test_a_timeline_starts_at_the_part_ii_observation_and_follows_each_later_aar(index):
    timeline = index.timeline(2022, 3)

    assert timeline.title == "Unliquidated cash advances of the City"
    assert timeline.in_collection is True
    assert timeline.raised.citation == "CY 2022 AAR, Part II, Observation No. 3, p. 73"
    assert [step.aar_year for step in timeline.steps] == [2023, 2024]
    in_2023, in_2024 = (step.follow_ups[0] for step in timeline.steps)
    assert in_2023.status == "Partially Implemented"
    assert in_2023.citation == "CY 2023 AAR, Part III, CY 2022 Observation No. 3, p. 91"
    assert in_2024.status == "Not Implemented"
    assert in_2024.citation == "CY 2024 AAR, Part III, CY 2022 Observation No. 3, p. 91"


def test_a_timeline_keeps_COAs_status_apart_from_Managements_account(index):
    in_2023 = index.timeline(2022, 3).steps[0].follow_ups[0]

    assert in_2023.status == "Partially Implemented"  # COA's Status of Implementation
    assert in_2023.management_action == "The City liquidated P8 million of the advances."
    assert in_2023.reason == "P4.5 million was owed at year end."
    assert "Partially" not in in_2023.management_action
    note = index.timeline(2022, 3).steps[1].follow_ups[0].status_note
    assert note == "Reiterated in Part II, Observation No. 14, Page 130"


def test_every_step_cites_a_piece_the_model_can_retrieve_by_id(index):
    timeline = index.timeline(2022, 3)

    assert timeline.keys == ["2022-3-description-1", "2023-III-1", "2024-III-1"]
    for key in timeline.keys:
        assert index.piece(key) is not None
    assert index.piece("2023-III-1").citation == timeline.steps[0].follow_ups[0].citation


def test_an_observation_before_2020_still_gets_a_timeline_cited_to_the_tracking_aars(index):
    timeline = index.timeline(2019, 4)

    assert timeline.in_collection is False
    assert timeline.raised is None
    assert timeline.title == "Disbursement vouchers were not submitted to the Accounting Office."
    assert [(s.aar_year, s.follow_ups[0].status) for s in timeline.steps] == [
        (2023, "Not Implemented"),
        (2024, "Implemented"),
    ]
    assert [s.follow_ups[0].citation for s in timeline.steps] == [
        "CY 2023 AAR, Part III, CY 2019 Observation No. 4, p. 92",
        "CY 2024 AAR, Part III, CY 2019 Observation No. 4, p. 92",
    ]


def test_an_observation_nothing_follows_up_has_a_timeline_of_just_where_it_was_raised(index):
    timeline = index.timeline(2023, 5)

    assert timeline.raised.citation == "CY 2023 AAR, Part II, Observation No. 5, pp. 71-73"
    assert timeline.steps == []


def test_an_observation_that_nothing_mentions_has_no_timeline(index):
    assert index.timeline(2021, 99) is None


def test_a_reference_that_matches_no_observation_is_kept_in_its_own_timeline(tmp_path):
    part3 = {
        2023: fx.part3_record(
            2023,
            [
                fx.tracked_observation(
                    2023,
                    2022,
                    9,  # the fixture's CY 2022 Part II has no Observation No. 9
                    [fx.follow_up(2023, 1, (2022, 9), "Not Implemented", "Do the thing.")],
                )
            ],
        )
    }
    records = fx.write_fixture_records(tmp_path / "records", fx.FIXTURE_YEARS, part3)
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())

    with Index.open(tmp_path / "coa.sqlite") as built:
        timeline = built.timeline(2022, 9)

    assert timeline.in_collection is False
    assert timeline.steps[0].follow_ups[0].recommendation == "Do the thing."


def test_text_printed_once_for_several_recommendations_is_marked_shared(tmp_path):
    shared = fx.follow_up(
        2023,
        1,
        (2022, 3),
        "Implemented",
        "Do A.",
        management_action="Done.",
        shared=["management_action"],
    )
    part3 = {2023: fx.part3_record(2023, [fx.tracked_observation(2023, 2022, 3, [shared])])}
    records = fx.write_fixture_records(tmp_path / "records", fx.FIXTURE_YEARS, part3)
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())

    with Index.open(tmp_path / "coa.sqlite") as built:
        assert built.timeline(2022, 3).steps[0].follow_ups[0].shared == ["management_action"]


@pytest.fixture(scope="module")
def real_index(tmp_path_factory):
    db = tmp_path_factory.mktemp("index") / "coa.sqlite"
    build_index(COMMITTED, db, FakeEmbedder())
    with Index.open(db) as opened:
        yield opened


def test_every_part_iii_recommendation_is_indexed_by_status_with_COAs_totals(real_index):
    statuses = ("Implemented", "Partially Implemented", "Not Implemented")
    totals = {
        2020: (23, 32, 24),
        2021: (17, 25, 16),
        2022: (8, 27, 18),
        2023: (44, 0, 9),
        2024: (17, 0, 10),
    }
    for year, expected in totals.items():
        found = tuple(
            len(real_index.search("", years=[year], parts=["III"], status=s, limit=500))
            for s in statuses
        )
        assert found == expected, year


def test_a_whole_years_part_iii_can_be_listed_beyond_the_ranked_search_cut_off(real_index):
    # CY 2022's Part III has 53 recommendations, more than the 50 pieces a ranked search considers.
    pieces = real_index.search("", years=[2022], parts=["III"], limit=500)

    assert len(pieces) == 53


def test_the_real_cash_in_bank_observation_has_a_timeline_across_four_aars(real_index):
    # CY 2020 Observation No. 1 (cash-in-bank accounting errors) is followed up in 2021, 2022, 2023.
    timeline = real_index.timeline(2020, 1)

    assert timeline.in_collection
    assert timeline.raised.citation == "CY 2020 AAR, Part II, Observation No. 1, pp. 69-71"
    assert [step.aar_year for step in timeline.steps] == [2021, 2022, 2023]
    assert all(
        f.citation.startswith(f"CY {s.aar_year} AAR, Part III")
        for s in timeline.steps
        for f in s.follow_ups
    )


def test_a_real_observation_from_before_2020_is_shown_cited_to_the_aars_that_track_it(real_index):
    timeline = real_index.timeline(2019, 1)  # the unsubmitted disbursement vouchers

    assert not timeline.in_collection
    assert [step.aar_year for step in timeline.steps] == [2020, 2021, 2022, 2023, 2024]
    assert "disbursement vouchers" in timeline.title.lower()
