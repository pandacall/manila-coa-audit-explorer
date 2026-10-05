"""Reading Citations back: which source one points at, and on which pages.

A Citation names its source (the AAR year and document, then the Part, Audit Observation, section,
Note or financial line it concerns) and ends with the pages, a best-effort pointer (ADR-0001). So
two Citations are the same source when everything before their pages matches, and `page_start`
may drift. A financial line has no pages; the Executive Summary's are lowercase Roman numerals.
"""

from __future__ import annotations

import re
from typing import NamedTuple

CITATION = re.compile(
    r"^(?P<source>CY \d{4} (?:AAR, (?:Part (?:IV|III|II|I)|Executive Summary|Transmittal Letter)"
    r"|AAPSI|APMT)(?:, (?!pp?\. ).+?)?)"  # an anchor, never the pages themselves
    r"(?:, pp?\. (?P<start>\d+|[ivxlc]+)(?:-(?P<end>\d+|[ivxlc]+))?)?$"
)
ROMAN = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100}


class ParsedCitation(NamedTuple):
    source: str  # the Citation without its pages
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
        match["source"],
        page_number(start) if start else None,
        page_number(end) if end else None,
    )


def page_number(text: str) -> int:
    """A page as a number, whether COA printed it in Arabic or lowercase Roman numerals."""
    if text.isdigit():
        return int(text)
    values = [ROMAN[c] for c in text]
    return sum(-v if v < after else v for v, after in zip(values, [*values[1:], 0], strict=True))
