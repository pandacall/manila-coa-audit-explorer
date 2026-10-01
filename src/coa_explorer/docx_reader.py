"""Read a Word (.docx) file into paragraphs and tables with printed list labels and derived pages.

Word stores neither list numbers nor page numbers in the text, so both are rebuilt:

* List labels ("1", "2.3", "a.") come from the numbering definitions, replaying Word's counter
  rules.
* Pages come from the section's starting page number plus the page breaks Word saved when it last
  laid the document out (``w:lastRenderedPageBreak``), plus explicit page breaks. A saved break that
  directly follows an explicit page break is the same break, so it is skipped (ADR-0001).
"""

from __future__ import annotations

import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from xml.etree import ElementTree as ET

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MC = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"


@dataclass(frozen=True)
class Paragraph:
    text: str
    bold: bool
    label: str | None  # printed list label, e.g. "3." or "1.9"; None when not numbered
    list_id: int | None  # abstract list the paragraph belongs to
    level: int | None
    page: int  # page on which the paragraph's text begins
    end_page: int  # page on which the paragraph's text ends


@dataclass(frozen=True)
class Table:
    markdown: str
    page: int
    end_page: int


Block = Paragraph | Table


def read_blocks(path: Path) -> list[Block]:
    """Read the document body as non-empty paragraphs and tables, in order."""
    with zipfile.ZipFile(path) as z:
        document = ET.fromstring(z.read("word/document.xml"))
        numbering = _read_part(z, "word/numbering.xml")
        styles = _read_part(z, "word/styles.xml")
    reader = _Reader(Styles(styles), Numbering(numbering, Styles(styles)))
    return reader.read(document.find(W + "body"))


def _read_part(z: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        return ET.fromstring(z.read(name))
    except KeyError:
        return None


# ---------------------------------------------------------------------------------------------
# Styles


class Styles:
    """Paragraph and character styles, resolved through their ``basedOn`` chains."""

    def __init__(self, root: ET.Element | None):
        self._styles: dict[str, ET.Element] = {}
        if root is not None:
            for style in root.findall(W + "style"):
                self._styles[style.get(W + "styleId")] = style

    def _chain(self, style_id: str | None) -> Iterator[ET.Element]:
        seen: set[str] = set()
        while style_id and style_id in self._styles and style_id not in seen:
            seen.add(style_id)
            style = self._styles[style_id]
            yield style
            based_on = style.find(W + "basedOn")
            style_id = based_on.get(W + "val") if based_on is not None else None

    def is_bold(self, style_id: str | None) -> bool:
        for style in self._chain(style_id):
            rpr = style.find(W + "rPr")
            if rpr is not None and rpr.find(W + "b") is not None:
                return _on(rpr.find(W + "b"))
        return False

    def num_pr(self, style_id: str | None) -> tuple[int | None, int | None]:
        """The (numId, ilvl) a paragraph style carries, nearest definition first."""
        num_id = ilvl = None
        for style in self._chain(style_id):
            num_pr = _child(style, "pPr", "numPr")
            if num_pr is None:
                continue
            if num_id is None:
                num_id = _int_val(num_pr.find(W + "numId"))
            if ilvl is None:
                ilvl = _int_val(num_pr.find(W + "ilvl"))
        return num_id, ilvl


def _on(element: ET.Element | None) -> bool:
    return element is not None and element.get(W + "val") not in ("0", "false", "off")


def _child(element: ET.Element, *names: str) -> ET.Element | None:
    for name in names:
        element = element.find(W + name)
        if element is None:
            return None
    return element


def _int_val(element: ET.Element | None) -> int | None:
    if element is None or element.get(W + "val") is None:
        return None
    return int(element.get(W + "val"))


# ---------------------------------------------------------------------------------------------
# Numbering


@dataclass
class _Level:
    start: int = 1
    fmt: str = "decimal"
    text: str = "%1."
    restart: int | None = None  # lvlRestart; 0 means never restart
    legal: bool = False


@dataclass
class _List:
    counters: dict[int, int] = field(default_factory=dict)


class Numbering:
    """Replays Word's list-numbering rules to find the label printed for each numbered paragraph."""

    def __init__(self, root: ET.Element | None, styles: Styles):
        self._styles = styles
        self._abstract: dict[int, dict[int, _Level]] = {}
        self._nums: dict[int, int] = {}
        self._start_overrides: dict[int, dict[int, int]] = {}
        self._level_overrides: dict[int, dict[int, _Level]] = {}
        self._lists: dict[int, _List] = {}
        self._overrides_applied: set[tuple[int, int]] = set()
        if root is None:
            return
        for abstract in root.findall(W + "abstractNum"):
            levels = {
                int(lvl.get(W + "ilvl")): _parse_level(lvl) for lvl in abstract.findall(W + "lvl")
            }
            self._abstract[int(abstract.get(W + "abstractNumId"))] = levels
        for num in root.findall(W + "num"):
            num_id = int(num.get(W + "numId"))
            self._nums[num_id] = int(num.find(W + "abstractNumId").get(W + "val"))
            for override in num.findall(W + "lvlOverride"):
                ilvl = int(override.get(W + "ilvl"))
                start = _int_val(override.find(W + "startOverride"))
                if start is not None:
                    self._start_overrides.setdefault(num_id, {})[ilvl] = start
                lvl = override.find(W + "lvl")
                if lvl is not None:
                    self._level_overrides.setdefault(num_id, {})[ilvl] = _parse_level(lvl)

    def resolve(self, para: ET.Element) -> tuple[int | None, int | None]:
        """The (numId, ilvl) in force for a paragraph, from its own properties or its style."""
        ppr = para.find(W + "pPr")
        style_id = None
        num_id = ilvl = None
        if ppr is not None:
            style = ppr.find(W + "pStyle")
            style_id = style.get(W + "val") if style is not None else None
            num_pr = ppr.find(W + "numPr")
            if num_pr is not None:
                num_id = _int_val(num_pr.find(W + "numId"))
                ilvl = _int_val(num_pr.find(W + "ilvl"))
        style_num_id, style_ilvl = self._styles.num_pr(style_id)
        if num_id is None:
            num_id = style_num_id
        if ilvl is None:
            ilvl = style_ilvl if style_ilvl is not None else 0
        return num_id, ilvl

    def advance(self, num_id: int | None, ilvl: int | None) -> tuple[str | None, int | None]:
        """Count one paragraph into its list; return its printed label and abstract list id."""
        if not num_id or num_id not in self._nums:
            return None, None
        abstract_id = self._nums[num_id]
        levels = self._abstract.get(abstract_id, {})
        if ilvl not in levels:
            return None, None
        list_ = self._lists.setdefault(abstract_id, _List())

        # A numId's own start override applies the first time that numId reaches the level.
        override = self._start_overrides.get(num_id, {}).get(ilvl)
        if override is not None and (num_id, ilvl) not in self._overrides_applied:
            self._overrides_applied.add((num_id, ilvl))
            list_.counters[ilvl] = override
        elif ilvl in list_.counters:
            list_.counters[ilvl] += 1
        else:
            list_.counters[ilvl] = self._level(num_id, abstract_id, ilvl).start
        for deeper in [lvl for lvl in list_.counters if lvl > ilvl]:
            if self._level(num_id, abstract_id, deeper).restart != 0:
                del list_.counters[deeper]
        return self._label(num_id, abstract_id, list_, ilvl), abstract_id

    def _level(self, num_id: int, abstract_id: int, ilvl: int) -> _Level:
        override = self._level_overrides.get(num_id, {}).get(ilvl)
        return override or self._abstract[abstract_id].get(ilvl) or _Level()

    def _label(self, num_id: int, abstract_id: int, list_: _List, ilvl: int) -> str:
        level = self._level(num_id, abstract_id, ilvl)

        def counter(n: int) -> str:
            lvl = self._level(num_id, abstract_id, n)
            value = list_.counters.get(n, lvl.start)
            fmt = "decimal" if level.legal and n != ilvl else lvl.fmt
            return _format_number(value, fmt)

        label = re.sub(r"%(\d)", lambda m: counter(int(m.group(1)) - 1), level.text)
        # Bullets are drawn from a symbol font as private-use characters; they carry no number.
        return re.sub(r"[-]", "", label).strip()


def _parse_level(lvl: ET.Element) -> _Level:
    def val(name: str) -> str | None:
        element = lvl.find(W + name)
        return element.get(W + "val") if element is not None else None

    return _Level(
        start=int(val("start") or 1),
        fmt=val("numFmt") or "decimal",
        text=val("lvlText") or "",
        restart=int(val("lvlRestart")) if val("lvlRestart") is not None else None,
        legal=lvl.find(W + "isLgl") is not None,
    )


def _format_number(value: int, fmt: str) -> str:
    if fmt == "decimal":
        return str(value)
    if fmt == "decimalZero":
        return f"{value:02d}"
    if fmt in ("lowerLetter", "upperLetter"):
        letters = ""
        n = value
        while n > 0:
            n, rem = divmod(n - 1, 26)
            letters = chr(ord("a") + rem) + letters
        return letters if fmt == "lowerLetter" else letters.upper()
    if fmt in ("lowerRoman", "upperRoman"):
        roman = _roman(value)
        return roman if fmt == "upperRoman" else roman.lower()
    if fmt == "none":
        return ""
    return str(value)


def _roman(value: int) -> str:
    out = ""
    for amount, numeral in (
        (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
        (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
    ):  # fmt: skip
        while value >= amount:
            out += numeral
            value -= amount
    return out


# ---------------------------------------------------------------------------------------------
# Pages


class _Pages:
    """Tracks the current page as breaks are met, in document order."""

    def __init__(self, first_page: int):
        self.page = first_page
        self._after_explicit_break = False

    def explicit_break(self) -> None:
        self.page += 1
        self._after_explicit_break = True

    def saved_break(self) -> None:
        if self._after_explicit_break:
            self._after_explicit_break = False  # the same break, saved again by Word
        else:
            self.page += 1

    def text(self, text: str) -> None:
        if text.strip():
            self._after_explicit_break = False

    def new_section(self, start: int | None, starts_new_page: bool) -> None:
        if starts_new_page:
            self.page = start if start is not None else self.page + 1
        self._after_explicit_break = False


# ---------------------------------------------------------------------------------------------
# Reader


class _Reader:
    def __init__(self, styles: Styles, numbering: Numbering):
        self._styles = styles
        self._numbering = numbering
        self._blocks: list[Block] = []
        self._pages = _Pages(1)
        self._sections: list[ET.Element] = []
        self._section_index = 0

    def read(self, body: ET.Element) -> list[Block]:
        self._sections = list(body.iter(W + "sectPr"))
        self._pages = _Pages(self._section_start(0) or 1)
        self._read_children(body)
        return self._blocks

    def _section_start(self, index: int) -> int | None:
        if index >= len(self._sections):
            return None
        pg = self._sections[index].find(W + "pgNumType")
        return _int_attr(pg, "start") if pg is not None else None

    def _read_children(self, parent: ET.Element) -> None:
        for child in parent:
            if child.tag == W + "p":
                self._read_paragraph(child)
            elif child.tag == W + "tbl":
                self._read_table(child)
            elif child.tag == W + "sdt":
                content = child.find(W + "sdtContent")
                if content is not None:
                    self._read_children(content)

    def _read_paragraph(self, para: ET.Element) -> None:
        num_id, ilvl = self._numbering.resolve(para)
        label, list_id = self._numbering.advance(num_id, ilvl)
        ppr = para.find(W + "pPr")
        style_id = None
        page_break_before = False
        if ppr is not None:
            style = ppr.find(W + "pStyle")
            style_id = style.get(W + "val") if style is not None else None
            page_break_before = _on(ppr.find(W + "pageBreakBefore"))
        paragraph_bold = self._styles.is_bold(style_id)

        if page_break_before:
            self._pages.explicit_break()
        pieces = self._pieces(para, paragraph_bold)
        text, bold, page, end_page = self._consume(pieces)
        if text:
            self._blocks.append(
                Paragraph(
                    text,
                    bold,
                    label or None,
                    list_id,
                    ilvl if list_id is not None else None,
                    page,
                    end_page,
                )
            )

        if ppr is not None and ppr.find(W + "sectPr") is not None:
            self._end_section()

    def _end_section(self) -> None:
        self._section_index += 1
        if self._section_index < len(self._sections):
            next_section = self._sections[self._section_index]
            kind = next_section.find(W + "type")
            continuous = kind is not None and kind.get(W + "val") == "continuous"
            self._pages.new_section(self._section_start(self._section_index), not continuous)

    def _consume(self, pieces: list[tuple[str, object]]) -> tuple[str, bool, int, int]:
        """Walk a paragraph's text and breaks; return its text, boldness and first/last page."""
        chars: list[tuple[str, bool]] = []
        first_page: int | None = None
        last_page: int | None = None
        for kind, value in pieces:
            if kind == "lrpb":
                self._pages.saved_break()
            elif kind == "break":
                self._pages.explicit_break()
            else:
                text, bold = value
                self._pages.text(text)
                if text.strip():
                    if first_page is None:
                        first_page = self._pages.page
                    last_page = self._pages.page
                chars.extend((c, bold) for c in text)
        text = "".join(c for c, _ in chars)
        normalised = re.sub(r"\s+", " ", text).strip()
        visible = [bold for c, bold in chars if not c.isspace()]
        all_bold = bool(visible) and all(visible)
        page = first_page if first_page is not None else self._pages.page
        return normalised, all_bold, page, last_page if last_page is not None else page

    def _pieces(self, para: ET.Element, paragraph_bold: bool) -> list[tuple[str, object]]:
        pieces: list = []
        for el in _walk(para):
            if el.tag == W + "r":
                rpr = el.find(W + "rPr")
                bold = paragraph_bold
                if rpr is not None:
                    if rpr.find(W + "b") is not None:
                        bold = _on(rpr.find(W + "b"))
                    elif rpr.find(W + "rStyle") is not None:
                        bold = bold or self._styles.is_bold(rpr.find(W + "rStyle").get(W + "val"))
                for item in el:
                    if item.tag == W + "t":
                        pieces.append(("text", (item.text or "", bold)))
                    elif item.tag in (W + "tab", W + "ptab"):
                        pieces.append(("text", (" ", bold)))
                    elif item.tag == W + "noBreakHyphen":
                        pieces.append(("text", ("-", bold)))
                    elif item.tag == W + "br":
                        kind = item.get(W + "type")
                        if kind == "page":
                            pieces.append(("break", True))
                        else:
                            pieces.append(("text", (" ", bold)))
                    elif item.tag == W + "cr":
                        pieces.append(("text", (" ", bold)))
                    elif item.tag == W + "lastRenderedPageBreak":
                        pieces.append(("lrpb", True))
        return pieces

    def _read_table(self, table: ET.Element) -> None:
        start = len(self._blocks)
        rows: list[list[str]] = []
        first_page = self._pages.page
        for row in table.findall(W + "tr"):
            cells: list[str] = []
            for cell in row.findall(W + "tc"):
                before = len(self._blocks)
                self._read_children(cell)
                added = self._blocks[before:]
                del self._blocks[before:]
                text = " ".join(_block_text(b) for b in added)
                span = _int_attr(_child(cell, "tcPr", "gridSpan"), "val") or 1
                cells.append(text)
                cells.extend([""] * (span - 1))
            rows.append(cells)
        del self._blocks[start:]
        markdown = _markdown_table(rows)
        if markdown:
            self._blocks.append(Table(markdown, first_page, self._pages.page))


def _walk(para: ET.Element) -> Iterator[ET.Element]:
    """Runs of a paragraph in document order, skipping deletions, drawings and fallbacks."""
    skip = {W + "del", W + "drawing", W + "pict", W + "object", W + "pPr", MC + "Fallback"}
    for child in para:
        if child.tag in skip:
            continue
        if child.tag == W + "r":
            yield child
        else:
            yield from _walk(child)


def _block_text(block: Block) -> str:
    return block.text if isinstance(block, Paragraph) else block.markdown


def _int_attr(element: ET.Element | None, name: str) -> int | None:
    if element is None or element.get(W + name) is None:
        return None
    return int(element.get(W + name))


def _markdown_table(rows: list[list[str]]) -> str:
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)

    def line(cells: list[str]) -> str:
        padded = cells + [""] * (width - len(cells))
        return "| " + " | ".join(c.replace("|", "\\|").strip() for c in padded) + " |"

    out = [line(rows[0]), "| " + " | ".join(["---"] * width) + " |"]
    out.extend(line(r) for r in rows[1:])
    return "\n".join(out)
