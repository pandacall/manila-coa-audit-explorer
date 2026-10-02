"""Seam 1: the Executive Summary and the Auditor's Report, extracted from the real, committed AARs.

Executive Summary pages are the lowercase Roman numerals COA prints; Auditor's Report pages are
plain numbers. Word pages are derived from the saved layout (ADR-0001); PDF pages are real.
"""

import re
from pathlib import Path

import pytest
from pypdf import PdfReader

from coa_explorer import front_matter
from coa_explorer.front_matter import FrontMatter
from tests.conftest import REPORTS, YEARS

HEADINGS = {
    2020: "ABCDEFGH",
    2021: "ABCDEFG",
    2022: "ABCDEFG",
    2023: "ABCDEFGH",
    2024: "ABCDEFG",
}


def section(record: FrontMatter, heading_start: str):
    matches = [s for s in record.sections if s.heading.startswith(heading_start)]
    assert len(matches) == 1, [s.heading for s in record.sections]
    return matches[0]


# ---------------------------------------------------------------------------------------------
# Every year has both documents


def test_every_year_has_an_executive_summary_and_an_auditors_report(
    executive_summaries, auditors_reports
):
    assert sorted(executive_summaries) == list(YEARS)
    assert sorted(auditors_reports) == list(YEARS)
    for year in YEARS:
        assert executive_summaries[year].sections
        assert auditors_reports[year].sections


def test_each_executive_summary_has_COAs_lettered_sections(executive_summaries):
    for year, expected in HEADINGS.items():
        labels = "".join(s.label for s in executive_summaries[year].sections)
        assert labels == expected, year


def test_the_executive_summary_sections_are_COAs_headings_in_order(executive_summaries):
    headings = [s.heading for s in executive_summaries[2023].sections]
    assert headings == [
        "Introduction",
        "Financial Highlights",
        "Operational Highlights",
        "Scope and Objectives of Audit",
        "Auditor’s Opinion on the Financial Statements",
        "Significant Audit Observations and Recommendations",
        "Summary of Suspensions, Disallowances and Charges as of Year-end",
        "Status of Implementation of Prior Years’ Audit Recommendations",
    ]


def test_every_auditors_report_gives_the_opinion_with_its_basis(auditors_reports):
    for year in YEARS:
        record = auditors_reports[year]
        opinion = section(record, "Qualified Opinion")
        assert "except for the effects" in opinion.text, year
        assert any(
            s.heading.startswith("Bas") and "Qualified Opinion" in s.heading
            for s in record.sections
        ), year


def test_the_auditors_report_sections_follow_COAs_standard_form(auditors_reports):
    headings = [s.heading for s in auditors_reports[2022].sections]
    assert headings == [
        "Independent Auditor’s Report",
        "Report on the Financial Statements",
        "Qualified Opinion",
        "Bases for Qualified Opinion",
        "Emphasis of Matter Paragraph",
        "Responsibilities of Management and Those Charged with Governance for the Financial "
        "Statements",
        "Auditor’s Responsibilities for the Audit of the Financial Statements",
    ]


# ---------------------------------------------------------------------------------------------
# Executive Summary pages are lowercase Roman numerals


def test_word_executive_summary_pages_are_lowercase_roman(executive_summaries):
    suspensions_2021 = section(executive_summaries[2021], "Summary of Suspensions")
    assert suspensions_2021.pages == "vi"
    assert suspensions_2021.citation == ("CY 2021 AAR, Executive Summary, Section F, p. vi")
    opinion_2023 = section(executive_summaries[2023], "Auditor’s Opinion")
    assert (opinion_2023.page_start, opinion_2023.pages) == (3, "iii-iv")
    operational_2022 = section(executive_summaries[2022], "Operational Highlights")
    assert operational_2022.pages == "ii-iii"
    assert operational_2022.citation == ("CY 2022 AAR, Executive Summary, Section C, pp. ii-iii")
    assert executive_summaries[2021].page_format == "lowerRoman"


@pytest.mark.parametrize("year", [2021, 2022, 2023])
def test_word_executive_summary_pages_agree_with_COAs_own_PDF_rendering(executive_summaries, year):
    """COA also published PDFs of the 2020-2023 Executive Summaries (kept in `_duplicates/`, never
    extracted). They are used here only as an oracle for where each section really starts."""
    printed = {
        roman: re.sub(r"[^a-z0-9]", "", text.lower())
        for roman, text in pdf_pages_by_label(year).items()
    }
    for s in executive_summaries[year].sections:
        start = re.sub(r"[^a-z0-9]", "", f"{s.label}. {s.heading}".lower())
        page = next(label for label, text in printed.items() if start in text)
        assert s.pages.split("-")[0] == page, (year, s.heading)


def test_the_2020_executive_summary_drifts_by_at_most_a_page(executive_summaries):
    """Word saved no page break after the first table of CY 2020's Executive Summary, so every
    later section is derived one page early (ADR-0001: best-effort pages; the section letter is
    the exact anchor)."""
    printed = pdf_pages_by_label(2020)
    labels = list(printed)
    for s in executive_summaries[2020].sections:
        start = re.sub(r"[^a-z0-9]", "", f"{s.label}. {s.heading}".lower())
        actual = next(
            i
            for i, text in enumerate(printed.values())
            if start in re.sub(r"[^a-z0-9]", "", text.lower())
        )
        assert 0 <= actual - (s.page_start - 1) <= 1, (s.heading, labels[actual])


def pdf_pages_by_label(year: int) -> dict[str, str]:
    pdf = PdfReader(REPORTS / "_duplicates" / f"Manila-City-Executive-Summary-{year}.pdf")
    pages = {}
    for page in pdf.pages:
        text = page.extract_text()
        label = text.split()[0]
        assert re.fullmatch(r"[ivx]+", label), label
        pages[label] = text
    return pages


def test_2024_executive_summary_pdf_keeps_its_printed_roman_pages(executive_summaries):
    record = executive_summaries[2024]
    assert record.source_file.endswith("03-ManilaCity2024_Executive_Summary.pdf")
    assert record.page_format == "lowerRoman"
    scope = section(record, "Scope and Objectives of Audit")
    assert (scope.page_start, scope.pages) == (3, "iii")
    assert scope.citation == "CY 2024 AAR, Executive Summary, Section D, p. iii"
    # Financial Highlights runs on to the revenue table printed on page ii.
    highlights = section(record, "Financial Highlights")
    assert highlights.pages == "i-ii"
    assert "The total revenue of P21.837 billion" in highlights.text
    # A recommendation list that continues on the next printed page stays in its section.
    opinion = section(record, "Auditor’s Opinion")
    assert opinion.pages == "iii-vi"
    assert "Ensure that identified reconciling items in the BRS" in opinion.text
    status = section(record, "Status of Implementation")
    assert status.pages == "vi"
    assert "17 or 62.96 percent were implemented" in status.text


def test_the_pdf_reader_checks_printed_page_numbers_against_pdf_pages():
    from coa_explorer import pdf_reader

    path = (
        REPORTS
        / "Manila-City-Annual-Audit-Report-2024"
        / "AAR"
        / "03-ManilaCity2024_Executive_Summary.pdf"
    )
    pages = pdf_reader.read_pages(path)
    assert [p.number for p in pages] == [1, 2, 3, 4, 5, 6]
    assert [p.label for p in pages] == ["i", "ii", "iii", "iv", "v", "vi"]
    assert not any(line.strip() in {"i", "ii", "iii"} for line in pages[2].lines)


# ---------------------------------------------------------------------------------------------
# Auditor's Report pages: real PDF pages, or derived from Word for CY 2020-2021


def test_pdf_auditors_report_sections_carry_their_real_pdf_pages(auditors_reports):
    for year, emphasis_page in ((2022, 2), (2023, 2), (2024, 3)):
        record = auditors_reports[year]
        assert record.source_file.endswith(".pdf"), year
        assert record.page_format == "decimal"
        emphasis = section(record, "Emphasis of Matter")
        assert emphasis.page_start == emphasis_page, year
        assert emphasis.citation == (f"CY {year} AAR, Part I, Auditor's Report, p. {emphasis_page}")
        qualified = section(record, "Qualified Opinion")
        assert (qualified.page_start, qualified.page_end) == (1, 1), year


def test_a_section_that_runs_over_a_page_cites_the_range(auditors_reports):
    responsibilities = section(auditors_reports[2022], "Auditor’s Responsibilities")
    assert (responsibilities.page_start, responsibilities.page_end) == (2, 3)
    assert responsibilities.citation == "CY 2022 AAR, Part I, Auditor's Report, pp. 2-3"
    # The sentence that carries over a page break is whole.
    assert "required to draw attention in our auditor’s report" in responsibilities.text


def test_word_auditors_reports_for_2020_and_2021(auditors_reports):
    for year in (2020, 2021):
        record = auditors_reports[year]
        assert record.source_file.endswith(".docx")
        assert section(record, "Emphasis of Matter").page_start == 2
    mayor_2020 = section(auditors_reports[2020], "Independent Auditor’s Report")
    assert "FRANCISCO “ISKO MORENO” DOMAGOSO" in mayor_2020.text
    basis_2021 = section(auditors_reports[2021], "Bases for Qualified Opinion")
    assert "cash advances totaling P182.725 million" in basis_2021.text
    assert (basis_2021.page_start, basis_2021.page_end) == (1, 2)


def test_the_opinion_on_each_year_is_a_qualified_opinion_in_COAs_words(auditors_reports):
    texts = {y: section(auditors_reports[y], "Qualified Opinion").text for y in YEARS}
    for year, text in texts.items():
        assert "except for the effects" in text, year
        assert "present fairly" in text or "presents fairly" in text, year
    assert "December 31, 2024" in texts[2024]


# ---------------------------------------------------------------------------------------------
# The 2023 Auditor's Report is a scan: its text is a reviewed transcription


def test_the_2023_auditors_report_uses_the_reviewed_transcription(auditors_reports):
    record = auditors_reports[2023]
    assert record.text_source == (
        "reviewed transcription: data/reviewed/05-ManilaCity2023_Part1-Auditor's_Report.txt"
    )
    bases = section(record, "Bases for Qualified Opinion")
    assert "Section 74 of Presidential Decree No. 1445" in bases.text
    assert "P9.237 billion" in bases.text
    assert "P525.085 million" in bases.text
    assert bases.page_start == 1
    # A paragraph carried over a page break is rejoined.
    ethical = bases.text.split("\n")[-1]
    assert ethical.endswith(
        "fulfilled our other ethical responsibilities in accordance with "
        "these requirements. We believe that the audit evidence we have "
        "obtained is sufficient and appropriate to provide a basis for our "
        "opinion."
    )
    assert (bases.page_start, bases.page_end) == (1, 2)


def test_the_garbled_text_layer_of_the_scan_is_not_used(auditors_reports):
    text = " ".join(s.text for s in auditors_reports[2023].sections)
    for junk in ("ltatementa", "Fln", "S.sa for", "dllectly", "aummary"):
        assert junk not in text


def test_only_the_scan_is_read_from_a_transcription(auditors_reports, executive_summaries):
    transcribed = [
        (y, r.text_source)
        for records in (auditors_reports, executive_summaries)
        for y, r in records.items()
        if r.text_source.startswith("reviewed transcription")
    ]
    assert [y for y, _ in transcribed] == [2023]


def test_a_transcription_with_the_wrong_number_of_pages_is_refused(tmp_path):
    reviewed = tmp_path / "05-ManilaCity2023_Part1-Auditor's_Report.txt"
    reviewed.write_text("=== page 1 ===\nOnly one page.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="3 pages"):
        front_matter.extract_auditors_report(REPORTS, 2023, reviewed_dir=tmp_path)


# ---------------------------------------------------------------------------------------------
# The duplicates stay out


def test_the_duplicate_executive_summary_pdfs_are_not_extracted(executive_summaries):
    for year in YEARS:
        source = executive_summaries[year].source_file
        assert "_duplicates" not in source
        assert Path(source).name.startswith("03-")
    assert not any(
        "_duplicates" in s.citation or "_duplicates" in s.text
        for r in executive_summaries.values()
        for s in r.sections
    )


# ---------------------------------------------------------------------------------------------
# Content survives the extraction


def test_executive_summary_tables_and_lists_are_kept(executive_summaries):
    highlights_2021 = section(executive_summaries[2021], "Financial Highlights")
    assert "| Assets | 62,542,872,024.44 | 59,923,855,115.94 | 2,619,016,908.50 |" in (
        highlights_2021.text
    )
    operational_2024 = section(executive_summaries[2024], "Operational Highlights")
    assert "Seal of Local Good Governance" in operational_2024.text
    assert operational_2024.text.count("\n") > 10  # list items stay separate lines
    revenue_2024 = section(executive_summaries[2024], "Financial Highlights").text
    assert "Tax Revenue | 10,126,851,810.31 | 5,607,943,359.23 | 15,734,795,169.54" in revenue_2024


def test_executive_summary_says_the_audit_opinion_in_each_year(executive_summaries):
    for year in YEARS:
        opinion = next(
            s
            for s in executive_summaries[year].sections
            if "Opinion" in s.heading or "Auditor’s Report" in s.heading
        )
        assert "qualified opinion" in opinion.text, year
