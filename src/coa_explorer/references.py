"""Normalise the ways COA writes a reference to an earlier Audit Observation.

Part III's Reference column says where a Prior Years' Recommendation was first raised, and COA's
spelling varies by year: "CY 2023 AAR, Observation No. 1, Page 71", "AAR 2020 / Observation No. 1 /
Pages 69-71", or just "Observation No. 1, Pages 63-67" under a heading row such as "AAR CY 2019".
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Reference:
    aar_year: int | None
    observation: int | None
    page_start: int | None
    page_end: int | None


_OBSERVATION = re.compile(r"\bObservation\s+No\.?\s*(\d+)", re.IGNORECASE)
_PAGES = re.compile(r"\b(?:Pages?|pp?\.)\s*(\d+)(?:\s*[-–—]\s*(\d+))?", re.IGNORECASE)
_YEAR = re.compile(r"\b((?:19|20)\d{2})\b")


def parse_reference(text: str) -> Reference:
    """The AAR year, observation number and pages in `text`; None for any part it does not carry."""
    observation = _OBSERVATION.search(text)
    pages = _PAGES.search(text)
    # The year is whatever precedes the observation and page parts, so a page number such as
    # "Page 2019" cannot be read as one.
    cut = min((m.start() for m in (observation, pages) if m), default=len(text))
    year = _YEAR.search(text[:cut])
    page_start = int(pages.group(1)) if pages else None
    page_end = int(pages.group(2)) if pages and pages.group(2) else page_start
    return Reference(
        aar_year=int(year.group(1)) if year else None,
        observation=int(observation.group(1)) if observation else None,
        page_start=page_start,
        page_end=page_end,
    )
