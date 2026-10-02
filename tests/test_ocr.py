"""The `ocr` step: Document AI reads the scans, and only when asked.

Document AI is scripted here (a fake reader that returns a line per page); no test uses GCP.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from pypdf import PdfReader

from coa_explorer.cli import main
from coa_explorer.pdf_reader import read_pages
from tests.conftest import REPORTS

SCANNED = {
    2020: [
        "01-ManilaCity2020_Transmittal_Letter",
        "06-ManilaCity2020_Part1-Mgmt_Responsibility_for_FS",
    ],
    2021: [
        "01-ManilaCity2021_Transmittal_Letter",
        "06-ManilaCity2021_Part1-Mgmt_Responsibility_for_FS",
    ],
    2022: [
        "01-ManilaCity2022_Transmittal_Letter",
        "06-ManilaCity2022_Part1-Mgmt_Responsibility_for_FS",
    ],
    2023: [
        "01-ManilaCity2023_Transmittal_Letter",
        "06-ManilaCity2023_Part1-Mgmt_Responsibility_for_FS",
    ],
    2024: ["06-ManilaCity2024_Part1-Mgmt_Responsibility_for_FS"],
}


class FakeOcr:
    """Reads a PDF as one numbered line per page, and a picture as one page."""

    def __init__(self):
        self.calls: list[str] = []

    def read(self, content: bytes, mime_type: str) -> list[str]:
        self.calls.append(mime_type)
        if mime_type == "application/pdf":
            count = len(PdfReader(io.BytesIO(content)).pages)
            return [f"scanned text of page {n}" for n in range(1, count + 1)]
        assert mime_type == "image/png"
        return ["scanned text of the picture"]


def run_ocr(tmp_path: Path, *extra: str, reader: FakeOcr | None = None) -> int:
    return main(["ocr", "--reviewed", str(tmp_path), *extra], ocr_reader=reader or FakeOcr())


def test_ocr_writes_a_transcription_for_each_scanned_document_and_no_other(tmp_path):
    assert run_ocr(tmp_path) == 0

    written = sorted(p.stem for p in tmp_path.glob("*.txt"))
    assert written == sorted(name for names in SCANNED.values() for name in names)


def test_a_transcription_has_one_page_heading_per_pdf_page(tmp_path):
    run_ocr(tmp_path)

    letter = tmp_path / "01-ManilaCity2023_Transmittal_Letter.txt"
    assert re.findall(r"^=== page \d+ ===$", letter.read_text(encoding="utf-8"), re.M) == [
        "=== page 1 ===",
        "=== page 2 ===",
        "=== page 3 ===",
    ]
    # The file loads exactly as the PDF reader loads a reviewed transcription.
    pdf = (
        REPORTS
        / "Manila-City-Annual-Audit-Report-2023/AAR/01-ManilaCity2023_Transmittal_Letter.pdf"
    )
    pages = read_pages(pdf, tmp_path)
    assert [p.number for p in pages] == [1, 2, 3]
    assert pages[1].lines[0] == "scanned text of page 2"


def test_the_picture_a_Word_letter_is_made_of_is_read_as_its_one_page(tmp_path):
    run_ocr(tmp_path)

    text = (tmp_path / "01-ManilaCity2021_Transmittal_Letter.txt").read_text(encoding="utf-8")
    assert text == "=== page 1 ===\nscanned text of the picture\n"


def test_a_native_text_letter_is_not_read_by_ocr(tmp_path):
    run_ocr(tmp_path)

    assert not (tmp_path / "01-ManilaCity2024_Transmittal_Letter.txt").exists()


def test_existing_transcriptions_are_not_overwritten_without_asking(tmp_path, capsys):
    run_ocr(tmp_path)
    name = "06-ManilaCity2022_Part1-Mgmt_Responsibility_for_FS.txt"
    (tmp_path / name).write_text("=== page 1 ===\nCorrected by a reviewer.\n", encoding="utf-8")
    reader = FakeOcr()

    assert run_ocr(tmp_path, reader=reader) == 1

    assert "--overwrite" in capsys.readouterr().err
    assert reader.calls == []  # refused before spending anything
    assert "Corrected by a reviewer." in (tmp_path / name).read_text(encoding="utf-8")
    assert run_ocr(tmp_path, "--overwrite") == 0
    assert "Corrected" not in (tmp_path / name).read_text(encoding="utf-8")


def test_ocr_can_be_limited_to_some_years_and_documents(tmp_path):
    run_ocr(tmp_path, "--years", "2022", "--documents", "management-responsibility")

    assert [p.stem for p in tmp_path.glob("*.txt")] == [
        "06-ManilaCity2022_Part1-Mgmt_Responsibility_for_FS"
    ]
