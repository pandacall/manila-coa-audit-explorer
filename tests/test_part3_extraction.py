"""Seam 1 (corpus extraction) for Part III, on the real committed AARs.

Expected values come from the source documents themselves: the rows of each Word table, and the
totals COA prints in the intro paragraph of its own Part III ("Of the 79 prior years' audit
recommendations ... 23 were fully implemented, 32 partially implemented and 24 unimplemented").
"""

from collections import Counter

import pytest

TABLE_ROWS = {2020: 55, 2021: 87, 2022: 88, 2023: 33, 2024: 11}

# COA's own totals and breakdown per Part III: (Implemented, Partially Implemented, Not Implemented).
COA_TOTALS = {
    2020: (79, (23, 32, 24)),
    2021: (58, (17, 25, 16)),
    2022: (53, (8, 27, 18)),
    2023: (53, (44, 0, 9)),
    2024: (27, (17, 0, 10)),
}


def tracked(part3, year, origin_year, observation):
    return next(
        o
        for o in part3[year].observations
        if (o.origin_year, o.origin_observation) == (origin_year, observation)
    )


@pytest.mark.parametrize("year,rows", TABLE_ROWS.items())
def test_part_iii_row_counts_match_the_word_tables(part3, year, rows):
    assert part3[year].table_rows == rows


@pytest.mark.parametrize("year,expected", COA_TOTALS.items())
def test_one_record_per_recommendation_matches_the_totals_COA_prints(part3, year, expected):
    total, (implemented, partial, not_implemented) = expected
    records = part3[year].recommendations

    assert part3[year].stated_recommendations == total
    assert len(records) == total
    counts = Counter(r.status for r in records)
    assert (counts["Implemented"], counts["Partially Implemented"], counts["Not Implemented"]) == (
        implemented,
        partial,
        not_implemented,
    )
    assert [r.number for r in records] == list(range(1, total + 1))


def test_status_is_normalised_but_COAs_wording_is_kept(part3):
    assert {r.status_text for r in part3[2020].recommendations} == {
        "Fully Implemented",
        "Partially Implemented",
        "Not Implemented",
    }
    assert {r.status_text for r in part3[2023].recommendations} == {"Implemented", "Unimplemented"}
    assert {r.status for r in part3[2023].recommendations} == {"Implemented", "Not Implemented"}


@pytest.mark.parametrize("year", [2020, 2021, 2022, 2023, 2024])
def test_every_table_reference_names_an_earlier_observation(part3, year):
    for observation in part3[year].observations:
        assert observation.origin_year is not None, observation.reference
        assert observation.origin_observation is not None, observation.reference
        assert observation.origin_page_start is not None, observation.reference
        assert observation.origin_year < year


def test_the_year_heading_rows_of_the_2020_table_give_the_year_of_each_reference(part3):
    # CY 2020's Part III prints "AAR CY 2019" once, then "Observation No. 1, Pages 63-67" below it.
    assert {o.origin_year for o in part3[2020].observations} == {2017, 2018, 2019}
    first = part3[2020].observations[0]
    assert (first.origin_year, first.origin_observation) == (2019, 1)
    assert (first.origin_page_start, first.origin_page_end) == (63, 67)
    assert first.reference == "AAR CY 2019 Observation No. 1, Pages 63-67"


def test_2021_follows_up_all_five_2020_observations(part3):
    from_2020 = [o.origin_observation for o in part3[2021].observations if o.origin_year == 2020]
    assert from_2020 == [1, 2, 3, 4, 5]
    ref = tracked(part3, 2021, 2020, 1)
    assert (ref.origin_page_start, ref.origin_page_end) == (69, 71)


def test_a_recommendation_carries_COAs_status_and_Managements_action_and_reason(part3):
    record = tracked(part3, 2022, 2021, 1).recommendations[0]

    assert record.status == "Not Implemented"
    assert record.recommendation.startswith("We reiterated our recommendation that Management:")
    assert "Direct the OCAT to correct the accounting errors" in record.recommendation
    assert record.management_action == (
        "The OCAT made adjusting entries to correct the misstatements."
    )
    assert record.reason.startswith("Accounting errors with net understatement of the CiB accounts")
    assert record.shared == []
    assert record.citation == "CY 2022 AAR, Part III, CY 2021 Observation No. 1, pp. 84-85"


def test_a_note_under_the_status_stays_with_that_status(part3):
    record = tracked(part3, 2024, 2023, 5).recommendations[0]

    assert record.status == "Not Implemented"
    assert record.status_note == "Reiterated in Part II, Observation No. 14, Page 130"
    in_2020 = tracked(part3, 2020, 2019, 2).recommendations[0]
    assert in_2020.status == "Partially Implemented"
    assert in_2020.status_note.startswith("Recommendation is reiterated (Finding No. 1")


def test_observations_with_several_recommendations_get_one_record_each_in_order(part3):
    # CY 2019 Observation No. 8 (lease management) has seven recommendations; COA's table lists
    # three statuses in one row and four in the next.
    leases = tracked(part3, 2020, 2019, 8).recommendations
    assert [r.status_text for r in leases] == [
        "Partially Implemented",
        "Not Implemented",
        "Partially Implemented",
        "Not Implemented",
        "Partially Implemented",
        "Fully Implemented",
        "Not Implemented",
    ]
    assert leases[0].recommendation.startswith("We recommended that Management improve the City")
    assert "Directing the Committee on Patrimonial Properties" in leases[0].recommendation
    assert "Directing the OCAT to maintain SLs for each of the lessees" in leases[6].recommendation
    assert all(r.shared == [] for r in leases[:3])


def test_a_recommendation_split_across_two_Word_paragraphs_is_one_record(part3):
    dvs = tracked(part3, 2023, 2019, 1).recommendations
    assert len(dvs) == 4
    assert "all the 288 DVs in Paragraph 1.7 of Observation No. 1;" in dvs[0].recommendation
    assert dvs[0].citation == "CY 2023 AAR, Part III, CY 2019 Observation No. 1, pp. 101-103"


def test_text_that_cannot_be_matched_to_one_recommendation_is_shared_not_dropped(part3):
    accounts_payable = tracked(part3, 2023, 2022, 3).recommendations
    assert [r.shared for r in accounts_payable] == [["management_action"], ["management_action"]]
    assert accounts_payable[0].management_action == accounts_payable[1].management_action
    assert "The OCAT now maintains Accounts Payable monitoring" in (
        accounts_payable[0].management_action
    )

    dvs = tracked(part3, 2023, 2019, 1).recommendations
    assert all("reason" in r.shared for r in dvs)
    assert all(r.reason for r in dvs)


def test_a_reason_is_matched_to_the_recommendation_it_explains(part3):
    # CY 2019 Observation No. 9: eight Fully Implemented recommendations and one Partially, with a
    # single reason in the table.
    taxes = tracked(part3, 2020, 2019, 9).recommendations
    assert [r.status for r in taxes].count("Partially Implemented") == 1
    partial = next(r for r in taxes if r.status == "Partially Implemented")
    assert partial.reason.startswith("Verification with the CTO showed that in CY 2020")
    assert all(r.reason is None for r in taxes if r is not partial)


def test_the_page_is_the_page_of_the_row_in_the_table(part3):
    record = tracked(part3, 2024, 2023, 1).recommendations[0]
    assert record.page_start == 178
    assert record.page_end >= record.page_start
