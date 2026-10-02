"""A Timeline: how one Audit Observation's Recommendations fared in each later AAR.

A timeline starts with the Originating Observation (cited to Part II) when it lies in the 2020-2024
collection, then has one step per later AAR whose Part III follows it up. Every status shown is
COA's Status of Implementation; Management's action is kept apart as Management's own account, and
the reason for partial or non-implementation is shown as the Part III column prints it. The text
and the Citations come from the index, never from the model.
"""

from __future__ import annotations

from pydantic import BaseModel


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
