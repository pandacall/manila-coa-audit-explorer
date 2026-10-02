"""OCR the AAR's scanned short documents with Document AI, into reviewed transcriptions.

The transmittal letters of 2020-2023 and every year's Management Responsibility statement are
pictures of paper: scans in PDF, or (CY 2021's letter) a PNG inside a Word file. Their text layers,
where they have one, are junk. Document AI Enterprise OCR reads them once, on request, and writes
`<reviewed_dir>/<file name>.txt`, one `=== page N ===` heading per page, which is the format
`pdf_reader.read_pages` already loads. A person then proofreads the file against the scan and
commits it; `coa-explorer extract` and `index` read only the committed text, so they need no GCP
access. Re-running this step is never part of a normal run, and it refuses to replace a
transcription that may hold a reviewer's corrections unless told to.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from PIL import Image

from coa_explorer.docx_reader import embedded_images
from coa_explorer.front_matter import (
    MANAGEMENT_RESPONSIBILITY,
    MANAGEMENT_RESPONSIBILITY_FILE,
    SCANNED,
    TRANSMITTAL_LETTER,
    TRANSMITTAL_LETTER_FILE,
    find_file,
)

# Document AI's OCR reads small pictures poorly; CY 2021's letter is 473 x 663 px.
MIN_PICTURE_WIDTH = 1600

FILE_PATTERNS = {
    TRANSMITTAL_LETTER: TRANSMITTAL_LETTER_FILE,
    MANAGEMENT_RESPONSIBILITY: MANAGEMENT_RESPONSIBILITY_FILE,
}


class OcrReader(Protocol):
    def read(self, content: bytes, mime_type: str) -> list[str]:
        """The text of each page of a PDF, or of the one page of a picture."""
        ...


@dataclass(frozen=True)
class Scan:
    year: int
    document: str
    path: Path


def scans(reports_dir: Path, years: list[int], documents: list[str]) -> list[Scan]:
    return [
        Scan(year, document, find_file(reports_dir, year, FILE_PATTERNS[document]))
        for document in documents
        for year in sorted(set(years) & set(SCANNED[document]))
    ]


def transcription_path(scan: Scan, reviewed_dir: Path) -> Path:
    return reviewed_dir / f"{scan.path.stem}.txt"


def read_scan(scan: Scan, reader: OcrReader) -> list[str]:
    """The OCR text of each page of the scan."""
    if scan.path.suffix == ".pdf":
        return reader.read(scan.path.read_bytes(), "application/pdf")
    pages: list[str] = []
    for _, picture in embedded_images(scan.path):
        pages.extend(reader.read(_enlarged(picture), "image/png"))
    return pages


def render(pages: list[str]) -> str:
    return "".join(
        f"=== page {number} ===\n{text.strip(chr(10))}\n" for number, text in enumerate(pages, 1)
    )


def _tidy(text: str) -> str:
    """Document AI pads some lines; nothing else is changed."""
    return "\n".join(line.rstrip() for line in text.strip("\n").split("\n"))


def _enlarged(picture: bytes) -> bytes:
    image = Image.open(io.BytesIO(picture)).convert("RGB")
    if image.width < MIN_PICTURE_WIDTH:
        factor = -(-MIN_PICTURE_WIDTH // image.width)
        image = image.resize((image.width * factor, image.height * factor), Image.LANCZOS)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


class DocumentAiOcr:
    """Document AI Enterprise OCR: the project's `OCR_PROCESSOR`, found by type in `location`."""

    def __init__(self, project: str, location: str, processor: str | None = None):
        from google.cloud import documentai_v1 as documentai

        self._documentai = documentai
        self._client = documentai.DocumentProcessorServiceClient(
            client_options={"api_endpoint": f"{location}-documentai.googleapis.com"}
        )
        parent = f"projects/{project}/locations/{location}"
        self._processor = processor or self._find_processor(parent)

    def _find_processor(self, parent: str) -> str:
        for processor in self._client.list_processors(parent=parent):
            if processor.type_ == "OCR_PROCESSOR" and processor.state.name == "ENABLED":
                return processor.name
        raise SystemExit(
            f"no enabled Document AI OCR_PROCESSOR under {parent}; create one in the console or"
            " set DOCUMENT_AI_PROCESSOR"
        )

    def read(self, content: bytes, mime_type: str) -> list[str]:
        documentai = self._documentai
        result = self._client.process_document(
            request=documentai.ProcessRequest(
                name=self._processor,
                raw_document=documentai.RawDocument(content=content, mime_type=mime_type),
            )
        )
        document = result.document
        return [
            "".join(
                document.text[int(segment.start_index) : int(segment.end_index)]
                for segment in page.layout.text_anchor.text_segments
            )
            for page in document.pages
        ]
