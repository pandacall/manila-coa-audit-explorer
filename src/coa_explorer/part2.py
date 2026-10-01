"""Extract Part II (Audit Observations and Recommendations) of an AAR into structured records.

An Audit Observation is a bold, level-0 numbered paragraph of the report's observation list. Below
it come numbered sub-paragraphs, a bold "We recommended ..." block, "Management comment/action:"
and, when COA has one, "Auditor's rejoinder:". Bold unnumbered lines that sit directly above an
observation are section headings. Commendations are the numbered acknowledgements COA lists before
the first observation (CY 2024); they are never Audit Observations.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from coa_explorer.docx_reader import Block, Paragraph, Table, read_blocks


@dataclass
class Recommendation:
    label: str | None
    text: str
    lead_in: str | None  # the "We recommended that Management:" line this item completes


@dataclass
class Observation:
    aar_year: int
    number: int
    title: str
    section_heading: str | None
    description: str
    recommendations: list[Recommendation]
    management_comment: str | None
    auditors_rejoinder: str | None
    page_start: int
    page_end: int
    citation: str


@dataclass
class Commendation:
    aar_year: int
    number: int
    text: str
    page_start: int
    page_end: int
    citation: str


@dataclass
class OtherItem:
    """A numbered, unbolded item in Part II that COA does not number as an Audit Observation."""

    aar_year: int
    number: int
    section_heading: str | None
    text: str
    page_start: int
    page_end: int
    citation: str


@dataclass
class Part2:
    aar_year: int
    source_file: str
    observations: list[Observation] = field(default_factory=list)
    commendations: list[Commendation] = field(default_factory=list)
    other_items: list[OtherItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def extract_year(reports_dir: Path, year: int) -> Part2:
    """Extract Part II for one AAR year from the committed report folders."""
    path = find_part2_file(reports_dir, year)
    result = extract_part2(path, year)
    result.source_file = path.relative_to(reports_dir).as_posix()
    return result


def find_part2_file(reports_dir: Path, year: int) -> Path:
    folder = reports_dir / f"Manila-City-Annual-Audit-Report-{year}"
    matches = sorted(folder.glob("**/09-*Part2*.docx"))
    if len(matches) != 1:
        raise FileNotFoundError(
            f"expected one Part II file for {year} under {folder}, got {matches}"
        )
    return matches[0]


def extract_part2(path: Path, year: int) -> Part2:
    blocks = read_blocks(path)
    result = Part2(aar_year=year, source_file=path.name)  # extract_year makes it repo-relative
    starts = _item_starts(blocks)
    if not starts:
        return result

    result.commendations = _commendations(year, blocks[: starts[0]])

    heading: str | None = None
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(blocks)
        # Bold lines directly above the next item are its section heading, not this item's text.
        next_headings = _trailing_headings(blocks[start + 1 : end]) if n + 1 < len(starts) else []
        body_end = end - len(next_headings)
        if n == 0:
            leading = _trailing_headings(blocks[:start])
            if leading:
                heading = _heading_text(leading)
        head = blocks[start]
        body = blocks[start + 1 : body_end]
        if head.bold:
            result.observations.append(_observation(year, head, body, heading))
        else:
            result.other_items.append(_other_item(year, head, body, heading))
        if next_headings:
            heading = _heading_text(next_headings)
    return result


# ---------------------------------------------------------------------------------------------
# Locating the numbered items


def _item_starts(blocks: list[Block]) -> list[int]:
    """Indexes of the numbered items that make up the report's main sequence 1, 2, 3, ...

    Audit Observations are bold. An unbolded item that continues the sequence in the same list as
    the observations (CY 2020's tax-remittance and audit-suspension sections) is kept too, so it
    ends the observation above it, but it is not an Audit Observation.
    """
    starts: list[int] = []
    expected = 1
    observation_list: int | None = None
    for i, block in enumerate(blocks):
        if not isinstance(block, Paragraph) or block.level != 0 or _number(block) != expected:
            continue
        if block.bold:
            observation_list = block.list_id
        elif block.list_id != observation_list or observation_list is None:
            continue
        starts.append(i)
        expected += 1
    return starts


def _number(block: Paragraph) -> int | None:
    match = re.fullmatch(r"(\d+)\.", block.label or "")
    return int(match.group(1)) if match else None


def _is_heading(block: Block) -> bool:
    return (
        isinstance(block, Paragraph)
        and (block.bold or block.text.isupper())
        and block.list_id is None
        and len(block.text) <= 250
        and not re.search(r"[.;:]$", block.text)
        and not _RECOMMENDS.search(block.text)
    )


def _heading_text(headings: list[Paragraph]) -> str:
    return " / ".join(h.text for h in headings)


def _trailing_headings(blocks: list[Block]) -> list[Paragraph]:
    headings: list[Paragraph] = []
    for block in reversed(blocks):
        if not _is_heading(block):
            break
        headings.insert(0, block)
    return headings


# ---------------------------------------------------------------------------------------------
# Commendations (CY 2024)


def _commendations(year: int, preamble: list[Block]) -> list[Commendation]:
    groups: list[list[Paragraph]] = []
    for block in preamble:
        if not isinstance(block, Paragraph) or block.bold:
            continue
        if block.list_id is None:
            if groups:
                break  # prose after the list ends it
            continue
        if block.level == 0 and re.fullmatch(r"\d+\.", block.label or ""):
            groups.append([block])
        elif groups:
            groups[-1].append(block)
    commendations = []
    for number, group in enumerate(groups, start=1):
        first, last = group[0], group[-1]
        text = "\n".join([first.text] + [_render(p) for p in group[1:]])
        commendations.append(
            Commendation(
                year,
                number,
                text,
                first.page,
                last.end_page,
                _citation(year, "Commendation No.", number, first.page, last.end_page),
            )
        )
    return commendations


# ---------------------------------------------------------------------------------------------
# Observations

_RECOMMENDS = re.compile(r"\b(recommend\w*|reiterat\w*)\b", re.IGNORECASE)
_COMMENT = re.compile(r"^management(?:[’']s)?\s+comments?\b", re.IGNORECASE)
_REJOINDER = re.compile(r"^auditor[’']s\s+rejoinder\b", re.IGNORECASE)


def _observation(year: int, head: Paragraph, body: list[Block], heading: str | None) -> Observation:
    description: list[Block] = []
    rec_paragraphs: list[Paragraph] = []
    comment: list[Block] = []
    rejoinder: list[Block] = []
    mode = "description"
    in_recs = False
    for block in body:
        if isinstance(block, Paragraph) and _REJOINDER.match(block.text):
            mode = "rejoinder"
            continue
        if isinstance(block, Paragraph) and _COMMENT.match(block.text) and mode == "description":
            mode = "comment"
            continue
        if mode == "comment":
            comment.append(block)
        elif mode == "rejoinder":
            rejoinder.append(block)
        elif (
            isinstance(block, Paragraph)
            and block.bold
            and (in_recs or _RECOMMENDS.search(block.text))
        ):
            in_recs = True
            rec_paragraphs.append(block)
        else:
            in_recs = False
            description.append(block)

    last = body[-1] if body else head
    page_end = max(head.end_page, last.end_page)
    number = _number(head)
    return Observation(
        aar_year=year,
        number=number,
        title=head.text,
        section_heading=heading,
        description=_join(description),
        recommendations=_recommendations(rec_paragraphs),
        management_comment=_join(comment) or None,
        auditors_rejoinder=_join(rejoinder) or None,
        page_start=head.page,
        page_end=page_end,
        citation=_citation(year, "Observation No.", number, head.page, page_end),
    )


def _recommendations(paragraphs: list[Paragraph]) -> list[Recommendation]:
    """One Recommendation per leaf item; a line ending in a colon leads in the items below it."""
    entries: list[dict] = []
    stack: list[dict] = []
    for p in paragraphs:
        while stack and _is_sibling_or_above(stack[-1]["p"], p):
            stack.pop()
        entry = {"p": p, "has_children": False, "lead_in": _lead_in(stack)}
        for parent in stack:
            parent["has_children"] = True
        entries.append(entry)
        if re.search(r"[:–-]$", p.text):
            stack.append(entry)
    return [
        Recommendation(e["p"].label or None, e["p"].text, e["lead_in"])
        for e in entries
        if not e["has_children"]
    ]


def _is_sibling_or_above(open_item: Paragraph, new_item: Paragraph) -> bool:
    return open_item.list_id == new_item.list_id and (open_item.level or 0) >= (new_item.level or 0)


def _lead_in(stack: list[dict]) -> str | None:
    return " ".join(e["p"].text for e in stack) or None


# ---------------------------------------------------------------------------------------------
# Other numbered items, rendering


def _other_item(year: int, head: Paragraph, body: list[Block], heading: str | None) -> OtherItem:
    last = body[-1] if body else head
    number = _number(head)
    page_end = max(head.end_page, last.end_page)
    return OtherItem(
        aar_year=year,
        number=number,
        section_heading=heading,
        text=_join([head, *body]),
        page_start=head.page,
        page_end=page_end,
        citation=_citation(year, "Item No.", number, head.page, page_end),
    )


def _render(block: Block) -> str:
    if isinstance(block, Table):
        return block.markdown
    return f"{block.label} {block.text}" if block.label else block.text


def _join(blocks: list[Block]) -> str:
    return "\n\n".join(_render(b) for b in blocks)


def _citation(year: int, what: str, number: int, page_start: int, page_end: int) -> str:
    pages = f"p. {page_start}" if page_start == page_end else f"pp. {page_start}-{page_end}"
    return f"CY {year} AAR, Part II, {what} {number}, {pages}"
