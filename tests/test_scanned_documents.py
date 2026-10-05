"""Seam 1: the transmittal letters and Management Responsibility statements, from the real AARs.

Most are scans, read from the committed, proofread OCR transcriptions in `data/reviewed/`; CY 2024's
letter is a native-text PDF; CY 2021's "Word" letter is a picture inside a Word file. Each is one
section cited by the pages of the PDF (or of the Word file's layout).
"""

import pytest

from coa_explorer import front_matter
from tests.conftest import REPORTS, YEARS

MR = "Management Responsibility for Financial Statements"
TL = "Transmittal Letter"


def only_section(record):
    assert len(record.sections) == 1
    return record.sections[0]


def test_every_year_has_a_transmittal_letter_and_a_management_responsibility_statement(
    transmittal_letters, management_responsibilities
):
    for records, document in ((transmittal_letters, TL), (management_responsibilities, MR)):
        assert sorted(records) == list(YEARS)
        for year, record in records.items():
            assert (record.aar_year, record.document) == (year, document)
            assert only_section(record).text


def test_letters_are_cited_by_the_pages_they_run_over(transmittal_letters):
    citations = {y: only_section(r).citation for y, r in transmittal_letters.items()}

    assert citations == {
        2020: "CY 2020 AAR, Transmittal Letter, pp. 1-2",
        2021: "CY 2021 AAR, Transmittal Letter, pp. 1-2",
        2022: "CY 2022 AAR, Transmittal Letter, pp. 1-2",
        2023: "CY 2023 AAR, Transmittal Letter, pp. 1-3",
        2024: "CY 2024 AAR, Transmittal Letter, pp. 1-3",
    }


def test_the_pages_of_a_scanned_letter_are_its_real_pdf_pages(transmittal_letters):
    record = transmittal_letters[2023]
    letter = only_section(record)

    assert (letter.page_start, letter.page_end, letter.pages) == (1, 3, "1-3")
    assert record.source_file.endswith("01-ManilaCity2023_Transmittal_Letter.pdf")
    # The letter's last PDF page holds only the "Copy furnished" list.
    assert "P472.415 million" in letter.text
    assert letter.text.index("P472.415 million") < letter.text.index("Copy furnished:")


def test_a_statement_is_one_page_and_cited_as_part_I(management_responsibilities):
    for year, record in management_responsibilities.items():
        section = only_section(record)
        assert (section.page_start, section.page_end) == (1, 1)
        assert section.citation == f"CY {year} AAR, Part I, {MR}, p. 1"
        assert f"as at December 31, {year}" in section.text.replace("\n", " ")
        assert "JONATHAN R. GALORIO" in section.text


def test_each_statement_is_signed_by_the_mayor_of_its_time(management_responsibilities):
    for year in (2020, 2021):
        assert "DOMAGOSO" in only_section(management_responsibilities[year]).text
    for year in (2022, 2023, 2024):
        assert "LACUNA-PANGAN" in only_section(management_responsibilities[year]).text


def test_the_scans_are_read_from_their_proofread_transcriptions(
    transmittal_letters, management_responsibilities
):
    scanned = {
        (y, r.document)
        for records in (transmittal_letters, management_responsibilities)
        for y, r in records.items()
        if r.text_source.startswith("reviewed transcription")
    }

    assert scanned == {(y, MR) for y in YEARS} | {(y, TL) for y in (2020, 2021, 2022, 2023)}
    assert transmittal_letters[2022].text_source == (
        "reviewed transcription: data/reviewed/01-ManilaCity2022_Transmittal_Letter.txt"
    )


def test_the_native_text_letter_is_read_from_its_pdf(transmittal_letters):
    record = transmittal_letters[2024]
    text = only_section(record).text

    assert record.text_source == "PDF text layer"
    assert "Honorable MARIA SHEILAH H. LACUNA-PANGAN" in text
    assert "June 10, 2025" in text
    assert "P4.086 billion" in text
    # Bullets stay separate lines.
    assert "\n• Maintain SLs for all receivable accounts" in text


def test_scan_noise_is_not_in_the_text(transmittal_letters, management_responsibilities):
    noise = ("CamScanner", "LUNGSOD", "RECEIVED", "CONTROL NO", "PILIPINAS", "☆")
    for records in (transmittal_letters, management_responsibilities):
        for year, record in records.items():
            text = only_section(record).text
            for junk in noise:
                assert junk not in text, (year, junk)


def test_bullets_and_hyphenated_words_survive_the_transcription(transmittal_letters):
    text = only_section(transmittal_letters[2023]).text

    assert "the above-mentioned regulations" in text
    assert "\n• Ensure that ALs and Assessed Values are accurately computed" in text
    assert "\n• Henceforth, ascertain that RPUs in the tax maps are included in the AR." in text


def test_the_2021_letter_is_a_picture_whose_text_is_transcribed(transmittal_letters):
    record = transmittal_letters[2021]
    letter = only_section(record)

    assert record.source_file.endswith("01-ManilaCity2021_Transmittal_Letter.docx")
    assert record.text_source == (
        "reviewed transcription: data/reviewed/01-ManilaCity2021_Transmittal_Letter.txt"
    )
    assert "June 29, 2022" in letter.text
    assert "ATTY. MARIA CARMINA PAULITA B. JUGUILON-PAGAYAWAN" in letter.text
    # The picture is page 1; the "Copy furnished" list Word holds as text follows on page 2.
    assert (letter.page_start, letter.page_end) == (1, 2)
    assert letter.text.rstrip().endswith("COA Commission Central Library (soft copy)")


def test_the_2020_letter_is_read_from_the_transcription_not_its_junk_text_layer(
    transmittal_letters,
):
    text = only_section(transmittal_letters[2020]).text

    assert "DOMAGOSO" in text
    assert "DOMAGOS0" not in text
    assert "presented in detail in Part II of the report" in text
    assert "Atty. RESURRECCION C. QUIETA" in text


def test_a_scan_with_no_transcription_is_an_error_not_junk_text(tmp_path):
    with pytest.raises(FileNotFoundError, match="coa-explorer ocr"):
        front_matter.extract_management_responsibility(REPORTS, 2022, reviewed_dir=tmp_path)
    with pytest.raises(FileNotFoundError, match="coa-explorer ocr"):
        front_matter.extract_transmittal_letter(REPORTS, 2021, reviewed_dir=tmp_path)


def test_a_transcription_with_the_wrong_number_of_pages_is_refused(tmp_path):
    (tmp_path / "01-ManilaCity2023_Transmittal_Letter.txt").write_text(
        "=== page 1 ===\nOnly one page.\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="1 pages but the PDF has 3"):
        front_matter.extract_transmittal_letter(REPORTS, 2023, reviewed_dir=tmp_path)
    (tmp_path / "01-ManilaCity2021_Transmittal_Letter.txt").write_text(
        "=== page 1 ===\nOne.\n=== page 2 ===\nTwo.\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="2 pages but .* 1 pictures"):
        front_matter.extract_transmittal_letter(REPORTS, 2021, reviewed_dir=tmp_path)


def test_a_native_text_letter_needs_no_transcription(tmp_path):
    record = front_matter.extract_transmittal_letter(REPORTS, 2024, reviewed_dir=tmp_path)

    assert record.text_source == "PDF text layer"


def test_the_committed_transcriptions_are_exactly_the_scans():
    reviewed = REPORTS.parent / "data" / "reviewed"

    assert sorted(p.name for p in reviewed.glob("*.txt")) == sorted(
        [
            "05-ManilaCity2023_Part1-Auditor's_Report.txt",
            *(f"01-ManilaCity{y}_Transmittal_Letter.txt" for y in (2020, 2021, 2022, 2023)),
            *(f"06-ManilaCity{y}_Part1-Mgmt_Responsibility_for_FS.txt" for y in YEARS),
        ]
    )
