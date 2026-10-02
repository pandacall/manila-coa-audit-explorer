"""A Timeline: how one Audit Observation's Recommendations fared in each later AAR.

A timeline starts with the Originating Observation (cited to Part II) when it lies in the 2020-2024
collection, then has one step per later AAR whose Part III follows it up. Every status shown is
COA's Status of Implementation; Management's action is kept apart as Management's own account, and
the reason for partial or non-implementation is shown as the Part III column prints it. The text
and the Citations come from the index, never from the model.
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


class Step(BaseModel):
    aar_year: int
    follow_ups: list[FollowUp]


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
            *(f.key for step in self.steps for f in step.follow_ups),
        ]


def assemble_timeline(
    db: sqlite3.Connection, origin_year: int, origin_observation: int
) -> Timeline | None:
    """Assemble a timeline from the index's `follow_ups` rows and the Part II pieces.

    An observation that predates the collection still gets a timeline, cited to the 2020-2024 AARs
    whose Part III track it. None if neither Part II nor any Part III mentions the observation.
    """
    follow_ups = db.execute(
        "SELECT * FROM follow_ups WHERE origin_year = ? AND origin_observation = ?"
        " ORDER BY tracked_in, number",
        (origin_year, origin_observation),
    ).fetchall()
    raised = db.execute(
        "SELECT key, citation, title FROM pieces WHERE part = 'II' AND aar_year = ?"
        " AND observation_number = ? ORDER BY id LIMIT 1",
        (origin_year, origin_observation),
    ).fetchone()
    if not follow_ups and not raised:
        return None
    steps: list[Step] = []
    for row in follow_ups:
        if not steps or steps[-1].aar_year != row["tracked_in"]:
            steps.append(Step(aar_year=row["tracked_in"], follow_ups=[]))
        steps[-1].follow_ups.append(
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
    return Timeline(
        origin_year=origin_year,
        origin_observation=origin_observation,
        title=clip_title(raised["title"] if raised else follow_ups[0]["summary"]),
        in_collection=raised is not None,
        raised=Raised(**dict(raised)) if raised else None,
        steps=steps,
    )


def clip_title(text: str) -> str:
    """Trim to MAX_TITLE_CHARS at a word boundary, marking the cut."""
    if len(text) <= MAX_TITLE_CHARS:
        return text
    return text[: MAX_TITLE_CHARS - 1].rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
