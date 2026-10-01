"""Seam 1 (corpus extraction) for Part II, on the real committed AARs.

Expected values come from the source documents themselves: COA's printed observation counts, the
Word files' own labels and cross-references, and the page numbers COA cites in the following
year's Part III.
"""

import pytest

OBSERVATION_COUNTS = {2020: 5, 2021: 6, 2022: 7, 2023: 7, 2024: 29}

# Observations whose AAR text carries a "Management comment(s)/action(s)" paragraph.
WITH_MANAGEMENT_COMMENT = {
    2020: {3, 5},
    2021: {1, 2, 3, 4, 5, 6},
    2022: {4, 6},
    2023: {2, 3, 4, 5},
    2024: {1, 2, 3, 5, 6, 8, 9, 10, 11, 12, 14, 15, 16, 17, 19, 23, 24, 25, 26, 28},
}

# The page on which COA's own later citations put each observation (Part III of the next AAR).
PAGES_COA_CITES = {
    2020: {1: 69, 2: 72, 3: 74, 4: 79, 5: 84},
    2021: {1: 74, 2: 79, 3: 80, 4: 83, 5: 86, 6: 88},
    2022: {1: 73, 2: 76, 3: 77, 4: 78, 5: 79, 6: 81},
}
PAGES_COA_CITES_2023 = {1: 71, 2: 75, 3: 77, 4: 82, 5: 85, 6: 88}


def observation(part2, year, number):
    return next(o for o in part2[year].observations if o.number == number)


@pytest.mark.parametrize("year,count", OBSERVATION_COUNTS.items())
def test_each_aar_has_the_audit_observations_COA_printed(part2, year, count):
    numbers = [o.number for o in part2[year].observations]
    assert numbers == list(range(1, count + 1))


def test_observation_title_is_the_bold_headline_of_the_observation(part2):
    assert observation(part2, 2020, 1).title.startswith(
        "Accounting errors in recording cash-in-bank (CiB) transactions amounting to P66.815 million"
    )
    assert observation(part2, 2024, 29).title.startswith(
        "Audit suspensions, disallowances and charges amounting to P42,538,364.47"
    )


def test_the_2024_commendations_are_commendations_and_not_audit_observations(part2):
    commendations = part2[2024].commendations
    assert len(commendations) == 7
    assert commendations[0].text.startswith(
        "The Multi-hazard Analysis of Nature’s Information for Localized Risk Analysis"
    )
    assert commendations[0].citation == "CY 2024 AAR, Part II, Commendation No. 1, p. 77"
    # The OCAT's adjustments are one commendation with four lettered items under it.
    assert len(commendations[5].text.splitlines()) == 5

    observation_text = " ".join(o.title + o.description for o in part2[2024].observations)
    for commendation in commendations:
        assert commendation.text.splitlines()[0] not in observation_text
    assert [o.number for o in part2[2024].observations] == list(range(1, 30))


@pytest.mark.parametrize("year", [2020, 2021, 2022, 2023])
def test_earlier_aars_have_no_commendations(part2, year):
    assert part2[year].commendations == []


def test_every_audit_observation_has_a_recommendation_except_the_one_COA_wrote_without(part2):
    # CY 2023 Observation No. 7 only reports the status of audit suspensions in a table; the AAR
    # carries no recommendation for it.
    without = {
        (year, o.number)
        for year, extracted in part2.items()
        for o in extracted.observations
        if not o.recommendations
    }
    assert without == {(2023, 7)}


def test_recommendations_are_split_into_the_items_COA_lists(part2):
    texts = [r.text for r in observation(part2, 2020, 1).recommendations]
    assert texts[:2] == [
        "Prepare the adjusting entry to record the 6,169 checks with a total amount of P5.913 "
        "million in the CkDJ; and",
        "Adopt preventive and corrective measures to address the deficiencies noted in Paragraph "
        "no. 1.7.",
    ]
    ppe = observation(part2, 2020, 2).recommendations
    assert [r.label for r in ppe] == ["a.", "b.", "c.", "d."]
    assert all(r.lead_in == "We recommended that Management:" for r in ppe)
    assert len(observation(part2, 2021, 4).recommendations) == 2


@pytest.mark.parametrize("year,numbers", WITH_MANAGEMENT_COMMENT.items())
def test_management_comment_is_captured_wherever_the_aar_has_one(part2, year, numbers):
    captured = {o.number for o in part2[year].observations if o.management_comment}
    assert captured == numbers


def test_management_comment_text_is_Managements_own_words(part2):
    assert "The Management adhered to the audit recommendations." in (
        observation(part2, 2021, 1).management_comment
    )
    assert "During the exit meeting, Management informed that the City will implement the PPAs" in (
        observation(part2, 2020, 5).management_comment
    )


def test_2020_auditors_rejoinder_is_captured_apart_from_the_management_comment(part2):
    obs = observation(part2, 2020, 3)
    assert obs.auditors_rejoinder.startswith(
        "3.16 Section 8 (f) of the JVO explicitly provides that each party shall be entitled to profits"
    )
    assert "B. Braun’s position was that" in obs.management_comment
    assert "Section 8 (f) of the JVO" not in obs.management_comment
    with_rejoinder = {
        (year, o.number)
        for year, extracted in part2.items()
        for o in extracted.observations
        if o.auditors_rejoinder
    }
    assert with_rejoinder == {(2020, 3)}


def test_sub_paragraph_numbers_match_the_printed_AAR(part2):
    # The AAR cross-refers to its own numbering ("para. 1.7", "para. 2.3.1", "para. 4.7").
    assert "1.7 This came about mainly because of the:" in observation(part2, 2020, 1).description
    assert "2.3.1 There are items of PPE recognized" in observation(part2, 2020, 2).description
    assert "4.7 Review of the JVA documents" in observation(part2, 2020, 4).description


def test_section_heading_is_the_heading_above_an_observation(part2):
    assert observation(part2, 2020, 1).section_heading == "FINANCIAL AND COMPLIANCE AUDIT"
    # Two headings are stacked above CY 2021 Observation No. 6 in the AAR, and both are kept.
    assert observation(part2, 2021, 6).section_heading.startswith(
        "COMPLIANCE WITH TAX LAWS AND OTHER REGULATORY REQUIREMENTS / Due to Bureau of Internal Revenue"
    )
    assert observation(part2, 2021, 5).section_heading == "FINANCIAL AND COMPLIANCE AUDIT"


def test_numbered_items_that_are_not_audit_observations_are_kept_apart(part2):
    # CY 2020's tax-remittance and audit-suspension sections are numbered 6 and 7 in the AAR but
    # are not bold Audit Observations; COA's Part III never cites them.
    assert [i.number for i in part2[2020].other_items] == [6, 7]
    assert [i.number for i in part2[2021].other_items] == [7]
    # ... and the heading above them does not bleed into Observation No. 5.
    assert observation(part2, 2020, 5).page_end == 86


def test_tables_are_kept_as_markdown_in_the_description(part2):
    description = observation(part2, 2020, 1).description
    assert "| Fund | Quantity | Amount |" in description
    assert "| SEF | 16 | P38,044,991.07 |" in description


@pytest.mark.parametrize("year", [2020, 2021, 2022])
def test_starting_page_is_the_page_COA_cites_for_the_observation(part2, year):
    derived = {o.number: o.page_start for o in part2[year].observations}
    assert {n: derived[n] for n in PAGES_COA_CITES[year]} == PAGES_COA_CITES[year]


def test_2023_starting_pages_are_within_two_pages_of_COAs_citations(part2):
    derived = {o.number: o.page_start for o in part2[2023].observations}
    for number, cited in PAGES_COA_CITES_2023.items():
        assert abs(derived[number] - cited) <= 2, (number, derived[number], cited)


def test_citation_is_written_the_way_COA_cites_itself(part2):
    assert (
        observation(part2, 2020, 1).citation == "CY 2020 AAR, Part II, Observation No. 1, pp. 69-71"
    )
    assert observation(part2, 2022, 7).citation == "CY 2022 AAR, Part II, Observation No. 7, p. 83"
