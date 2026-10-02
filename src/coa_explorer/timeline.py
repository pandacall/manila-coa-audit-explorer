"""A Timeline: how one Audit Observation's Recommendations fared in each later AAR.

A timeline starts with the Originating Observation (cited to Part II) when it lies in the 2020-2024
collection, then has one step per AAR whose Part III, AAPSI or APMT follows it up. A step keeps
three kinds of entry apart, each attributed:

- `follow_ups`: COA's Status of Implementation from Part III, with Management's action beside it;
- `action_plans`: Management's own Action Plan and Reported Status from the AAPSI;
- `validations`: COA's Status of Implementation from the APMT, with the Reported Status the same
  row carries and, where the two differ, a sentence saying so.

Management's Reported Status is never merged into COA's Status of Implementation. The text and the
Citations come from the index, never from the model.
"""

from __future__ import annotations

import json
import sqlite3

from pydantic import BaseModel

MAX_TITLE_CHARS = 200


class Raised(BaseModel):
    """Where the observation was first raised, when that is in the collection."""

    key: str
    citation: str
    title: str


class FollowUp(BaseModel):
    """One Prior Years' Recommendation in one AAR's Part III."""

    key: str
    recommendation: str
    status: str  # COA's Status of Implementation: Implemented, Partially or Not Implemented
    status_text: str  # as COA printed it
    status_note: str | None
    management_action: str | None  # Management's own account
    reason: str | None  # the Part III column's reason for partial or non-implementation
    shared: list[str]  # columns whose text COA printed once for several recommendations
    citation: str


class ActionPlan(BaseModel):
    """One AAPSI row: what Management says it will do and claims it has done. All of it is
    Management's own account; `reported_status_text` is the Reported Status as printed."""

    key: str
    recommendation: str | None
    action_plan: str | None
    person_responsible: str | None
    target_from: str | None
    target_to: str | None
    reported_status_text: str | None
    reported_status: str | None  # as Implemented, Partially or Not Implemented, when it is one
    reason: (
        str | None
    )  # Management's reason for partial implementation, delay or non-implementation
    action_taken: str | None
    citation: str


class Validation(BaseModel):
    """One APMT row: COA's validation of Management's Action Plan. `status` is COA's Status of
    Implementation, the authoritative one; the Reported Status is Management's claim in the same
    row, and `disagreement` says so when the two differ."""

    key: str
    recommendation: str | None
    status: str | None  # COA's Status of Implementation: Implemented, Partially or Not Implemented
    status_text: str | None  # as COA printed it
    follow_up_date: str | None
    actual_from: str | None
    actual_to: str | None
    remarks: str | None  # COA's remarks
    reported_status_text: str | None  # Management's Reported Status, as printed
    reported_status: str | None
    disagreement: str | None
    citation: str


class Step(BaseModel):
    aar_year: int
    follow_ups: list[FollowUp] = []  # Part III
    action_plans: list[ActionPlan] = []  # AAPSI
    validations: list[Validation] = []  # APMT


class Timeline(BaseModel):
    origin_year: int
    origin_observation: int
    title: str
    in_collection: bool  # False when the observation predates the 2020-2024 AARs
    raised: Raised | None
    steps: list[Step]

    @property
    def keys(self) -> list[str]:
        """The ids of every piece this timeline cites."""
        return [
            *([self.raised.key] if self.raised else []),
            *(
                entry.key
                for step in self.steps
                for entry in (*step.follow_ups, *step.action_plans, *step.validations)
            ),
        ]


def assemble_timeline(
    db: sqlite3.Connection, origin_year: int, origin_observation: int
) -> Timeline | None:
    """Assemble a timeline from the index's `follow_ups` and `monitoring_rows` and the Part II
    pieces.

    An observation that predates the collection still gets a timeline, cited to the 2020-2024 AARs
    that track it. None if no Part II, Part III, AAPSI or APMT mentions the observation.
    """
    follow_ups = db.execute(
        "SELECT * FROM follow_ups WHERE origin_year = ? AND origin_observation = ?"
        " ORDER BY tracked_in, number",
        (origin_year, origin_observation),
    ).fetchall()
    monitoring = db.execute(
        "SELECT * FROM monitoring_rows WHERE origin_year = ? AND origin_observation = ?"
        " ORDER BY aar_year, number",
        (origin_year, origin_observation),
    ).fetchall()
    raised = db.execute(
        "SELECT key, citation, title FROM pieces WHERE part = 'II' AND aar_year = ?"
        " AND observation_number = ? ORDER BY id LIMIT 1",
        (origin_year, origin_observation),
    ).fetchone()
    if not follow_ups and not monitoring and not raised:
        return None
    steps: dict[int, Step] = {}

    def step(year: int) -> Step:
        return steps.setdefault(year, Step(aar_year=year))

    for row in follow_ups:
        step(row["tracked_in"]).follow_ups.append(
            FollowUp(
                key=row["key"],
                recommendation=row["recommendation"],
                status=row["status"],
                status_text=row["status_text"],
                status_note=row["status_note"],
                management_action=row["management_action"],
                reason=row["reason"],
                shared=json.loads(row["shared"]),
                citation=row["citation"],
            )
        )
    for row in monitoring:
        if row["document"] == "AAPSI":
            step(row["aar_year"]).action_plans.append(
                ActionPlan(**{name: row[name] for name in ActionPlan.model_fields})
            )
        else:
            fields = {name: row[name] for name in Validation.model_fields if name in row.keys()}
            step(row["aar_year"]).validations.append(
                Validation(
                    **fields, disagreement=disagreement(row["reported_status"], row["status"])
                )
            )
    first = (follow_ups or monitoring or [None])[0]
    return Timeline(
        origin_year=origin_year,
        origin_observation=origin_observation,
        title=clip_title(raised["title"] if raised else first["summary"]),
        in_collection=raised is not None,
        raised=Raised(**dict(raised)) if raised else None,
        steps=[steps[year] for year in sorted(steps)],
    )


def disagreement(reported: str | None, coa: str | None) -> str | None:
    """Where Management's Reported Status and COA's Status of Implementation (each one of
    Implemented, Partially Implemented or Not Implemented) differ, a sentence attributing each."""
    if reported is None or coa is None or reported == coa:
        return None
    return f"Management reported this as {reported.lower()}; COA assessed it as {coa.lower()}"


def clip_title(text: str) -> str:
    """Trim to MAX_TITLE_CHARS at a word boundary, marking the cut."""
    if len(text) <= MAX_TITLE_CHARS:
        return text
    return text[: MAX_TITLE_CHARS - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
