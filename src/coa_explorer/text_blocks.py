"""Blocks of text: paragraphs, list items and tables, each with the page it sits on.

Word and PDF documents are first read into the same plain blocks, which the extractors then cut on
their own headings (the Executive Summary's sections, the Notes' Notes ...). This module is that
shared step:

* A Word document's paragraphs and tables come from `docx_reader`; a table is written as markdown,
  each of its lines with the pages it is on.
* A PDF's pages come as text lines in their layout. Lines are grouped into paragraphs on blank
  lines, a paragraph that runs over a page break is rejoined, and the columns of a table are cut at
  the gaps the layout leaves between them. Deciding what is a table, and what is a heading, is left
  to each extractor.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace

from coa_explorer.docx_reader import Block as DocxBlock
from coa_explorer.docx_reader import Paragraph, Table
from coa_explorer.pdf_reader import PdfPage

# Sentence-ending characters: a block that ends with anything else carries on over a page break.
TERMINATORS = '.;:?!)"”’'
LIST_ITEM = re.compile(r"^(?:(?:[a-z]|\d{1,2})[.)]\s+\S|•)")
AMOUNT = re.compile(r"\(?\d{1,3}(?:,\d{3})+(?:\.\d+)?\)?")
CELL_GAP = re.compile(r"\s{2,}")


@dataclass(frozen=True)
class Line:
    text: str
    page: int
    end_page: int


@dataclass(frozen=True)
class Block:
    """A paragraph, list item or table. A table keeps its line breaks, is never joined to its
    neighbours and lists its lines (a markdown table's header row and separator first) with the
    pages each is on; `text` is all of them."""

    text: str
    page: int
    end_page: int
    table: bool = False
    rows: tuple[Line, ...] = ()


# A PDF page's groups of lines become blocks as the extractor decides; given the lines and the page.
GroupBlocks = Callable[[list[str], int], list[Block]]


# ---------------------------------------------------------------------------------------------
# Word documents


def word_blocks(blocks: list[DocxBlock]) -> list[Block]:
    result = []
    for block in blocks:
        if isinstance(block, Table):
            result.append(_word_table(block))
        elif isinstance(block, Paragraph):
            text = f"{block.label} {block.text}" if block.label else block.text
            result.append(Block(text, block.page, block.end_page))
    return result


def _word_table(table: Table) -> Block:
    """The table as markdown, each row with the pages it is on. The rows Word saved without any
    text are not in the markdown, so they are left out here too."""
    lines = table.markdown.split("\n")
    kept = [row for row in table.rows if any(row.cells)]
    if len(kept) == len(lines) - 1:
        pages = [kept[0], kept[0], *kept[1:]]  # the separator line sits on the header's page
    else:  # a cell holds a table of its own: the rows can't be told apart, so give them all
        pages = [table] * len(lines)  # the table's own pages
    rows = tuple(Line(line, p.page, p.end_page) for line, p in zip(lines, pages, strict=True))
    return Block(table.markdown, table.page, table.end_page, table=True, rows=rows)


# ---------------------------------------------------------------------------------------------
# PDF pages


def pdf_blocks(
    pages: list[PdfPage],
    group_blocks: GroupBlocks,
    starts_block: Callable[[str], bool],
    page_of: Callable[[PdfPage], int] = lambda page: page.number,
) -> list[Block]:
    """Each page's groups of lines as `group_blocks` makes blocks of them, on the page `page_of`
    names. `starts_block` says whether text is a heading, so that it is never rejoined to the text
    above it over a page break."""
    blocks: list[Block] = []
    for page in pages:
        first_on_page = len(blocks)
        for group in paragraph_groups(page.lines):
            blocks.extend(group_blocks(group, page_of(page)))
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


def join_lines(lines: Sequence[str], list_item: re.Pattern[str] = LIST_ITEM) -> list[str]:
    """The paragraphs of a group of lines: each list item starts one, any other line carries on
    the one above."""
    paragraphs: list[str] = []
    for line in lines:
        text = tidy(line)
        if not paragraphs or list_item.match(text):
            paragraphs.append(text)
        else:
            paragraphs[-1] = f"{paragraphs[-1]} {text}"
    return paragraphs


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
