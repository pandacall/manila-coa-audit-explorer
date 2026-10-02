"""Seam 1: AAPSI and APMT table rows read from the scans become grouped, citable, linkable records.

The page reader (Gemini in production) is scripted here; no test calls a model.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from pypdf import PdfReader

from coa_explorer.aapsi import AAPSI, APMT, build_document, extract_document
from coa_explorer.links import LINKED, OUT_OF_COLLECTION, UNMATCHED, build_links, report
from tests import fixtures as fx

REPORTS = Path(__file__).resolve().parents[1] / "coa-audit-reports"


def raw(reference="", observations="", recommendations="", **cells) -> dict:
    """One row as the page reader returns it: every column a string, blank when blank."""
    row = dict.fromkeys(
        (
            "reference observations recommendations action_plan person_responsible target_from"
            " target_to status reason_for_delay action_taken follow_up_date coa_status actual_from"
            " actual_to remarks"
        ).split(),
        "",
    )
    row.update(reference=reference, observations=observations, recommendations=recommendations)
    row.update(cells)
    return row


def document(pages, year=2023, kind=AAPSI, notes=None):
    return build_document(year, kind, f"fixture/{year}_{kind}.pdf", len(pages), pages, notes or [])


# --- grouping -------------------------------------------------------------------------------


def test_rows_group_under_the_reference_printed_above_them_even_across_a_page_break():
    doc = document(
        [
            [
                raw("AAR 2023 Observation No. 1 Page 79", "1. Cash-in-Bank.", "1.7.1. Reconcile."),
                raw(recommendations="1.7.2. Cause timely preparation."),
            ],
            [
                raw(recommendations="1.7.3. Formulate a tool."),  # continues the block above
                raw(
                    "AAR 2023 Observation No. 2 Page 82", "2. Accounts payable.", "2.9.1. Identify."
                ),
            ],
        ]
    )

    assert [(o.origin_year, o.origin_observation) for o in doc.observations] == [
        (2023, 1),
        (2023, 2),
    ]
    first, second = doc.observations
    assert [r.recommendation for r in first.rows] == [
        "1.7.1. Reconcile.",
        "1.7.2. Cause timely preparation.",
        "1.7.3. Formulate a tool.",
    ]
    assert first.summary == "1. Cash-in-Bank."
    assert first.reference == "AAR 2023 Observation No. 1 Page 79"
    assert (first.origin_page_start, first.origin_page_end) == (79, 79)
    assert [r.recommendation for r in second.rows] == ["2.9.1. Identify."]


def test_every_row_is_numbered_and_cites_its_own_real_pdf_page():
    doc = document(
        [
            [raw("AAR 2023 Observation No. 1 Page 79", "1. Cash.", "1.7.1. Reconcile.")],
            [raw(recommendations="1.7.2. Cause timely preparation.")],
        ]
    )

    rows = doc.rows
    assert [(r.number, r.page) for r in rows] == [(1, 1), (2, 2)]
    assert rows[0].citation == "CY 2023 AAPSI, CY 2023 Observation No. 1, p. 1"
    assert rows[1].citation == "CY 2023 AAPSI, CY 2023 Observation No. 1, p. 2"


def test_an_apmt_row_is_cited_to_the_apmt():
    doc = document(
        [[raw("CY 2022 AAR, Observation No. 6, Page 81", "7. Remit taxes.", "Remit.")]],
        year=2024,
        kind=APMT,
    )

    assert doc.rows[0].citation == "CY 2024 APMT, CY 2022 Observation No. 6, p. 1"


def test_a_heading_row_supplies_the_year_of_references_that_omit_it():
    doc = document(
        [
            [
                raw("CY 2022 AAR"),
                raw("Observation No. 6, Page 81", "7. Remit taxes.", "Remit."),
                raw("Observation No. 7, Page 83", "8. Cases.", "Settle."),
            ]
        ],
        year=2024,
    )

    assert [(o.origin_year, o.origin_observation) for o in doc.observations] == [
        (2022, 6),
        (2022, 7),
    ]
    assert doc.observations[0].reference == "CY 2022 AAR Observation No. 6, Page 81"
    assert doc.observations[0].rows[0].citation == "CY 2024 AAPSI, CY 2022 Observation No. 6, p. 1"


def test_rows_with_nothing_in_them_are_dropped_but_nothing_else_is():
    doc = document(
        [
            [
                raw(),
                raw("AAR 2023 Observation No. 1 Page 79", "1. Cash.", "Reconcile."),
                raw(),
                raw(action_taken="stray note"),
            ]
        ]
    )

    assert len(doc.rows) == 2
    assert doc.rows[1].action_taken == "stray note"


def test_a_row_before_any_reference_is_kept_and_reported_as_unmatched():
    doc = document([[raw(recommendations="Orphan recommendation.")]])

    (observation,) = doc.observations
    assert (observation.origin_year, observation.origin_observation) == (None, None)
    assert observation.rows[0].citation == "CY 2023 AAPSI, p. 1"
    links = build_links({}, {}, {AAPSI: {2023: doc.to_dict()}})
    assert [link.outcome for link in links] == [UNMATCHED]
    assert links[0].document == AAPSI


def test_blank_cells_are_none_and_text_has_its_whitespace_tidied():
    doc = document(
        [
            [
                raw(
                    "AAR 2023 Observation No. 1 Page 79",
                    "1.  Cash   in bank\n was wrong.",
                    "Reconcile.",
                    person_responsible="  OCAT and CTO ",
                )
            ]
        ]
    )

    row = doc.rows[0]
    assert doc.observations[0].summary == "1. Cash in bank was wrong."
    assert row.person_responsible == "OCAT and CTO"
    assert row.action_plan is None
    assert row.target_from is None


# --- statuses -------------------------------------------------------------------------------


def test_Managements_reported_status_is_kept_as_printed_and_normalised_when_it_can_be():
    doc = document(
        [
            [
                raw("AAR 2023 Observation No. 1 Page 79", "1.", "a", status="Fully Implemented"),
                raw(recommendations="b", status="Ongoing"),
                raw(recommendations="c", status=""),
            ]
        ]
    )

    first, second, third = doc.rows
    assert (first.reported_status_text, first.reported_status) == (
        "Fully Implemented",
        "Implemented",
    )
    # "Ongoing" is Management's word and has no COA equivalent: kept, not translated.
    assert (second.reported_status_text, second.reported_status) == ("Ongoing", None)
    assert (third.reported_status_text, third.reported_status) == (None, None)


def test_an_apmt_row_carries_COAs_status_apart_from_Managements_reported_status():
    doc = document(
        [
            [
                raw(
                    "AAR 2023 Observation No. 1 Page 79",
                    "1. Cash.",
                    "Reconcile.",
                    status="Fully Implemented",  # Management's column
                    coa_status="Not Implemented",  # COA's validation
                    follow_up_date="July 31, 2024",
                    actual_from="2024",
                    actual_to="2024",
                    remarks="Bank reconciliation statements remain unadjusted.",
                )
            ]
        ],
        kind=APMT,
    )

    row = doc.rows[0]
    assert (row.reported_status_text, row.reported_status) == ("Fully Implemented", "Implemented")
    assert (row.status_text, row.status) == ("Not Implemented", "Not Implemented")
    assert row.follow_up_date == "July 31, 2024"
    assert (row.actual_from, row.actual_to) == ("2024", "2024")
    assert row.remarks == "Bank reconciliation statements remain unadjusted."


# --- links ----------------------------------------------------------------------------------


def test_references_link_to_part_II_or_are_reported_as_unmatched_or_out_of_the_collection():
    part2 = {2023: fx.part2(2023, [fx.observation(2023, 1, "Cash", "Cash.")])}
    doc = document(
        [
            [
                raw("AAR 2023 Observation No. 1 Page 79", "1.", "a"),
                raw("AAR 2023 Observation No. 9 Page 99", "9.", "b"),  # Part II has no No. 9
                raw("CY 2018 AAR, Observation No. 15, Page 91", "10.", "c"),
                raw("AAR 2024 Observation No. 1 Page 78", "1.", "d"),  # later than this AAPSI
            ]
        ]
    )

    links = build_links(part2, {}, {AAPSI: {2023: doc.to_dict()}})

    assert [link.outcome for link in links] == [LINKED, UNMATCHED, OUT_OF_COLLECTION, UNMATCHED]
    assert links[0].origin_citation == "CY 2023 AAR, Part II, Observation No. 1, p. 71"
    assert all(link.document == AAPSI for link in links)
    unmatched = report(links)["unmatched"]
    assert [u["document"] for u in unmatched] == [AAPSI, AAPSI]
    assert "no Audit Observation No. 9" in unmatched[0]["reason"]


# --- reading the scans ----------------------------------------------------------------------


class ScriptedReader:
    """Plays prepared rows per page and keeps the single-page PDFs it was handed."""

    def __init__(self, *reads: list[list[dict]]):
        self.reads = list(reads)  # one list of pages per pass
        self.pdfs: list[bytes] = []
        self.documents: list[str] = []
        self.calls = 0

    def read_page(self, pdf: bytes, document: str) -> list[dict]:
        self.pdfs.append(pdf)
        self.documents.append(document)
        passes = len(self.reads)
        page_index = (self.calls // passes) % len(self.reads[0])
        pass_index = self.calls % passes
        self.calls += 1
        return self.reads[pass_index][page_index]


def test_the_scanned_pdf_is_read_one_page_at_a_time_and_every_page_is_kept_in_order():
    pages = [[] for _ in range(7)]
    pages[1] = [raw("AAR 2023 Observation No. 1 Page 79", "1.", "a")]
    pages[2] = [raw(recommendations="b")]
    reader = ScriptedReader(pages)

    doc = extract_document(REPORTS, 2023, AAPSI, reader, passes=1)

    assert doc.pdf_pages == 7
    assert len(reader.pdfs) == 7
    assert all(len(PdfReader(io.BytesIO(pdf)).pages) == 1 for pdf in reader.pdfs)
    assert set(reader.documents) == {AAPSI}
    assert doc.source_file == (
        "Manila-City-Annual-Audit-Report-2023/AAPSI_APMT/ManilaCity2023_AAPSI.pdf"
    )
    assert [(r.page, r.recommendation) for r in doc.rows] == [(2, "a"), (3, "b")]


def test_two_reads_that_disagree_leave_a_note_for_the_human_reviewer():
    row = raw("AAR 2023 Observation No. 1 Page 79", "1. Cash.", "Reconcile unremitted taxes.")
    clipped = raw("AAR 2023 Observation No. 1 Page 79", "1. Cash.", "Reconcile.")
    blank = [[] for _ in range(7)]
    first = [list(p) for p in blank]
    second = [list(p) for p in blank]
    first[3] = [row]
    second[3] = [clipped]
    reader = ScriptedReader(first, second)

    doc = extract_document(REPORTS, 2023, AAPSI, reader, passes=2)

    assert [n["page"] for n in doc.review_notes] == [4]
    assert doc.review_notes[0]["only_in_first_read"] == ["unremitted", "taxes"]
    assert doc.review_notes[0]["only_in_second_read"] == []
    assert doc.rows[0].recommendation == "Reconcile unremitted taxes."  # the first read is kept


def test_two_reads_that_agree_leave_no_note_even_if_they_split_rows_differently():
    one_row = [raw("AAR 2023 Observation No. 1 Page 79", "1.", "1.7.1. Reconcile. 1.7.2. Cause.")]
    two_rows = [
        raw("AAR 2023 Observation No. 1 Page 79", "1.", "1.7.1. Reconcile."),
        raw(recommendations="1.7.2. Cause."),
    ]
    first = [[] for _ in range(7)]
    second = [[] for _ in range(7)]
    first[1], second[1] = one_row, two_rows

    doc = extract_document(REPORTS, 2023, AAPSI, ScriptedReader(first, second), passes=2)

    assert doc.review_notes == []


def test_a_read_that_fails_stops_the_extraction_instead_of_leaving_a_gap():
    class Failing:
        def read_page(self, pdf: bytes, document: str) -> list[dict]:
            raise RuntimeError("model unavailable")

    with pytest.raises(RuntimeError, match="model unavailable"):
        extract_document(REPORTS, 2023, AAPSI, Failing(), passes=1)


def test_a_status_cell_that_stacks_several_statuses_is_one_status_only_when_they_agree():
    doc = document(
        [
            [
                raw(
                    "AAR 2024 Observation No. 1 Page 78",
                    "1.",
                    "a. b. c.",
                    status="Fully implemented Fully implemented",
                    coa_status="Not Implemented Not implemented Not Implemented",
                ),
                raw(
                    recommendations="d. e.",
                    status="Ongoing Fully Implemented",
                    coa_status="Not Implemented Partially Implemented",
                ),
            ]
        ],
        year=2024,
        kind=APMT,
    )

    agreeing, mixed = doc.rows
    assert agreeing.status == "Not Implemented"
    assert agreeing.status_text == "Not Implemented Not implemented Not Implemented"  # as printed
    assert agreeing.reported_status == "Implemented"
    # Different statuses in one cell cannot be told apart by recommendation: none is claimed.
    assert (mixed.status, mixed.reported_status) == (None, None)
    assert mixed.status_text == "Not Implemented Partially Implemented"


# --- the committed, reviewed records --------------------------------------------------------

COMMITTED = REPORTS.parent / "data" / "extracted"


def committed(document: str, year: int) -> dict:
    return json.loads((COMMITTED / document.lower() / f"{year}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("document", "year", "pages", "rows"),
    [(AAPSI, 2023, 7, 24), (AAPSI, 2024, 25, 45), (APMT, 2023, 3, 28), (APMT, 2024, 12, 76)],
)
def test_the_committed_records_hold_every_row_with_real_pdf_pages(document, year, pages, rows):
    record = committed(document, year)

    assert record["pdf_pages"] == pages
    all_rows = [r for o in record["observations"] for r in o["rows"]]
    assert len(all_rows) == rows
    assert [r["number"] for r in all_rows] == list(range(1, rows + 1))
    assert all(1 <= r["page"] <= pages for r in all_rows)
    assert all(r["citation"].startswith(f"CY {year} {document}, ") for r in all_rows)
    assert all(r["citation"].endswith(f"p. {r['page']}") for r in all_rows)


def test_the_committed_records_report_no_unmatched_references():
    report = json.loads((COMMITTED / "monitoring-link-report.json").read_text(encoding="utf-8"))

    assert report["counts"] == {"linked": 69, "out_of_collection": 9, "unmatched": 0}
    assert report["unmatched"] == []
    assert {d["document"] for d in report["page_drift"]} == {AAPSI, APMT}


def test_the_committed_link_report_matches_the_committed_records():
    from coa_explorer.cli import monitoring_link_report

    committed_report = json.loads(
        (COMMITTED / "monitoring-link-report.json").read_text(encoding="utf-8")
    )

    assert monitoring_link_report(COMMITTED) == committed_report


def test_references_to_observations_before_2020_are_out_of_the_collection():
    out_of_collection = {
        (b["origin_year"], b["origin_observation"])
        for document in (AAPSI, APMT)
        for year in (2023, 2024)
        for b in committed(document, year)["observations"]
        if b["origin_year"] < 2020
    }

    assert out_of_collection == {(2019, 1), (2018, 15), (2018, 16)}


def test_the_2024_aapsi_has_no_rows_for_the_observations_the_scan_skips():
    # The printed table jumps from Observation No. 21 to 23 and from 26 to 29.
    numbers = {
        b["origin_observation"]
        for b in committed(AAPSI, 2024)["observations"]
        if b["origin_year"] == 2024
    }

    assert numbers.isdisjoint({22, 27, 28})
    assert {1, 21, 23, 26, 29} <= numbers


def test_the_2023_apmt_records_Management_and_COA_apart_for_the_first_recommendation():
    # Checked against the scan: Management's column says Fully Implemented, COA's says Not.
    first = committed(APMT, 2023)["observations"][0]["rows"][0]

    assert first["recommendation"].startswith("We recommend")
    assert (first["reported_status_text"], first["status_text"]) == (
        "Fully Implemented",
        "Not Implemented",
    )
    assert first["follow_up_date"] == "July 31, 2024"
