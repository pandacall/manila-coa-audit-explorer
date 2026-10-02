"""Extract Part III (Status of Implementation of Prior Years' Audit Recommendations) of an AAR.

Part III is one 5-column table: Reference | Observations and Recommendations | Status of
Implementation | Management Action | Reason for Partial / Non-Implementation. The Reference names
the earlier Audit Observation (the Originating Observation) a block of rows is about; the rows
below it carry COA's Status of Implementation for each of that observation's Recommendations.

One record is made per status COA prints, i.e. per Prior Years' Recommendation. COA's totals in the
intro paragraph (79, 58, 53, 53 and 27) equal these counts. Word cells often hold several
paragraphs, and when a column's paragraphs cannot be matched one-to-one with the statuses, the
column's whole text is attached to each of the recommendations it covers and the column is listed
in `shared`, so nothing is dropped and nothing is guessed.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from coa_explorer.docx_reader import Paragraph, Table, TableRow, read_blocks
from coa_explorer.references import Reference, parse_reference

IMPLEMENTED = "Implemented"
PARTIAL = "Partially Implemented"
NOT_IMPLEMENTED = "Not Implemented"

_STATUS = re.compile(
    r"^(fully\s+|partially\s+|not\s+)?(implemented|unimplemented)\b", re.IGNORECASE
)
_RECOMMENDATION_LEAD = re.compile(r"^we\b.{0,40}\b(recommend\w*|reiterat\w*)\b", re.IGNORECASE)
_CLOSING = (".", ";", ":", ")", "and", "or")
_STATED_TOTAL = re.compile(r"\bOf the (\d+) prior years", re.IGNORECASE)


@dataclass
class PriorYearsRecommendation:
    number: int  # 1-based position within this AAR's Part III
    recommendation: str
    status: str  # COA's Status of Implementation: Implemented, Partially or Not Implemented
    status_text: str  # as printed ("Fully Implemented" in the CY 2020-2022 AARs)
    status_note: str | None  # e.g. "Recommendation is reiterated (Finding No. 1, pp. 66-69)"
    management_action: str | None
    reason: str | None  # reason for partial or non-implementation
    shared: list[str]  # columns whose text covers several recommendations, not just this one
    page_start: int
    page_end: int
    citation: str


@dataclass
class TrackedObservation:
    """An earlier Audit Observation whose Recommendations this AAR's Part III follows up."""

    aar_year: int  # the AAR whose Part III this is
    reference: str  # as printed, with the year heading above it when the table has one
    origin_year: int | None
    origin_observation: int | None
    origin_page_start: int | None
    origin_page_end: int | None
    summary: str  # the observation as summarised in Part III
    recommendations: list[PriorYearsRecommendation] = field(default_factory=list)


@dataclass
class Part3:
    aar_year: int
    source_file: str
    table_rows: int  # rows in the Word table, header and empty rows included
    stated_recommendations: int | None  # the total COA states in the intro paragraph
    observations: list[TrackedObservation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def recommendations(self) -> list[PriorYearsRecommendation]:
        return [r for o in self.observations for r in o.recommendations]


def extract_year(reports_dir: Path, year: int) -> Part3:
    """Extract Part III for one AAR year from the committed report folders."""
    path = find_part3_file(reports_dir, year)
    result = extract_part3(path, year)
    result.source_file = path.relative_to(reports_dir).as_posix()
    return result


def find_part3_file(reports_dir: Path, year: int) -> Path:
    folder = reports_dir / f"Manila-City-Annual-Audit-Report-{year}"
    matches = sorted(folder.glob("**/10-*Part3*.docx"))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"expected one Part III file for {year} under {folder}, got {matches}"
        )
    return matches[0]


def extract_part3(path: Path, year: int) -> Part3:
    blocks = read_blocks(path)
    tables = [b for b in blocks if isinstance(b, Table)]
    if len(tables) != 1:
        raise ValueError(f"{path.name}: expected one Part III table, found {len(tables)}")
    table = tables[0]
    intro = " ".join(b.text for b in blocks if isinstance(b, Paragraph))
    total = _STATED_TOTAL.search(intro)
    result = Part3(
        aar_year=year,
        source_file=path.name,  # extract_year makes it repo-relative
        table_rows=len(table.rows),
        stated_recommendations=int(total.group(1)) if total else None,
    )
    count = 0
    for group in _groups(table.rows[1:]):
        tracked = _tracked_observation(year, group, count)
        count += len(tracked.recommendations)
        result.observations.append(tracked)
    return result


# ---------------------------------------------------------------------------------------------
# Grouping rows by the observation they follow up


@dataclass
class _Group:
    reference: str
    ref: Reference
    rows: list[TableRow]


def _cell(row: TableRow, column: int) -> tuple[str, ...]:
    return tuple(p for p in (row.cells[column] if column < len(row.cells) else ()) if p.strip())


def _groups(rows: list[TableRow]) -> list[_Group]:
    groups: list[_Group] = []
    heading = ""  # the "AAR CY 2019" row above a run of observations
    heading_year: int | None = None
    for row in rows:
        reference = " ".join(_cell(row, 0)).strip()
        if reference:
            ref = parse_reference(reference)
            if ref.observation is None:
                if any(_cell(row, c) for c in range(1, 5)):
                    raise ValueError(f"heading row {reference!r} carries content")
                heading, heading_year = reference, ref.aar_year
                continue
            if ref.aar_year is None:
                ref = Reference(heading_year, ref.observation, ref.page_start, ref.page_end)
                reference = f"{heading} {reference}".strip()
            groups.append(_Group(reference, ref, [row]))
        elif any(_cell(row, c) for c in range(1, 5)):
            if not groups:
                raise ValueError("Part III row before any Reference")
            groups[-1].rows.append(row)
    return groups


# ---------------------------------------------------------------------------------------------
# One observation's rows into recommendations


def _tracked_observation(year: int, group: _Group, already: int) -> TrackedObservation:
    observation_text, first_recs = _split_observation(group.rows[0])
    recs_by_row = [first_recs] + [list(_cell(row, 1)) for row in group.rows[1:]]
    statuses_by_row = [_statuses(_cell(row, 2)) for row in group.rows]

    group_items = [item for recs in recs_by_row for item in _items(recs)]
    group_aligned = len(group_items) == sum(len(s) for s in statuses_by_row)

    tracked = TrackedObservation(
        aar_year=year,
        reference=group.reference,
        origin_year=group.ref.aar_year,
        origin_observation=group.ref.observation,
        origin_page_start=group.ref.page_start,
        origin_page_end=group.ref.page_end,
        summary=" ".join(observation_text),
    )
    offset = 0  # statuses in earlier rows of the group, to index into group_items
    for row, recs, statuses in zip(group.rows, recs_by_row, statuses_by_row, strict=True):
        k = len(statuses)
        if not k:
            continue
        shared: list[str] = []
        items = _items(recs)
        if len(items) == k:
            texts = items
        elif group_aligned:
            texts = group_items[offset : offset + k]
        else:
            texts = [" ".join(recs)] * k
            shared.append("recommendation")
        offset += k

        actions = _spread(_cell(row, 3), statuses, shared, "management_action", open_only=False)
        reasons = _spread(_cell(row, 4), statuses, shared, "reason", open_only=True)
        for i, (status, note) in enumerate(statuses):
            tracked.recommendations.append(
                PriorYearsRecommendation(
                    number=already + len(tracked.recommendations) + 1,
                    recommendation=texts[i],
                    status=_normalise(status),
                    status_text=status,
                    status_note=note,
                    management_action=actions[i],
                    reason=reasons[i],
                    shared=list(shared),
                    page_start=row.page,
                    page_end=row.end_page,
                    citation=_citation(year, group.ref, row.page, row.end_page),
                )
            )
    return tracked


def _split_observation(first: TableRow) -> tuple[list[str], list[str]]:
    """The first row's observation text, and the Recommendations (if any) that follow it."""
    paragraphs = list(_cell(first, 1))
    lead = next((i for i, p in enumerate(paragraphs) if i and _RECOMMENDATION_LEAD.match(p)), None)
    if lead is None:
        # No "We recommended ..." line: a row that also carries a status has one observation
        # paragraph followed by the recommendation; a row without one is all observation.
        lead = 1 if _cell(first, 2) else len(paragraphs)
    return paragraphs[:lead], paragraphs[lead:]


def _statuses(paragraphs: tuple[str, ...]) -> list[tuple[str, str | None]]:
    """(status, note) pairs: a paragraph that is not a status annotates the status above it."""
    statuses: list[tuple[str, list[str]]] = []
    for paragraph in paragraphs:
        text = paragraph.strip()
        if _STATUS.match(text):
            statuses.append((text, []))
        elif statuses:
            statuses[-1][1].append(text)
    return [(status, " ".join(notes) or None) for status, notes in statuses]


def _normalise(status: str) -> str:
    match = _STATUS.match(status)
    prefix = (match.group(1) or "").strip().lower()
    if prefix == "partially":
        return PARTIAL
    if prefix == "not" or match.group(2).lower() == "unimplemented":
        return NOT_IMPLEMENTED
    return IMPLEMENTED


def _items(paragraphs: list[str]) -> list[str]:
    """Each Recommendation in a cell: a line that completes the lead-in ending in a colon above it.

    Word sometimes breaks one recommendation across two paragraphs mid-sentence ("... of
    Observation" / "No. 1;"), so a line that follows one with no closing punctuation continues it.
    """
    items: list[str] = []
    lead: list[str] = []
    after_item = False
    for paragraph in paragraphs:
        if after_item and not items[-1].endswith(_CLOSING):
            items[-1] = f"{items[-1]} {paragraph}"
        elif paragraph.rstrip().endswith(":"):
            if after_item:
                lead = []
            lead.append(paragraph)
            after_item = False
        else:
            items.append(" ".join([*lead, paragraph]))
            after_item = True
    return items


def _spread(
    paragraphs: tuple[str, ...],
    statuses: list[tuple[str, str | None]],
    shared: list[str],
    name: str,
    *,
    open_only: bool,
) -> list[str | None]:
    """Spread a column's paragraphs over the row's statuses, or share them when they don't fit.

    A Reason is printed only for Partially or Not Implemented recommendations, so a Reason column
    with one paragraph per such status is matched against those.
    """
    k = len(statuses)
    if not paragraphs:
        return [None] * k
    if k == 1:
        return [" ".join(paragraphs)]
    if len(paragraphs) == k:
        return list(paragraphs)
    if open_only:
        open_ones = [i for i, (s, _) in enumerate(statuses) if _normalise(s) != IMPLEMENTED]
        if len(paragraphs) == len(open_ones):
            spread: list[str | None] = [None] * k
            for i, paragraph in zip(open_ones, paragraphs, strict=True):
                spread[i] = paragraph
            return spread
    shared.append(name)
    return [" ".join(paragraphs)] * k


def _citation(year: int, ref: Reference, page_start: int, page_end: int) -> str:
    pages = f"p. {page_start}" if page_start == page_end else f"pp. {page_start}-{page_end}"
    if ref.aar_year is None or ref.observation is None:
        return f"CY {year} AAR, Part III, {pages}"
    return f"CY {year} AAR, Part III, CY {ref.aar_year} Observation No. {ref.observation}, {pages}"
