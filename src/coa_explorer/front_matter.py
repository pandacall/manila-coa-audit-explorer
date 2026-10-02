"""Extract the Executive Summary and the Auditor's Report of an AAR into cited sections.

Both documents come as Word or as PDF depending on the year, so each is first read into the same
plain blocks (a paragraph, a list item or a table, with the page it is on) and then split into
sections on COA's headings:

* The Executive Summary's sections are lettered ("A. Introduction", "B. Financial Highlights" ...).
  Its pages are the lowercase Roman numerals COA prints: Word says so in the section's page-number
  format, and the 2024 PDF prints them.
* The Auditor's Report has no letters; its headings follow COA's standard form ("Qualified
  Opinion", "Emphasis of Matter" ...) and are matched against that list. Its pages are plain
  numbers.

Word pages are derived from the saved layout (ADR-0001), so they are best-effort; PDF pages are
the PDF's real ones. Each section is one Citation: the Executive Summary's names the section
letter, the exact anchor, the Auditor's Report's the page.
"""

from __future__ import annotations

import re
import string
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from coa_explorer.config import DEFAULT_REVIEWED
from coa_explorer.docx_reader import Block as DocxBlock
from coa_explorer.docx_reader import (
    Paragraph,
    Table,
    format_page_number,
    page_number_format,
    read_blocks,
)
from coa_explorer.pdf_reader import PdfPage, read_pages, reviewed_path

EXECUTIVE_SUMMARY = "Executive Summary"
AUDITORS_REPORT = "Auditor's Report"

# Sentence-ending characters: a block that ends with anything else carries on over a page break.
TERMINATORS = '.;:?!)"”’'
LIST_ITEM = re.compile(r"^(?:(?:[a-z]|\d{1,2})[.)]\s+\S|•)")
AMOUNT = re.compile(r"\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?")
CELL_GAP = re.compile(r"\s{2,}")
EXECUTIVE_SUMMARY_HEADING = re.compile(r"^([A-Z])\.\s+(\S.*)$")
AUDITORS_REPORT_HEADINGS = re.compile(
    r"independent auditor's report"
    r"|report on the (audit of the )?financial statements"
    r"|(qualified|unqualified|unmodified|adverse) opinion|disclaimer of opinion"
    r"|bas(is|es) for (qualified |adverse |disclaimer of )?opinion"
    r"|emphasis of matter( paragraph)?|key audit matters"
    r"|responsibilities of management and those charged with governance"
    r" for the financial statements"
    r"|auditor's responsibilities for the audit of the financial statements"
    r"|report on other legal and regulatory requirements"
)


@dataclass(frozen=True)
class Block:
    text: str
    page: int
    end_page: int
    table: bool = False  # keeps its line breaks and is never joined to its neighbours


@dataclass
class Section:
    label: str | None  # the Executive Summary's section letter
    heading: str
    page_start: int
    page_end: int
    pages: str  # as COA prints them: "iii", or "ii-iii" over a page break
    citation: str
    text: str


@dataclass
class FrontMatter:
    aar_year: int
    document: str
    source_file: str
    text_source: str
    page_format: str  # Word number format of the printed pages: lowerRoman or decimal
    sections: list[Section] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# A heading matcher looks at the blocks from `i` on and returns (label, heading, blocks used).
HeadingMatcher = Callable[[Sequence[Block], int], "tuple[str | None, str, int] | None"]


def extract_executive_summary(
    reports_dir: Path, year: int, reviewed_dir: Path | None = DEFAULT_REVIEWED
) -> FrontMatter:
    return _extract(
        reports_dir, year, "03-*Executive_Summary.*", EXECUTIVE_SUMMARY, "lowerRoman", reviewed_dir
    )


def extract_auditors_report(
    reports_dir: Path, year: int, reviewed_dir: Path | None = DEFAULT_REVIEWED
) -> FrontMatter:
    return _extract(
        reports_dir, year, "05-*Auditor*Report.*", AUDITORS_REPORT, "decimal", reviewed_dir
    )


def find_file(reports_dir: Path, year: int, pattern: str) -> Path:
    """The year's one file for this document, Word or PDF. The duplicate Executive Summary PDFs
    live outside the year folders, in `_duplicates/`, and are never found here."""
    folder = reports_dir / f"Manila-City-Annual-Audit-Report-{year}"
    matches = sorted(p for p in folder.glob(f"**/{pattern}") if p.suffix in (".docx", ".pdf"))
    if len(matches) != 1:
        raise FileNotFoundError(f"expected one {pattern} file for {year} under {folder}: {matches}")
    return matches[0]


def _extract(
    reports_dir: Path,
    year: int,
    pattern: str,
    document: str,
    pdf_page_format: str,
    reviewed_dir: Path | None,
) -> FrontMatter:
    path = find_file(reports_dir, year, pattern)
    is_summary = document == EXECUTIVE_SUMMARY
    matcher = _executive_summary_matcher() if is_summary else _auditors_report_matcher
    starts_block = _starts_block(is_summary)
    if path.suffix == ".docx":
        page_format = page_number_format(path)
        blocks = _word_blocks(read_blocks(path))
        text_source = "Word document"
    else:
        page_format = pdf_page_format
        pages = read_pages(path, reviewed_dir)
        _check_printed_pages(path, pages, page_format)
        blocks = _pdf_blocks(pages, starts_block)
        transcription = reviewed_path(path, reviewed_dir)
        text_source = (
            f"reviewed transcription: data/reviewed/{transcription.name}"
            if transcription
            else "PDF text layer"
        )
    sections = _sections(blocks, matcher, year, document, page_format)
    if not sections:
        raise ValueError(f"{path.name}: no sections found")
    return FrontMatter(
        aar_year=year,
        document=document,
        source_file=path.relative_to(reports_dir).as_posix(),
        text_source=text_source,
        page_format=page_format,
        sections=sections,
    )


# ---------------------------------------------------------------------------------------------
# Headings


def _executive_summary_matcher() -> HeadingMatcher:
    """Lettered headings, in sequence: a line such as "E. " inside a list is not a heading."""
    expected = iter(string.ascii_uppercase)
    wanted = [next(expected)]

    def match(blocks: Sequence[Block], i: int):
        block = blocks[i]
        found = None if block.table else EXECUTIVE_SUMMARY_HEADING.match(block.text)
        if found and found.group(1) == wanted[0]:
            wanted[0] = next(expected, "")
            return found.group(1), found.group(2), 1
        return None

    return match


def _auditors_report_matcher(blocks: Sequence[Block], i: int):
    """COA's standard headings. Word sometimes breaks a long one across two paragraphs."""
    for used in (1, 2):
        pieces = [b for b in blocks[i : i + used] if not b.table]
        if len(pieces) < used:
            break
        text = " ".join(b.text for b in pieces)
        normal = re.sub(r"\s+", " ", text.replace("’", "'")).strip().lower()
        if AUDITORS_REPORT_HEADINGS.fullmatch(normal):
            heading = string.capwords(text) if text.isupper() else text
            return None, re.sub(r"\s+", " ", heading).strip(), used
    return None


def _starts_block(is_summary: bool) -> Callable[[str], bool]:
    """Whether text is a heading, for joining blocks over a PDF page break. Unlike the matcher it
    keeps no count, so a stray "E." in a list may pass for a heading; that only keeps two blocks
    apart."""
    if is_summary:
        return lambda text: EXECUTIVE_SUMMARY_HEADING.match(text) is not None
    return lambda text: _auditors_report_matcher([Block(text, 0, 0)], 0) is not None


def _sections(
    blocks: list[Block], matcher: HeadingMatcher, year: int, document: str, page_format: str
) -> list[Section]:
    sections: list[Section] = []
    heading: tuple[str | None, str, int, int] | None = None
    body: list[Block] = []

    def close() -> None:
        if heading is None:
            return
        label, title, page, end = heading
        last = max([end, *(b.end_page for b in body)])
        pages = _printed(page, last, page_format)
        sections.append(
            Section(
                label=label,
                heading=title,
                page_start=page,
                page_end=last,
                pages=pages,
                citation=_citation(year, document, label, page, last, page_format),
                text="\n".join(b.text for b in body),
            )
        )

    i = 0
    while i < len(blocks):
        found = matcher(blocks, i)
        if found:
            close()
            label, title, used = found
            heading = (label, title, blocks[i].page, blocks[i + used - 1].end_page)
            body = []
            i += used
            continue
        if heading is not None:  # text before the first heading is letterhead and addressee
            body.append(blocks[i])
        i += 1
    close()
    return sections


def _printed(start: int, end: int, page_format: str) -> str:
    first = format_page_number(start, page_format)
    return first if start == end else f"{first}-{format_page_number(end, page_format)}"


def _citation(
    year: int, document: str, label: str | None, start: int, end: int, page_format: str
) -> str:
    pages = _printed(start, end, page_format)
    where = f"p. {pages}" if start == end else f"pp. {pages}"
    if document == EXECUTIVE_SUMMARY:
        return f"CY {year} AAR, {document}, Section {label}, {where}"
    return f"CY {year} AAR, Part I, {document}, {where}"


# ---------------------------------------------------------------------------------------------
# Word documents into blocks


def _word_blocks(blocks: list[DocxBlock]) -> list[Block]:
    result = []
    for block in blocks:
        if isinstance(block, Table):
            result.append(Block(block.markdown, block.page, block.end_page, table=True))
        elif isinstance(block, Paragraph):
            text = f"{block.label} {block.text}" if block.label else block.text
            result.append(Block(text, block.page, block.end_page))
    return result


# ---------------------------------------------------------------------------------------------
# PDF pages into blocks


def _check_printed_pages(path: Path, pages: list[PdfPage], page_format: str) -> None:
    """The page numbers a PDF prints must be its own page order, or its pages can't be cited."""
    for page in pages:
        expected = format_page_number(page.number, page_format)
        if page.label not in (None, expected):
            raise ValueError(
                f"{path.name}: PDF page {page.number} prints page number {page.label!r},"
                f" expected {expected!r}"
            )


def _pdf_blocks(pages: list[PdfPage], starts_block: Callable[[str], bool]) -> list[Block]:
    blocks: list[Block] = []
    for page in pages:
        first_on_page = len(blocks)
        for group in paragraph_groups(page.lines):
            blocks.extend(_group_blocks(group, page.number))
        join_over_page_break(blocks, first_on_page, starts_block)
    return blocks


def paragraph_groups(lines: Sequence[str]) -> list[list[str]]:
    groups: list[list[str]] = [[]]
    for line in lines:
        if line.strip():
            groups[-1].append(line)
        elif groups[-1]:
            groups.append([])
    return [g for g in groups if g]


def _group_blocks(lines: list[str], page: int) -> list[Block]:
    if sum(len(AMOUNT.findall(line)) >= 2 for line in lines) >= 2:
        return [Block("\n".join(_table_rows(lines)), page, page, table=True)]
    blocks: list[str] = []
    for line in lines:
        text = tidy(line)
        if not blocks or LIST_ITEM.match(text):
            blocks.append(text)
        else:
            blocks[-1] = f"{blocks[-1]} {text}"
    return [Block(text, page, page) for text in blocks]


def _table_rows(lines: list[str]) -> list[str]:
    return [" | ".join(row) for row in table_cells(lines)]


def table_cells(
    lines: list[str], split: Callable[[str], list[str]] | None = None
) -> list[list[str]]:
    """The cells of each table line (as `split` cuts them, by default at the gaps between
    columns); a lone indented label continues the row above."""
    rows: list[list[str]] = []
    indents: list[int] = []
    for line in lines:
        cells = split(line) if split else [tidy(cell) for cell in CELL_GAP.split(line.strip())]
        indent = len(line) - len(line.lstrip())
        if (
            len(cells) == 1
            and rows
            and AMOUNT.search(" ".join(rows[-1][1:]))
            and indent > indents[-1]
        ):
            rows[-1][0] = f"{rows[-1][0]} {cells[0]}"
            continue
        rows.append(cells)
        indents.append(indent)
    return rows


def tidy(text: str) -> str:
    """Collapse spacing, and close the gap a PDF leaves before a hyphen ("non -maintenance")."""
    return re.sub(r"(?<=\w) -(?=\w)", "-", re.sub(r"\s+", " ", text)).strip()


def join_over_page_break(
    blocks: list[Block], first_on_page: int, starts_block: Callable[[str], bool]
) -> None:
    """Rejoin a paragraph that runs over a page break: the earlier page's last block has not
    ended its sentence and the new page opens with plain text, not a heading, item or table."""
    if first_on_page == 0 or first_on_page >= len(blocks):
        return
    before, after = blocks[first_on_page - 1], blocks[first_on_page]
    if (
        before.table
        or after.table
        or before.text.endswith(tuple(TERMINATORS))
        or LIST_ITEM.match(after.text)
        or starts_block(after.text)
        or starts_block(before.text)
    ):
        return
    blocks[first_on_page - 1 : first_on_page + 1] = [
        replace(before, text=f"{before.text} {after.text}", end_page=after.end_page)
    ]
