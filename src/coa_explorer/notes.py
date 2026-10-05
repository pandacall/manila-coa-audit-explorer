"""Extract the Notes to Financial Statements of an AAR into cited Notes.

The Notes come as Word (2020-2023) or as PDF (2024). Each is first read into plain blocks (a
paragraph, a list item or a table, with the page it sits on) and then split on COA's headings,
"Note 1 – Profile", "Note 2 – ..." and so on in sequence. Each Note is cut into passages of at most
`MAX_PASSAGE_CHARS`, on block boundaries; tables are written as markdown and, when a table has to be
cut, every part repeats its header row. Each passage is one Citation, by Note and page:
"CY 2023 AAR, Part I, Notes to Financial Statements, Note 4, p. 30".

Pages are the ones COA prints. Word's are derived from the saved layout (ADR-0001), which follows
the page-number restarts a document makes in a later section; the PDF's are read off the pages
themselves (the 2024 file begins at page 12, so its first PDF page is cited as page 12). The PDF's
tables are rebuilt from the text layer's column spacing, and a table with no amounts in it is read
as prose.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from coa_explorer.config import DEFAULT_REVIEWED
from coa_explorer.docx_reader import read_blocks
from coa_explorer.front_matter import find_file
from coa_explorer.pdf_reader import PdfPage, read_pages, reviewed_path
from coa_explorer.text_blocks import (
    CELL_GAP,
    Block,
    Line,
    join_lines,
    pdf_blocks,
    table_cells,
    tidy,
    word_blocks,
)
from coa_explorer.timeline import clip_title

NOTES = "Notes to Financial Statements"
NOTES_PART = "NOTES"  # the part code the index and `search` know the Notes by (they are in Part I)
MAX_PASSAGE_CHARS = 1800

NOTE_HEADING = re.compile(r"^Note\s+(\d+)\s*[–—-]\s*(\S.*)$", re.DOTALL)
# A list item in a PDF: "a." "1)" "3.1" "(ee)" or a bullet.
NOTE_LIST_ITEM = re.compile(
    r"^(?:(?:[a-z]|\d{1,2})[.)]\s+\S|\d{1,2}\.\d{1,2}\s+\S|\([a-z]{1,2}\)\s+\S|[•●])"
)
# An amount as a table cell: 1,234.50 or (1,234.50) or 12.5, or a lone dash for nil.
AMOUNT_CELL = re.compile(r"^\(?(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+)\)?$|^[-–]$")
# "Other 5,292.76": a label and an amount that the layout left one space apart.
LABEL_AND_AMOUNT = re.compile(r"^(.*\S)\s+(\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?)$")
HEADING_LINE = re.compile(r"^\s*Note\s+\d+\s*[–—-]")
NUMERIC_SHARE = 0.4  # of a table row's cells, at least this share are amounts


@dataclass
class Passage:
    page_start: int
    page_end: int
    citation: str
    text: str


@dataclass
class Note:
    number: int
    title: str
    page_start: int
    page_end: int
    citation: str
    passages: list[Passage] = field(default_factory=list)


@dataclass
class Notes:
    aar_year: int
    document: str
    source_file: str
    text_source: str
    notes: list[Note] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def extract_notes(
    reports_dir: Path, year: int, reviewed_dir: Path | None = DEFAULT_REVIEWED
) -> Notes:
    path = find_file(reports_dir, year, "08-*Notes*.*")
    if path.suffix == ".docx":
        blocks = word_blocks(read_blocks(path))
        text_source = "Word document"
    else:
        blocks = _pdf_blocks(read_pages(path, reviewed_dir), path)
        transcription = reviewed_path(path, reviewed_dir)
        text_source = (
            f"reviewed transcription: data/reviewed/{transcription.name}"
            if transcription
            else "PDF text layer"
        )
    notes = _notes(blocks, year)
    if not notes:
        raise ValueError(f"{path.name}: no Notes found")
    return Notes(
        aar_year=year,
        document=NOTES,
        source_file=path.relative_to(reports_dir).as_posix(),
        text_source=text_source,
        notes=notes,
    )


def citation(year: int, number: int, start: int, end: int) -> str:
    where = f"p. {start}" if start == end else f"pp. {start}-{end}"
    return f"CY {year} AAR, Part I, {NOTES}, Note {number}, {where}"


# ---------------------------------------------------------------------------------------------
# Notes


def _notes(blocks: Sequence[Block], year: int) -> list[Note]:
    """Cut the blocks at "Note N –" headings, N counting up from 1 so that a mention of a Note at
    the start of a paragraph is never taken for a heading. Text before Note 1 is the document's
    title and the statement of units."""
    notes: list[Note] = []
    body: list[Block] = []
    heading: tuple[int, str, Block] | None = None
    seen = 0

    def close() -> None:
        if heading is None:
            return
        number, title, block = heading
        end = max([block.end_page, *(b.end_page for b in body)])
        notes.append(
            Note(
                number=number,
                title=title,
                page_start=block.page,
                page_end=end,
                citation=citation(year, number, block.page, end),
                passages=_passages(body, year, number),
            )
        )

    for block in blocks:
        found = None if block.table else NOTE_HEADING.match(block.text)
        if found and int(found.group(1)) == seen + 1:
            close()
            seen += 1
            number, title = seen, re.sub(r"\s+", " ", found.group(2)).strip()
            body = []
            if title.endswith("."):
                # No heading was printed: the Note opens straight into its first sentence.
                body = [Block(title, block.page, block.end_page)]
                title = clip_title(re.split(r"(?<=[.)])\s+(?=[A-Z])", title)[0])
            heading = (number, title, block)
        elif heading is not None:
            body.append(block)
    close()
    return notes


# ---------------------------------------------------------------------------------------------
# Passages


@dataclass(frozen=True)
class _Item:
    text: str
    page: int
    end_page: int
    table: int | None = None  # which table of the Note this line is part of, if any
    repeated: bool = False  # a table header written again at the top of a later passage


def _passages(blocks: Sequence[Block], year: int, number: int) -> list[Passage]:
    items: list[_Item] = []
    headers: dict[int, _Item] = {}
    for index, block in enumerate(blocks):
        if not block.table or len(block.rows) < 3:
            items.append(_Item(block.text, block.page, block.end_page))
            continue
        header, separator, *rows = block.rows
        headers[index] = _Item(
            f"{header.text}\n{separator.text}", header.page, header.end_page, table=index
        )
        items.append(headers[index])
        items.extend(_Item(r.text, r.page, r.end_page, table=index) for r in rows)

    passages: list[Passage] = []
    current: list[_Item] = []

    def flush() -> None:
        real = [item for item in current if not item.repeated]
        if not real:
            return
        start, end = min(i.page for i in real), max(i.end_page for i in real)
        passages.append(Passage(start, end, citation(year, number, start, end), _join(current)))

    for item in items:
        if current and len(_join([*current, item])) > MAX_PASSAGE_CHARS:
            flush()
            current = []
            if item.table is not None and item is not headers[item.table]:
                current = [replace(headers[item.table], repeated=True)]
        current.append(item)
    flush()
    return passages


def _join(items: Sequence[_Item]) -> str:
    """Lines one under another, with a blank line around each table so it stays markdown."""
    out = ""
    for before, item in zip([None, *items], items, strict=False):
        if before is not None:
            out += "\n\n" if before.table != item.table else "\n"
        out += item.text
    return out


# ---------------------------------------------------------------------------------------------
# PDF pages into blocks


def _printed_pages(path: Path, pages: list[PdfPage]) -> dict[int, int]:
    """The page COA prints on each PDF page: the file starts part-way through the AAR, so its
    page 1 is printed as 12. The printed numbers must run in the PDF's own page order."""
    offsets = {int(p.label) - p.number for p in pages if p.label and p.label.isdigit()}
    unusable = [p.number for p in pages if p.label and not p.label.isdigit()]
    if len(offsets) > 1 or unusable:
        raise ValueError(f"{path.name}: the printed page numbers don't follow the PDF's pages")
    offset = offsets.pop() if offsets else 0
    return {p.number: p.number + offset for p in pages}


def _pdf_blocks(pages: list[PdfPage], path: Path) -> list[Block]:
    printed = _printed_pages(path, pages)
    return pdf_blocks(
        pages,
        _group_blocks,
        lambda text: bool(NOTE_HEADING.match(text)),
        lambda page: printed[page.number],
    )


def _group_blocks(lines: list[str], page: int) -> list[Block]:
    heading = next((i for i, line in enumerate(lines) if HEADING_LINE.match(line)), None)
    if heading is not None:
        before = _group_blocks(lines[:heading], page) if heading else []
        return [*before, Block(tidy(" ".join(lines[heading:])), page, page)]
    if _is_table(lines):
        return [_pdf_table(lines, page)]
    return [Block(text, page, page) for text in join_lines(lines, NOTE_LIST_ITEM)]


def _is_table(lines: list[str]) -> bool:
    """Two or more lines whose cells are mostly amounts, or a heading line and one such line.
    Prose also splits into "cells" where the text is justified, but hardly any of its cells are
    amounts."""
    rows = sum(_is_amount_row(line) for line in lines)
    return rows >= 2 or (rows == 1 and len(lines) <= 3)


def _is_amount_row(line: str) -> bool:
    cells = CELL_GAP.split(line.strip())
    amounts = sum(bool(AMOUNT_CELL.match(cell)) for cell in cells[1:])
    return len(cells) >= 2 and amounts / len(cells) >= NUMERIC_SHARE


def _cells(line: str) -> list[str]:
    """A table line's cells. A label the layout spread over several cells is one cell again, so
    that every amount stays under the column it belongs to."""
    cells: list[str] = []
    for cell in CELL_GAP.split(line.strip()):
        split = LABEL_AND_AMOUNT.match(cell)
        cells += [tidy(part) for part in split.groups()] if split else [tidy(cell)]
    first_amount = next((i for i, cell in enumerate(cells) if AMOUNT_CELL.match(cell)), 0)
    if first_amount > 1:
        cells[:first_amount] = [" ".join(cells[:first_amount])]
    return cells


def _pdf_table(lines: list[str], page: int) -> Block:
    rows = table_cells(lines, _cells)
    width = max(len(row) for row in rows)

    def markdown(cells: list[str]) -> str:
        padded = cells + [""] * (width - len(cells))
        return "| " + " | ".join(cell.replace("|", "\\|").strip() for cell in padded) + " |"

    texts = [markdown(rows[0]), "| " + " | ".join(["---"] * width) + " |"]
    texts += [markdown(row) for row in rows[1:]]
    return Block(
        "\n".join(texts),
        page,
        page,
        table=True,
        rows=tuple(Line(text, page, page) for text in texts),
    )
