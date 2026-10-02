"""Read the scanned AAPSI and APMT tables into records.

The AAPSI is Management's own report of its Action Plan for each Recommendation, with the Reported
Status it claims. The APMT is the same table with COA's validation added: COA's Status of
Implementation, the date of COA's follow-up, the actual implementation dates and COA's remarks.
Both are scans, so a page reader (Gemini in production, see `GeminiPageReader`) reads one PDF page
at a time into rows keyed by column; the records are committed once a human has reviewed them.

A block of rows follows the Reference printed in the first of them, which names the Originating
Observation. A page can end mid-block, so the rows below carry on from the previous page. Nothing
is dropped and nothing is guessed: a row with no usable Reference is kept and reported as unmatched,
and the model's own row boundaries are not trusted (it splits rows differently between runs), so
each row is cited by its real PDF page and read by the Recommendation numbers in its text.

Management's status column is Management's Reported Status; it is kept apart from COA's Status of
Implementation (`status`), which only the APMT has.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol

from pypdf import PdfReader, PdfWriter

from coa_explorer.part3 import normalise_status
from coa_explorer.references import Reference, parse_reference

AAPSI = "AAPSI"
APMT = "APMT"
DOCUMENTS = (AAPSI, APMT)

# The columns printed in both tables, left to right (Target Implementation Date has From and To).
AAPSI_COLUMNS = (
    "reference",
    "observations",
    "recommendations",
    "action_plan",
    "person_responsible",
    "target_from",
    "target_to",
    "status",
    "reason_for_delay",
    "action_taken",
)
# The APMT adds COA's validation to the right.
APMT_COLUMNS = (
    *AAPSI_COLUMNS,
    "follow_up_date",
    "coa_status",
    "actual_from",
    "actual_to",
    "remarks",
)
COLUMNS = {AAPSI: AAPSI_COLUMNS, APMT: APMT_COLUMNS}

_WORD = re.compile(r"\w+")
_STATUS_ANYWHERE = re.compile(
    r"\b(?:fully\s+|partially\s+|not\s+)?(?:implemented|unimplemented)\b", re.I
)

_RULES = """Rules:
- One output row per horizontal band of the Audit Observations / Audit Recommendations columns. \
A band is closed off by the ruled lines in those columns.
- A cell on the right that is merged across several bands belongs to the first band it covers; \
leave it empty on the others. Never repeat text to fill a merged cell.
- A cell that is blank in the scan is an empty string. Do not infer or fill anything in.
- Copy text character for character, including numbers, peso amounts, item numbers such as \
"1.7.1" or "2.19", sub-item letters, and bullet items. Keep the scan's own wording even if it \
looks like a typo. Join words broken across lines; do not add line breaks inside a cell.
- Do not skip any row, and do not shorten any cell.
- Ignore the page title, the page number and anything outside the table (cover letters, \
signatures, stamps, footnotes). A page with no table rows gives no rows.
"""

PAGE_PROMPTS = {
    AAPSI: """This is one scanned page of the City of Manila's Agency Action Plan and Status of \
Implementation (AAPSI), a landscape table. Transcribe the table rows exactly as printed.

Columns, left to right: Reference; Audit Observations; Audit Recommendations; Agency Action Plan \
(sub-columns Action Plan, Person/Dept. Responsible, Target Implementation Date From, To); Status \
of Implementation; Reason for Partial/Delay/Non-Implementation, if applicable; Action \
Taken/Action to be Taken.

"""
    + _RULES,
    APMT: """This is one scanned page of COA's Action Plan Monitoring Tool (APMT) for the City \
of Manila, a landscape table. Transcribe the table rows exactly as printed.

Columns, left to right: Reference; Audit Observations; Audit Recommendations; Agency Action Plan \
(sub-columns Action Plan, Person/Dept. Responsible, Target Implementation Date From, To); Status \
of Implementation (the agency's own); Reason for Partial/Delay/Non-Implementation, if \
applicable; Action Taken/Action to be Taken; then under "Results of COA Validation": Date of \
Follow-up; Status of Imp. (COA's); Actual Imp. Date From, To; Remarks.

A row such as "CY 2022 AAR" that only names a year, with nothing else in it, is a heading row: \
give it as a row with only the reference filled in.

"""
    + _RULES,
}


def row_schema(document: str) -> dict:
    """JSON Schema of the page reader's answer: rows of strings, one per column."""
    return {
        "type": "object",
        "properties": {
            "rows": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {c: {"type": "string"} for c in COLUMNS[document]},
                    "required": list(COLUMNS[document]),
                },
            }
        },
        "required": ["rows"],
    }


@dataclass
class MonitoringRow:
    """One row of the table. The Management columns are Management's own account."""

    number: int  # 1-based position within this document
    page: int  # the real PDF page the row starts on
    recommendation: str | None
    action_plan: str | None
    person_responsible: str | None
    target_from: str | None
    target_to: str | None
    reported_status_text: str | None  # Management's Reported Status, as printed
    reported_status: str | None  # ... as a Status of Implementation value, when it is one
    reason: str | None  # Management's reason for partial implementation, delay or none
    action_taken: str | None  # Management's action taken or to be taken
    # APMT only: COA's validation. `status` is COA's Status of Implementation.
    follow_up_date: str | None
    status_text: str | None
    status: str | None
    actual_from: str | None
    actual_to: str | None
    remarks: str | None
    citation: str


@dataclass
class MonitoringObservation:
    """A block of rows following one Reference: the Originating Observation they are about."""

    aar_year: int  # the AAR the AAPSI or APMT belongs to
    document: str
    reference: str
    origin_year: int | None
    origin_observation: int | None
    origin_page_start: int | None
    origin_page_end: int | None
    summary: str  # the observation as printed in the table
    rows: list[MonitoringRow] = field(default_factory=list)


@dataclass
class MonitoringDocument:
    aar_year: int
    document: str
    source_file: str
    pdf_pages: int
    # "pending" until a human has checked the rows against the scan and set it to "reviewed".
    human_review: str = "pending"
    observations: list[MonitoringObservation] = field(default_factory=list)
    # Pages where two readings of the scan disagree, for the human reviewer to check first.
    review_notes: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def rows(self) -> list[MonitoringRow]:
        return [r for o in self.observations for r in o.rows]


class PageReader(Protocol):
    def read_page(self, pdf: bytes, document: str) -> list[dict]:
        """The table rows on one single-page PDF, each a dict of strings keyed by COLUMNS."""
        ...


# ---------------------------------------------------------------------------------------------
# Reading a document


def pdf_path(reports_dir: Path, year: int, document: str) -> Path:
    folder = reports_dir / f"Manila-City-Annual-Audit-Report-{year}" / "AAPSI_APMT"
    matches = sorted(folder.glob(f"*{year}_{document}.pdf"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one {document} for {year} under {folder}, got {matches}")
    return matches[0]


def extract_document(
    reports_dir: Path, year: int, document: str, reader: PageReader, *, passes: int = 2
) -> MonitoringDocument:
    """Read every page of one AAPSI or APMT scan with `reader`.

    Each page is read `passes` times. The first reading is kept; where a later one differs in the
    words it holds, the page is noted in `review_notes` (a model can silently drop a phrase, and
    comparing two readings is how that is caught). Any failed read stops the extraction.
    """
    path = pdf_path(reports_dir, year, document)
    pdf = PdfReader(path)
    pages: list[list[dict]] = []
    notes: list[dict] = []
    for number, page in enumerate(pdf.pages, start=1):
        single = _single_page(page)
        readings = [reader.read_page(single, document) for _ in range(passes)]
        pages.append(readings[0])
        for later in readings[1:]:
            note = _disagreement(number, readings[0], later)
            if note:
                notes.append(note)
    return build_document(
        year, document, path.relative_to(reports_dir).as_posix(), len(pdf.pages), pages, notes
    )


def _single_page(page) -> bytes:
    """One page as its own PDF, sent as scanned (rotation flag and all)."""
    writer = PdfWriter()
    writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _words(rows: list[dict]) -> Counter[str]:
    return Counter(
        word.lower() for row in rows for cell in row.values() for word in _WORD.findall(cell or "")
    )


def _disagreement(page: int, first: list[dict], second: list[dict]) -> dict | None:
    """The words found in one reading of a page and not the other, in the order they appear."""
    a, b = _words(first), _words(second)
    only_first = _surplus(first, a - b)
    only_second = _surplus(second, b - a)
    if not only_first and not only_second:
        return None
    return {"page": page, "only_in_first_read": only_first, "only_in_second_read": only_second}


def _surplus(rows: list[dict], extra: Counter[str]) -> list[str]:
    remaining = Counter(extra)
    found = []
    for row in rows:
        for cell in row.values():
            for word in _WORD.findall(cell or ""):
                if remaining[word.lower()] > 0:
                    remaining[word.lower()] -= 1
                    found.append(word)
    return found


# ---------------------------------------------------------------------------------------------
# Grouping rows by the observation they follow up


def build_document(
    year: int,
    document: str,
    source_file: str,
    pdf_pages: int,
    pages: list[list[dict]],
    review_notes: list[dict],
) -> MonitoringDocument:
    """Group the rows read from each page into blocks, one per Reference, and number them."""
    result = MonitoringDocument(year, document, source_file, pdf_pages, review_notes=review_notes)
    heading_year: int | None = None
    heading = ""
    current: MonitoringObservation | None = None
    count = 0
    for page_number, rows in enumerate(pages, start=1):
        for raw in rows:
            cells = {c: _clean(raw.get(c)) for c in COLUMNS[document]}
            reference = cells["reference"]
            content = any(v for c, v in cells.items() if c != "reference")
            if not reference and not content:
                continue
            if reference:
                ref = parse_reference(reference)
                if ref.observation is None and not content:
                    heading, heading_year = reference, ref.aar_year  # e.g. "CY 2022 AAR"
                    continue
                if ref.aar_year is None and ref.observation is not None:
                    ref = Reference(heading_year, ref.observation, ref.page_start, ref.page_end)
                    reference = f"{heading} {reference}".strip()
                current = MonitoringObservation(
                    aar_year=year,
                    document=document,
                    reference=reference,
                    origin_year=ref.aar_year,
                    origin_observation=ref.observation,
                    origin_page_start=ref.page_start,
                    origin_page_end=ref.page_end,
                    summary=cells["observations"] or "",
                )
                result.observations.append(current)
            elif current is None:
                current = MonitoringObservation(
                    year, document, "", None, None, None, None, cells["observations"] or ""
                )
                result.observations.append(current)
            elif cells["observations"]:
                # The observation's text carries on below the row that started it.
                current.summary = f"{current.summary} {cells['observations']}".strip()
            count += 1
            current.rows.append(_row(count, page_number, year, document, current, cells))
    return result


def _row(
    number: int, page: int, year: int, document: str, block: MonitoringObservation, cells: dict
) -> MonitoringRow:
    reported = cells["status"]
    coa = cells.get("coa_status")
    return MonitoringRow(
        number=number,
        page=page,
        recommendation=cells["recommendations"],
        action_plan=cells["action_plan"],
        person_responsible=cells["person_responsible"],
        target_from=cells["target_from"],
        target_to=cells["target_to"],
        reported_status_text=reported,
        reported_status=status_of(reported),
        reason=cells["reason_for_delay"],
        action_taken=cells["action_taken"],
        follow_up_date=cells.get("follow_up_date"),
        status_text=coa,
        status=status_of(coa),
        actual_from=cells.get("actual_from"),
        actual_to=cells.get("actual_to"),
        remarks=cells.get("remarks"),
        citation=citation(year, document, block.origin_year, block.origin_observation, page),
    )


def status_of(text: str | None) -> str | None:
    """A status cell as one of Implemented, Partially or Not Implemented; None for other wording.

    A cell can stack several statuses, one per Recommendation in the row (the 2024 APMT does).
    They cannot be told apart by Recommendation, so the row has a status only when they all agree.
    """
    found = {normalise_status(m.group(0)) for m in _STATUS_ANYWHERE.finditer(text or "")}
    found.discard(None)
    if len(found) == 1 and normalise_status(text or "") is not None:
        return found.pop()
    return None


def citation(year: int, document: str, origin_year: int | None, origin: int | None, page: int):
    """COA-style Citation: the AAPSI or APMT, the Originating Observation, the real PDF page."""
    if origin_year is None or origin is None:
        return f"CY {year} {document}, p. {page}"
    return f"CY {year} {document}, CY {origin_year} Observation No. {origin}, p. {page}"


def _clean(text: object) -> str | None:
    """A cell's text with its whitespace tidied; None when the cell is blank."""
    return " ".join(str(text or "").split()) or None
