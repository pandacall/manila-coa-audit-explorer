"""Small Part II records in the shape `coa-explorer extract` writes, for Seam 2 and Seam 3 tests."""

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


def write_fixture_records(directory: Path, years: dict[int, dict] | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for year, record in (years or FIXTURE_YEARS).items():
        (directory / f"{year}.json").write_text(json.dumps(record), encoding="utf-8")
    return directory
