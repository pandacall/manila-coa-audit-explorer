"""Seam 1: Part III references link to Part II observations, and the links are reported."""

from collections import Counter

import pytest

from coa_explorer.links import LINKED, OUT_OF_COLLECTION, UNMATCHED, build_links, report
from tests import fixtures as fx


@pytest.fixture(scope="module")
def links(part2, part3):
    return build_links(
        {year: record.to_dict() for year, record in part2.items()},
        {year: record.to_dict() for year, record in part3.items()},
    )


def test_every_tracked_observation_gets_a_link_and_none_is_unmatched(links, part3):
    assert len(links) == sum(len(p.observations) for p in part3.values())
    assert Counter(link.status for link in links) == {LINKED: 35, OUT_OF_COLLECTION: 95}


def test_references_to_observations_before_2020_are_out_of_the_collection(links):
    out = [link for link in links if link.status == OUT_OF_COLLECTION]
    assert {link.origin_year for link in out} == {2017, 2018, 2019}
    assert all(link.origin_citation is None for link in out)
    # CY 2020's own Part III follows up nothing inside the collection.
    assert {link.status for link in links if link.tracked_in == 2020} == {OUT_OF_COLLECTION}


def test_a_linked_reference_points_at_the_part_II_citation(links):
    link = next(
        link
        for link in links
        if (link.tracked_in, link.origin_year, link.origin_observation) == (2022, 2021, 3)
    )
    assert link.status == LINKED
    assert link.origin_citation == "CY 2021 AAR, Part II, Observation No. 3, pp. 80-83"


@pytest.mark.parametrize("origin_year", [2020, 2021, 2022])
def test_derived_pages_agree_exactly_with_the_following_years_part_III(links, origin_year):
    # ADR-0001: the page COA cites in the next AAR is the starting page derived from Word's layout.
    following = [
        link
        for link in links
        if link.status == LINKED
        and link.origin_year == origin_year
        and link.tracked_in == origin_year + 1
    ]
    assert following
    assert {link.drift for link in following} == {0}


def test_derived_pages_are_within_two_pages_of_the_following_years_part_III_for_2023(links):
    following = [
        link
        for link in links
        if link.status == LINKED and link.origin_year == 2023 and link.tracked_in == 2024
    ]
    assert len(following) == 6
    assert all(abs(link.drift) <= 2 for link in following), [link.drift for link in following]


def test_the_report_lists_the_drift_it_observed(links):
    drift = report(links)["page_drift"]

    assert len(drift) == 35
    in_2023 = [d for d in drift if d["origin"].startswith("CY 2023") and d["tracked_in"] == 2024]
    assert {d["drift"] for d in in_2023} == {0, -1, -2}


def test_unmatched_references_are_reported_with_a_reason_and_never_dropped():
    part2_records = {2022: fx.part2(2022, [fx.observation(2022, 1, "Cash", "Cash advances.")])}
    part3_records = {
        2023: {
            "aar_year": 2023,
            "observations": [
                fx.tracked_observation(2023, 2022, 1),
                fx.tracked_observation(2023, 2022, 9),  # Part II has no observation 9
                fx.tracked_observation(2023, None, None, reference="Observation, see above"),
                fx.tracked_observation(2023, 2023, 2),  # cannot follow up its own AAR
                fx.tracked_observation(2023, 2019, 4),
            ],
        }
    }

    links = build_links(part2_records, part3_records)

    assert [link.status for link in links] == [
        LINKED,
        UNMATCHED,
        UNMATCHED,
        UNMATCHED,
        OUT_OF_COLLECTION,
    ]
    unmatched = report(links)["unmatched"]
    assert [u["reference"] for u in unmatched] == [
        "CY 2022 AAR, Observation No. 9, Page 79",
        "Observation, see above",
        "CY 2023 AAR, Observation No. 2, Page 72",
    ]
    assert "no Audit Observation No. 9" in unmatched[0]["reason"]
    assert "does not give" in unmatched[1]["reason"]
    assert report(links)["counts"] == {LINKED: 1, OUT_OF_COLLECTION: 1, UNMATCHED: 3}
