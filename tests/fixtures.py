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


def write_fixture_records(
    directory: Path, years: dict[int, dict] | None = None, part3: dict[int, dict] | None = None
) -> Path:
    """Write Part II (and Part III) records in the layout `coa-explorer extract` writes."""
    if part3 is None:
        part3 = FIXTURE_PART3 if years is None else {}
    for part, records in (("part2", years or FIXTURE_YEARS), ("part3", part3)):
        (directory / part).mkdir(parents=True, exist_ok=True)
        for year, record in records.items():
            (directory / part / f"{year}.json").write_text(json.dumps(record), encoding="utf-8")
    return directory
