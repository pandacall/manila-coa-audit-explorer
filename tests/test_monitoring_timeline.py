"""Seam 2: AAPSI and APMT rows are searchable and cited, and timelines keep COA's Status of
Implementation and Management's Reported Status apart, surfacing where they disagree."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coa_explorer.index import build_index
from coa_explorer.search import Index
from tests import fixtures as fx
from tests import monitoring_fixtures as mf
from tests.fake_embedder import FakeEmbedder

COMMITTED = Path(__file__).resolve().parents[1] / "data" / "extracted"


def build(tmp_path, monitoring=None, **records):
    path = fx.write_fixture_records(tmp_path / "records", monitoring=monitoring, **records)
    build_index(path, tmp_path / "coa.sqlite", FakeEmbedder())
    return Index.open(tmp_path / "coa.sqlite")


@pytest.fixture()
def index(tmp_path):
    with build(tmp_path, mf.FIXTURE_MONITORING) as opened:
        yield opened


# --- search ---------------------------------------------------------------------------------


def test_aapsi_rows_are_searchable_and_cited_to_the_aapsi_page(index):
    (piece,) = index.search("demand letters", parts=["AAPSI"])

    assert (piece.part, piece.kind, piece.aar_year) == ("AAPSI", "action_plan", 2023)
    assert piece.citation == "CY 2023 AAPSI, CY 2022 Observation No. 3, p. 2"
    assert (piece.origin_year, piece.origin_observation) == (2022, 3)
    assert piece.observation_number is None


def test_an_aapsi_piece_is_Managements_account_and_never_carries_a_Status_of_Implementation(index):
    (piece,) = index.search("demand letters", parts=["AAPSI"])

    assert piece.status is None  # `status` is COA's; Management's claim is a Reported Status
    assert "Action Plan (Management): Demand letters to every advance holder." in piece.text
    assert "Person or department responsible (Management): City Accountant" in piece.text
    assert "Target implementation (Management): 2023 to 2024" in piece.text
    assert "Reported Status (Management): Fully Implemented" in piece.text
    assert "Action taken or to be taken (Management): Demand letters were sent." in piece.text
    assert "Status of Implementation" not in piece.text


def test_apmt_rows_are_searchable_and_cited_with_COAs_status_labelled_as_COAs(index):
    (piece,) = index.search("unliquidated", parts=["APMT"], years=[2023])

    assert (piece.part, piece.kind) == ("APMT", "coa_validation")
    assert piece.citation == "CY 2023 APMT, CY 2022 Observation No. 3, p. 2"
    assert piece.status == "Not Implemented"
    assert "Status of Implementation (COA): Not Implemented" in piece.text
    assert "Date of COA's follow-up: July 31, 2024" in piece.text
    assert "COA's remarks: Advances of P6 million remain unliquidated." in piece.text
    assert "Reported Status (Management): Fully Implemented" in piece.text


def test_a_search_text_says_when_the_reported_status_and_COAs_status_disagree(index):
    (piece,) = index.search("unliquidated", parts=["APMT"], years=[2023])

    assert (
        "Reported Status and Status of Implementation disagree: Management reported this as "
        "implemented; COA assessed it as not implemented." in piece.text
    )
    pieces = index.search("monthly bank reconciliation statements", parts=["APMT"])
    agreeing = next(p for p in pieces if "Prepare monthly" in p.text)
    assert "disagree" not in agreeing.text


def test_the_status_filter_finds_COAs_assessments_in_the_apmt_too(index):
    pieces = index.search("", years=[2023], parts=["APMT"], status="Partially Implemented")

    assert [p.citation for p in pieces] == ["CY 2023 APMT, CY 2023 Observation No. 1, p. 3"]


def test_the_parts_filter_separates_the_aapsi_and_apmt_from_parts_II_and_III(index):
    found = {p.part for p in index.search("cash advances", limit=25)}

    assert {"II", "III", "AAPSI", "APMT"} <= found
    assert {p.part for p in index.search("cash advances", parts=["AAPSI"])} == {"AAPSI"}
    assert {p.part for p in index.search("cash advances", parts=["Apmt"])} == {"APMT"}


# --- timelines ------------------------------------------------------------------------------


def test_a_timeline_shows_Managements_action_plan_and_COAs_validation_in_their_own_aar(index):
    timeline = index.timeline(2022, 3)

    assert [s.aar_year for s in timeline.steps] == [2023, 2024]
    in_2023 = timeline.steps[0]
    (plan,) = in_2023.action_plans
    assert plan.action_plan == "Demand letters to every advance holder."
    assert plan.person_responsible == "City Accountant"
    assert (plan.target_from, plan.target_to) == ("2023", "2024")
    assert plan.citation == "CY 2023 AAPSI, CY 2022 Observation No. 3, p. 2"
    (validation,) = in_2023.validations
    assert validation.follow_up_date == "July 31, 2024"
    assert validation.citation == "CY 2023 APMT, CY 2022 Observation No. 3, p. 2"


def test_Status_of_Implementation_and_Reported_Status_are_kept_apart_in_the_timeline(index):
    in_2023 = index.timeline(2022, 3).steps[0]

    (plan,) = in_2023.action_plans
    (validation,) = in_2023.validations
    (part_iii,) = in_2023.follow_ups
    assert plan.reported_status_text == "Fully Implemented"  # Management's claim
    assert validation.status == "Not Implemented"  # COA's, from the APMT
    assert part_iii.status == "Partially Implemented"  # COA's, from Part III
    assert not hasattr(plan, "status")  # an action plan has no Status of Implementation
    assert validation.reported_status_text == "Fully Implemented"


def test_a_disagreement_between_Reported_Status_and_Status_of_Implementation_is_surfaced(index):
    (validation,) = index.timeline(2022, 3).steps[0].validations

    assert (
        validation.disagreement
        == "Management reported this as implemented; COA assessed it as not implemented"
    )


def test_no_disagreement_is_claimed_when_the_statuses_agree_or_cannot_be_compared(index):
    validations = index.timeline(2023, 1).steps[0].validations

    ongoing, agreeing = validations
    assert (ongoing.reported_status_text, ongoing.status) == ("Ongoing", "Partially Implemented")
    assert ongoing.disagreement is None  # "Ongoing" has no Status of Implementation equivalent
    assert (agreeing.reported_status, agreeing.status) == ("Implemented", "Implemented")
    assert agreeing.disagreement is None
    (blank,) = index.timeline(2022, 3).steps[1].validations
    assert (blank.reported_status_text, blank.disagreement) == (None, None)


def test_the_disagreement_wording_follows_the_two_statuses(tmp_path):
    rows = [
        mf.row(
            2023,
            "APMT",
            1,
            (2023, 1),
            "A.",
            reported="Partially Implemented",
            coa="Fully Implemented",
        ),
        mf.row(
            2023,
            "APMT",
            2,
            (2023, 1),
            "B.",
            reported="Fully Implemented",
            coa="Partially Implemented",
        ),
    ]
    monitoring = {
        "APMT": {2023: mf.record(2023, "APMT", [mf.observation(2023, "APMT", (2023, 1), rows)])}
    }

    with build(tmp_path, monitoring) as built:
        first, second = built.timeline(2023, 1).steps[0].validations

    assert first.disagreement == (
        "Management reported this as partially implemented; COA assessed it as implemented"
    )
    assert second.disagreement == (
        "Management reported this as implemented; COA assessed it as partially implemented"
    )


def test_an_observation_is_planned_and_validated_in_its_own_aar_after_it_was_raised(index):
    timeline = index.timeline(2023, 1)

    assert timeline.raised.citation == "CY 2023 AAR, Part II, Observation No. 1, p. 71"
    assert [s.aar_year for s in timeline.steps] == [2023]
    (step,) = timeline.steps
    assert step.follow_ups == []  # Part III only follows up earlier years' observations
    assert (
        step.action_plans[0].action_plan == "Monthly reconciliation of the Cash-in-Bank accounts."
    )
    assert len(step.validations) == 2


def test_every_step_of_a_timeline_cites_a_piece_the_model_can_retrieve_by_id(index):
    timeline = index.timeline(2022, 3)

    assert timeline.keys == [
        "2022-3-description-1",
        "2023-III-1",
        "2023-AAPSI-1",
        "2023-APMT-1",
        "2024-III-1",
        "2024-AAPSI-1",
        "2024-APMT-1",
    ]
    for key in timeline.keys:
        assert index.piece(key) is not None
    assert index.piece("2023-AAPSI-1").citation == timeline.steps[0].action_plans[0].citation
    assert index.piece("2023-APMT-1").citation == timeline.steps[0].validations[0].citation


def test_a_timeline_without_monitoring_records_is_as_before(tmp_path):
    with build(tmp_path) as built:
        timeline = built.timeline(2022, 3)

    assert [s.aar_year for s in timeline.steps] == [2023, 2024]
    assert all(s.action_plans == [] and s.validations == [] for s in timeline.steps)


def test_an_observation_only_the_aapsi_mentions_still_gets_a_timeline_cited_to_it(tmp_path):
    rows = [mf.row(2023, "AAPSI", 1, (2018, 15), "Reorganise the unit.", reported="Ongoing")]
    block = mf.observation(
        2023, "AAPSI", (2018, 15), rows, summary="The unit was created without approval."
    )
    monitoring = {"AAPSI": {2023: mf.record(2023, "AAPSI", [block])}}

    with build(tmp_path, monitoring, years=fx.FIXTURE_YEARS, part3={}) as built:
        timeline = built.timeline(2018, 15)

    assert timeline.in_collection is False
    assert timeline.title == "The unit was created without approval."
    assert timeline.steps[0].action_plans[0].citation == (
        "CY 2023 AAPSI, CY 2018 Observation No. 15, p. 2"
    )


def test_a_reference_that_matches_no_observation_keeps_its_rows_and_is_reported(tmp_path):
    rows = [mf.row(2023, "AAPSI", 1, (2023, 9), "Do the thing.", reported="Ongoing")]
    block = mf.observation(2023, "AAPSI", (2023, 9), rows)  # the fixture has no Observation No. 9
    monitoring = {"AAPSI": {2023: mf.record(2023, "AAPSI", [block])}}

    with build(tmp_path, monitoring) as built:
        timeline = built.timeline(2023, 9)
        (outcome,) = built._db.execute(
            "SELECT outcome, document FROM links WHERE document = 'AAPSI'"
        ).fetchall()

    assert timeline.in_collection is False
    assert timeline.steps[0].action_plans[0].recommendation == "Do the thing."
    assert tuple(outcome) == ("unmatched", "AAPSI")


# --- the committed records ------------------------------------------------------------------


@pytest.fixture(scope="module")
def real_index(tmp_path_factory):
    db = tmp_path_factory.mktemp("index") / "coa.sqlite"
    build_index(COMMITTED, db, FakeEmbedder())
    with Index.open(db) as opened:
        yield opened


def committed(document: str, year: int) -> dict:
    path = COMMITTED / document.lower() / f"{year}.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_every_committed_aapsi_and_apmt_row_is_indexed_and_cited_to_a_real_page(real_index):
    for document in ("AAPSI", "APMT"):
        for year in (2023, 2024):
            record = committed(document, year)
            expected = sum(len(o["rows"]) for o in record["observations"])
            found = real_index.search("", years=[year], parts=[document], limit=500)
            assert len(found) == expected, (document, year)
            assert all(1 <= p.page_start <= record["pdf_pages"] for p in found)
            assert all(p.citation.startswith(f"CY {year} {document}, ") for p in found)


def test_the_real_cash_in_bank_timeline_shows_the_disagreement_between_reported_and_COAs_status(
    real_index,
):
    # CY 2023 Observation No. 1, Recommendation 1.7.1: Management reported Fully Implemented in
    # the 2023 APMT's own columns; COA's validation says Not Implemented (checked on the scan).
    timeline = real_index.timeline(2023, 1)

    step = next(s for s in timeline.steps if s.aar_year == 2023)
    assert step.action_plans and step.validations
    first = step.validations[0]
    assert first.citation == "CY 2023 APMT, CY 2023 Observation No. 1, p. 1"
    assert (first.reported_status_text, first.status) == ("Fully Implemented", "Not Implemented")
    assert first.disagreement == (
        "Management reported this as implemented; COA assessed it as not implemented"
    )
    assert all(p.citation.startswith("CY 2023 AAPSI, ") for p in step.action_plans)


def test_a_real_observation_from_before_2020_gets_its_aapsi_and_apmt_entries_too(real_index):
    timeline = real_index.timeline(2018, 16)

    in_2023 = next(s for s in timeline.steps if s.aar_year == 2023)
    assert not timeline.in_collection
    assert in_2023.action_plans and in_2023.validations
