"""Reading Citations back: which source one points at, and on which pages.

A Citation names its source by AAR year, Part, and the Audit Observation (for Part III, the
Originating Observation) it concerns; the pages are a best-effort pointer (ADR-0001). So two
Citations are the same source when their `source` matches, and `page_start` may drift.
"""

from __future__ import annotations

import re
from typing import NamedTuple

CITATION = re.compile(
    r"^CY (?P<year>\d{4}) AAR, Part (?P<part>IV|III|II|I)"
    r"(?:, (?:CY (?P<origin>\d{4}) )?(?P<label>[A-Za-z]+) No\. (?P<number>\d+))?"
    r"(?:, pp?\. (?P<start>\d+)(?:-(?P<end>\d+))?)?$"
)


class Source(NamedTuple):
    aar_year: int
    part: str
    origin_year: int | None  # Part III: the AAR year of the Originating Observation
    label: str | None  # "Observation", or "Item"/"Commendation" for Part II's other lists
    number: int | None


class ParsedCitation(NamedTuple):
    source: Source
    page_start: int | None
    page_end: int | None


def parse_citation(text: str) -> ParsedCitation:
    """Parse a Citation in COA's format, e.g. 'CY 2023 AAR, Part II, Observation No. 5, p. 71'."""
    match = CITATION.match(text.strip())
    if not match:
        raise ValueError(
            f"not a Citation in COA's format ('CY 2023 AAR, Part II, Observation No. 5, p. 71'):"
            f" {text!r}"
        )
    start = match["start"]
    end = match["end"] or start
    return ParsedCitation(
        Source(
            aar_year=int(match["year"]),
            part=match["part"],
            origin_year=int(match["origin"]) if match["origin"] else None,
            label=match["label"],
            number=int(match["number"]) if match["number"] else None,
        ),
        int(start) if start else None,
        int(end) if end else None,
    )
