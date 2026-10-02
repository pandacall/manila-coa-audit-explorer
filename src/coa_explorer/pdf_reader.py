"""Read a PDF into pages of text lines, keeping the PDF's real page numbers.

This reads the text a PDF already carries; it does not OCR. A scanned PDF whose text layer is
missing or unreliable (the CY 2023 Auditor's Report is one) is read instead from a reviewed
transcription: `<reviewed_dir>/<pdf file name>.txt`, one `=== page N ===` heading per PDF page,
committed only after a person has proofread it against the page images.

Lines keep their layout spacing, so a caller can tell table columns from justified prose. A page
number printed alone on the last line of a page is taken off the text and returned as the page's
`label`, so callers can check it against the PDF's own page order.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

PAGE_MARKER = re.compile(r"^=== page (\d+) ===$")
PRINTED_NUMBER = re.compile(r"^(?:\d{1,3}|[ivxlc]{1,6})$")
# Symbol-font bullets come out as private-use characters.
PRIVATE_USE = re.compile("[-]")


@dataclass(frozen=True)
class PdfPage:
    number: int  # 1-based position in the PDF
    label: str | None  # the page number printed on the page ("iii", "2"), if there is one
    lines: tuple[str, ...]  # text lines in reading order; blank lines kept as ""


def reviewed_path(pdf: Path, reviewed_dir: Path | None) -> Path | None:
    """The reviewed transcription that stands in for this PDF's text layer, if there is one."""
    if reviewed_dir is None:
        return None
    path = reviewed_dir / f"{pdf.stem}.txt"
    return path if path.exists() else None


def read_pages(pdf: Path, reviewed_dir: Path | None = None) -> list[PdfPage]:
    """The PDF's pages, from its reviewed transcription when there is one, else its text layer."""
    reviewer = reviewed_path(pdf, reviewed_dir)
    reader = PdfReader(pdf)
    if reviewer is not None:
        pages = _read_transcription(reviewer)
        if len(pages) != len(reader.pages):
            raise ValueError(
                f"{reviewer.name} has {len(pages)} pages but the PDF has {len(reader.pages)} pages"
            )
        return pages
    return [
        _page(number, page.extract_text(extraction_mode="layout"))
        for number, page in enumerate(reader.pages, start=1)
    ]


def _read_transcription(path: Path) -> list[PdfPage]:
    pages: list[list[str]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        marker = PAGE_MARKER.match(line.strip())
        if marker:
            if int(marker.group(1)) != len(pages) + 1:
                raise ValueError(f"{path.name}: page {marker.group(1)} is out of order")
            pages.append([])
        elif pages:
            pages[-1].append(line)
        elif line.strip():
            raise ValueError(f"{path.name}: text before the first '=== page 1 ===' heading")
    return [PdfPage(number, None, tuple(lines)) for number, lines in enumerate(pages, start=1)]


def _page(number: int, text: str) -> PdfPage:
    lines = [PRIVATE_USE.sub("•", line).rstrip() for line in text.splitlines()]
    label = None
    last = next((i for i in range(len(lines) - 1, -1, -1) if lines[i].strip()), None)
    if last is not None and PRINTED_NUMBER.match(lines[last].strip()):
        label = lines[last].strip()
        del lines[last:]
    return PdfPage(number, label, tuple(lines))
