"""Small AAPSI and APMT records in the shape `coa-explorer extract-aapsi` writes, for Seams 2 and 3."""

from __future__ import annotations

NORMALISED = {
    "Fully Implemented": "Implemented",
    "Partially Implemented": "Partially Implemented",
    "Not Implemented": "Not Implemented",
}


def row(
    year: int,
    document: str,
    number: int,
    origin: tuple[int, int],
    recommendation: str,
    reported: str | None = None,
    coa: str | None = None,
    **overrides,
) -> dict:
    """One AAPSI or APMT row of the `year` AAR. `reported` is Management's Reported Status as
    printed; `coa` is COA's Status of Implementation as printed (APMT only)."""
    page = 1 + number
    record = {
        "number": number,
        "page": page,
        "recommendation": recommendation,
        "action_plan": None,
        "person_responsible": None,
        "target_from": None,
        "target_to": None,
        "reported_status_text": reported,
        "reported_status": NORMALISED.get(reported or ""),
        "reason": None,
        "action_taken": None,
        "follow_up_date": None,
        "status_text": coa,
        "status": NORMALISED.get(coa or ""),
        "actual_from": None,
        "actual_to": None,
        "remarks": None,
        "citation": f"CY {year} {document}, CY {origin[0]} Observation No. {origin[1]}, p. {page}",
    }
    record.update(overrides)
    return record


def observation(
    year: int, document: str, origin: tuple[int, int], rows: list[dict], **overrides
) -> dict:
    """A block of AAPSI or APMT rows following one earlier (or the same year's) observation."""
    record = {
        "aar_year": year,
        "document": document,
        "reference": f"CY {origin[0]} AAR, Observation No. {origin[1]}, Page {70 + origin[1]}",
        "origin_year": origin[0],
        "origin_observation": origin[1],
        "origin_page_start": 70 + origin[1],
        "origin_page_end": 70 + origin[1],
        "summary": f"Table summary of CY {origin[0]} observation {origin[1]}.",
        "rows": rows,
    }
    record.update(overrides)
    return record


def record(year: int, document: str, observations: list[dict]) -> dict:
    return {
        "aar_year": year,
        "document": document,
        "source_file": f"fixture/{year}_{document}.pdf",
        "pdf_pages": 5,
        "observations": observations,
        "review_notes": [],
    }


ADVANCES = "Liquidate all cash advances promptly."
RECONCILE = "Reconcile the variances between bank confirmations and book balances."

# Management's plan for the CY 2022 cash advances, and COA's validation of it. In 2023 Management
# reported the recommendation as implemented and COA assessed it as not implemented: a disagreement.
# CY 2023 Observation No. 1 is raised, planned and validated in its own AAR; Management's "Ongoing"
# has no COA equivalent, so nothing is compared, and where both say "Fully Implemented" they agree.
FIXTURE_MONITORING = {
    "AAPSI": {
        2023: record(
            2023,
            "AAPSI",
            [
                observation(
                    2023,
                    "AAPSI",
                    (2022, 3),
                    [
                        row(
                            2023,
                            "AAPSI",
                            1,
                            (2022, 3),
                            ADVANCES,
                            reported="Fully Implemented",
                            action_plan="Demand letters to every advance holder.",
                            person_responsible="City Accountant",
                            target_from="2023",
                            target_to="2024",
                            action_taken="Demand letters were sent.",
                        )
                    ],
                    summary="Cash advances of P12.5 million had not been settled by year end.",
                ),
                observation(
                    2023,
                    "AAPSI",
                    (2023, 1),
                    [
                        row(
                            2023,
                            "AAPSI",
                            2,
                            (2023, 1),
                            RECONCILE,
                            reported="Ongoing",
                            action_plan="Monthly reconciliation of the Cash-in-Bank accounts.",
                            person_responsible="City Treasurer",
                        )
                    ],
                ),
            ],
        ),
        2024: record(
            2024,
            "AAPSI",
            [
                observation(
                    2024,
                    "AAPSI",
                    (2022, 3),
                    [
                        row(
                            2024,
                            "AAPSI",
                            1,
                            (2022, 3),
                            ADVANCES,
                            action_plan="Final notices to advance holders.",
                            person_responsible="City Accountant",
                        )
                    ],
                )
            ],
        ),
    },
    "APMT": {
        2023: record(
            2023,
            "APMT",
            [
                observation(
                    2023,
                    "APMT",
                    (2022, 3),
                    [
                        row(
                            2023,
                            "APMT",
                            1,
                            (2022, 3),
                            ADVANCES,
                            reported="Fully Implemented",
                            coa="Not Implemented",
                            follow_up_date="July 31, 2024",
                            remarks="Advances of P6 million remain unliquidated.",
                        )
                    ],
                ),
                observation(
                    2023,
                    "APMT",
                    (2023, 1),
                    [
                        row(
                            2023,
                            "APMT",
                            2,
                            (2023, 1),
                            RECONCILE,
                            reported="Ongoing",
                            coa="Partially Implemented",
                            follow_up_date="July 31, 2024",
                        ),
                        row(
                            2023,
                            "APMT",
                            3,
                            (2023, 1),
                            "Prepare monthly bank reconciliation statements.",
                            reported="Fully Implemented",
                            coa="Fully Implemented",
                        ),
                    ],
                ),
            ],
        ),
        2024: record(
            2024,
            "APMT",
            [
                observation(
                    2024,
                    "APMT",
                    (2022, 3),
                    [
                        row(
                            2024,
                            "APMT",
                            1,
                            (2022, 3),
                            ADVANCES,
                            coa="Not Implemented",
                            remarks="Pending appropriate action from Management.",
                        )
                    ],
                )
            ],
        ),
    },
}
