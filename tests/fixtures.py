"""Small Part II and Part III records in the shape `coa-explorer extract` writes, for Seam 2 and 3."""

from __future__ import annotations

import json
from pathlib import Path


def observation(year: int, number: int, title: str, description: str, **overrides) -> dict:
    record = {
        "aar_year": year,
        "number": number,
        "title": title,
        "section_heading": None,
        "description": description,
        "recommendations": [
            {
                "label": "a.",
                "text": f"Address observation {number}.",
                "lead_in": "We recommended that Management:",
            }
        ],
        "management_comment": None,
        "auditors_rejoinder": None,
        "page_start": 70 + number,
        "page_end": 70 + number,
        "citation": f"CY {year} AAR, Part II, Observation No. {number}, p. {70 + number}",
    }
    record.update(overrides)
    return record


def part2(year: int, observations: list[dict], **extra) -> dict:
    return {
        "aar_year": year,
        "source_file": f"fixture/{year}.docx",
        "observations": observations,
        "commendations": [],
        "other_items": [],
        **extra,
    }


FIXTURE_YEARS = {
    2022: part2(
        2022,
        [
            observation(
                2022,
                3,
                "Unliquidated cash advances of the City",
                "Cash advances totalling P12.5 million remained unliquidated as of December 31, 2022, "
                "contrary to Section 89 of PD No. 1445.",
                management_comment="Management commented that liquidation is ongoing.",
                auditors_rejoinder="We maintain that the advances be liquidated promptly.",
            ),
        ],
    ),
    2023: part2(
        2023,
        [
            observation(
                2023,
                1,
                "Cash-in-Bank balance not reconciled",
                "The accuracy of the Cash-in-Bank accounts balance could not be established because "
                "bank reconciliation statements were not prepared.",
                recommendations=[
                    {
                        "label": "a.",
                        "text": "Reconcile the variances between bank confirmations and book balances.",
                        "lead_in": "We recommended that Management direct the City Treasurer to:",
                    }
                ],
            ),
            observation(
                2023,
                5,
                "Financial statements not fully compliant with IPSAS 1",
                "The Financial Statements did not fully comply with IPSAS 1, Presentation of Financial "
                "Statements, as comparative information was omitted. The SEF accounts were also affected.",
                page_start=71,
                page_end=73,
                citation="CY 2023 AAR, Part II, Observation No. 5, pp. 71-73",
                management_comment="Management will present comparative information next year.",
            ),
        ],
    ),
}


def follow_up(
    year: int,
    number: int,
    origin: tuple[int, int],
    status: str,
    recommendation: str,
    **overrides,
) -> dict:
    """One Prior Years' Recommendation record of the `year` AAR's Part III."""
    origin_year, origin_observation = origin
    page = 90 + number
    record = {
        "number": number,
        "recommendation": recommendation,
        "status": status,
        "status_text": status,
        "status_note": None,
        "management_action": None,
        "reason": None,
        "shared": [],
        "page_start": page,
        "page_end": page,
        "citation": f"CY {year} AAR, Part III, CY {origin_year} Observation No. "
        f"{origin_observation}, p. {page}",
    }
    record.update(overrides)
    return record


def tracked_observation(
    year: int,
    origin_year: int | None,
    origin_observation: int | None,
    recommendations: list[dict] | None = None,
    **overrides,
) -> dict:
    """A block of Part III rows following up one earlier Audit Observation."""
    page = 70 + origin_observation if origin_observation else None
    reference = f"CY {origin_year} AAR, Observation No. {origin_observation}, Page {page}"
    record = {
        "aar_year": year,
        "reference": reference,
        "origin_year": origin_year,
        "origin_observation": origin_observation,
        "origin_page_start": page,
        "origin_page_end": page,
        "summary": f"Summary of CY {origin_year} observation {origin_observation}.",
        "recommendations": recommendations or [],
    }
    record.update(overrides)
    return record


def part3_record(year: int, observations: list[dict]) -> dict:
    return {
        "aar_year": year,
        "source_file": f"fixture/{year}.docx",
        "table_rows": len(observations) + 1,
        "stated_recommendations": sum(len(o["recommendations"]) for o in observations),
        "observations": observations,
    }


# CY 2022 Observation No. 3 (unliquidated cash advances) is followed up in both later AARs; the CY
# 2019 observation it sits beside predates the collection.
FIXTURE_PART3 = {
    2023: part3_record(
        2023,
        [
            tracked_observation(
                2023,
                2022,
                3,
                [
                    follow_up(
                        2023,
                        1,
                        (2022, 3),
                        "Partially Implemented",
                        "Liquidate all cash advances promptly.",
                        management_action="The City liquidated P8 million of the advances.",
                        reason="P4.5 million was owed at year end.",
                    )
                ],
                summary="Cash advances of P12.5 million had not been settled by year end.",
            ),
            tracked_observation(
                2023,
                2019,
                4,
                [
                    follow_up(
                        2023,
                        2,
                        (2019, 4),
                        "Not Implemented",
                        "Submit the disbursement vouchers to the Accounting Office.",
                        management_action="Management has no reply on the recommendation.",
                    )
                ],
                summary="Disbursement vouchers were not submitted to the Accounting Office.",
            ),
        ],
    ),
    2024: part3_record(
        2024,
        [
            tracked_observation(
                2024,
                2022,
                3,
                [
                    follow_up(
                        2024,
                        1,
                        (2022, 3),
                        "Not Implemented",
                        "Liquidate all cash advances promptly.",
                        status_note="Reiterated in Part II, Observation No. 14, Page 130",
                        reason="Advances of P6 million were owed.",
                    )
                ],
                summary="Cash advances of P12.5 million had not been settled by year end.",
            ),
            tracked_observation(
                2024,
                2019,
                4,
                [
                    follow_up(
                        2024,
                        2,
                        (2019, 4),
                        "Implemented",
                        "Submit the disbursement vouchers to the Accounting Office.",
                    )
                ],
                summary="Disbursement vouchers were not submitted to the Accounting Office.",
            ),
        ],
    ),
}


def front_matter_section(
    year: int, document: str, heading: str, text: str, pages: tuple[int, int], label=None
) -> dict:
    """One section of an Executive Summary (Roman pages) or an Auditor's Report (plain pages)."""
    roman = ["", "i", "ii", "iii", "iv", "v", "vi"]
    summary = document == "Executive Summary"
    start, end = pages
    printed = (lambda n: roman[n]) if summary else str
    span = printed(start) if start == end else f"{printed(start)}-{printed(end)}"
    where = f"p. {span}" if start == end else f"pp. {span}"
    citation = (
        f"CY {year} AAR, Executive Summary, Section {label}, {where}"
        if summary
        else f"CY {year} AAR, Part I, Auditor's Report, {where}"
    )
    return {
        "label": label,
        "heading": heading,
        "page_start": start,
        "page_end": end,
        "pages": span,
        "citation": citation,
        "text": text,
    }


def front_matter_record(year: int, document: str, sections: list[dict]) -> dict:
    summary = document == "Executive Summary"
    return {
        "aar_year": year,
        "document": document,
        "source_file": f"fixture/{year}-{'es' if summary else 'ar'}.docx",
        "text_source": "Word document",
        "page_format": "lowerRoman" if summary else "decimal",
        "sections": sections,
    }


FIXTURE_EXECUTIVE_SUMMARIES = {
    2022: front_matter_record(
        2022,
        "Executive Summary",
        [
            front_matter_section(
                2022,
                "Executive Summary",
                "Financial Highlights",
                "Assets of P73.694 billion and liabilities of P26.765 billion.",
                (1, 1),
                "B",
            ),
            front_matter_section(
                2022,
                "Executive Summary",
                "Auditor's Opinion on the Financial Statements",
                "The Auditor rendered a qualified opinion on the fairness of presentation.",
                (3, 4),
                "E",
            ),
        ],
    ),
    2023: front_matter_record(
        2023,
        "Executive Summary",
        [
            front_matter_section(
                2023,
                "Executive Summary",
                "Financial Highlights",
                "Assets of P81.680 billion and liabilities of P31.374 billion.",
                (1, 2),
                "B",
            ),
            front_matter_section(
                2023,
                "Executive Summary",
                "Operational Highlights",
                "Continued mass vaccination and the Kalinga sa Manila Project.",
                (2, 2),
                "C",
            ),
        ],
    ),
}

FIXTURE_AUDITORS_REPORTS = {
    2022: front_matter_record(
        2022,
        "Auditor's Report",
        [
            front_matter_section(
                2022, "Auditor's Report", "Report on the Financial Statements", "", (1, 1)
            ),
            front_matter_section(
                2022,
                "Auditor's Report",
                "Qualified Opinion",
                "In our opinion, except for the effects of the matter described, the financial "
                "statements present fairly the financial position of the City of Manila.",
                (1, 1),
            ),
            front_matter_section(
                2022,
                "Auditor's Report",
                "Emphasis of Matter Paragraph",
                "We draw attention to Note 31, the restated financial statements.",
                (2, 2),
            ),
        ],
    ),
    2023: front_matter_record(
        2023,
        "Auditor's Report",
        [
            front_matter_section(
                2023,
                "Auditor's Report",
                "Qualified Opinion",
                "In our opinion, except for the effects of the matter described in the Bases for "
                "Qualified Opinion, the financial statements present fairly.",
                (1, 1),
            ),
        ],
    ),
}


def note(year: int, number: int, title: str, passages: list[tuple[int, int, str]]) -> dict:
    """One Note to Financial Statements with its passages, each given as (first page, last page,
    text)."""

    def cite(start: int, end: int) -> str:
        where = f"p. {start}" if start == end else f"pp. {start}-{end}"
        return f"CY {year} AAR, Part I, Notes to Financial Statements, Note {number}, {where}"

    first = min(start for start, _, _ in passages)
    last = max(end for _, end, _ in passages)
    return {
        "number": number,
        "title": title,
        "page_start": first,
        "page_end": last,
        "citation": cite(first, last),
        "passages": [
            {"page_start": s, "page_end": e, "citation": cite(s, e), "text": text}
            for s, e, text in passages
        ],
    }


def notes_record(year: int, notes: list[dict]) -> dict:
    return {
        "aar_year": year,
        "document": "Notes to Financial Statements",
        "source_file": f"fixture/{year}.docx",
        "text_source": "Word document",
        "notes": notes,
    }


CASH_TABLE_2022 = (
    "| Accounts | 2022 | 2021 |\n| --- | --- | --- |\n| Cash on Hand |  |  |\n"
    "| Cash Local Treasury | 74,452,994.15 | 24,328,888.58 |\n"
    "| Total | 8,325,730,232.46 | 10,852,325,069.13 |"
)

FIXTURE_NOTES = {
    2022: notes_record(
        2022,
        [
            note(
                2022,
                4,
                "Cash and Cash Equivalents",
                [
                    (
                        33,
                        34,
                        CASH_TABLE_2022
                        + "\n\nThe Cash Local Treasury accounts for the cash received "
                        "by the City Treasurer's Office for deposit to the Authorized Government "
                        "Depository Bank.",
                    )
                ],
            ),
            note(
                2022,
                12,
                "Financial Liabilities (Current)",
                [(51, 51, "Payables are the accounts owed to suppliers at year end.")],
            ),
        ],
    ),
    2023: notes_record(
        2023,
        [
            note(
                2023,
                4,
                "Cash and Cash Equivalents",
                [
                    (
                        30,
                        30,
                        "| Accounts | 2023 | 2022 |\n| --- | --- | --- |\n"
                        "| Total | 9,304,414,447.87 | 8,325,730,232.46 |",
                    ),
                    (
                        31,
                        31,
                        "The decrease is due to the termination of the time deposit accounts.",
                    ),
                ],
            ),
        ],
    ),
}


def write_fixture_records(
    directory: Path,
    years: dict[int, dict] | None = None,
    part3: dict[int, dict] | None = None,
    summaries: dict[int, dict] | None = None,
    auditors_reports: dict[int, dict] | None = None,
    monitoring: dict[str, dict[int, dict]] | None = None,
    notes: dict[int, dict] | None = None,
) -> Path:
    """Write Part II, Part III, the Executive Summary, the Auditor's Report and (when given)
    AAPSI/APMT records in the layout `coa-explorer extract` and `extract-aapsi` write. Only the
    default fixtures include the Executive Summary and Auditor's Report. `monitoring` maps "AAPSI"
    and "APMT" to their records by AAR year. `notes` (by AAR year, none by default) are the Notes
    to Financial Statements."""
    if part3 is None:
        part3 = FIXTURE_PART3 if years is None else {}
    if summaries is None:
        summaries = FIXTURE_EXECUTIVE_SUMMARIES if years is None else {}
    if auditors_reports is None:
        auditors_reports = FIXTURE_AUDITORS_REPORTS if years is None else {}
    for part, records in (
        ("part2", years or FIXTURE_YEARS),
        ("part3", part3),
        ("executive_summary", summaries),
        ("auditors_report", auditors_reports),
        ("notes", notes or {}),
        *((document.lower(), by_year) for document, by_year in (monitoring or {}).items()),
    ):
        (directory / part).mkdir(parents=True, exist_ok=True)
        for year, record in records.items():
            (directory / part / f"{year}.json").write_text(json.dumps(record), encoding="utf-8")
    return directory
