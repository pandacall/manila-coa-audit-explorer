"""Seam 1: the Notes to Financial Statements, extracted from the real, committed AARs.

Word pages are derived from the saved layout (ADR-0001), so they are checked against what the
documents themselves say about their pagination; the 2024 PDF's pages are the ones it prints.
"""

import re
from pathlib import Path

import pytest
from pypdf import PdfReader

from coa_explorer.docx_reader import Paragraph, read_blocks
from coa_explorer.notes import MAX_PASSAGE_CHARS, Note, Notes
from tests.conftest import REPORTS, YEARS

NOTE_COUNTS = {2020: 31, 2021: 33, 2022: 32, 2023: 35, 2024: 34}


def note(record: Notes, number: int) -> Note:
    matches = [n for n in record.notes if n.number == number]
    assert len(matches) == 1, [n.number for n in record.notes]
    return matches[0]


def text_of(n: Note) -> str:
    return "\n".join(p.text for p in n.passages)


def reports_folder(year: int) -> Path:
    return REPORTS / f"Manila-City-Annual-Audit-Report-{year}"


# ---------------------------------------------------------------------------------------------
# Every year, every Note


def test_each_year_has_its_numbered_notes_counting_up_from_one(notes):
    for year, count in NOTE_COUNTS.items():
        assert [n.number for n in notes[year].notes] == list(range(1, count + 1)), year


def test_a_note_has_COAs_title(notes):
    assert note(notes[2022], 4).title == "Cash and Cash Equivalents"
    assert note(notes[2022], 31).title == "Restatements"
    assert note(notes[2023], 35).title == "Legal Cases and Other Disclosures"
    assert note(notes[2024], 34).title == "Other Regulatory Requirements"
    # The Notes' own numbering drifts between years: Note 18 is not the same Note every year.
    assert note(notes[2021], 18).title == "Share from National Taxes"
    assert note(notes[2022], 18).title == "Share from Internal Revenue Collections (IRA)"


def test_a_note_whose_heading_COA_ran_into_its_text_is_titled_by_its_first_sentence(notes):
    profile = note(notes[2020], 2)

    assert profile.title.startswith("The City of Manila shifted to the preparation of Financial")
    assert profile.title.endswith("(NGAS).")
    assert text_of(profile).startswith(profile.title)


def test_every_note_has_text(notes):
    for year in YEARS:
        for n in notes[year].notes:
            assert n.passages, (year, n.number)


def test_the_title_lines_before_Note_1_belong_to_no_note(notes):
    assert "NOTES TO THE FINANCIAL STATEMENTS" not in text_of(note(notes[2020], 1))
    assert text_of(note(notes[2020], 1)).startswith("The City of Manila was founded")


# ---------------------------------------------------------------------------------------------
# Pages: Word


def test_a_word_note_is_cited_by_note_and_derived_page(notes):
    cash_2022 = note(notes[2022], 4)

    assert (cash_2022.page_start, cash_2022.page_end) == (33, 34)
    assert (
        cash_2022.citation
        == "CY 2022 AAR, Part I, Notes to Financial Statements, Note 4, pp. 33-34"
    )
    assert note(notes[2020], 3).page_start == 12
    one_page = note(notes[2021], 9)
    assert one_page.citation == "CY 2021 AAR, Part I, Notes to Financial Statements, Note 9, p. 42"


def test_every_passage_is_cited_with_its_own_pages(notes):
    ppe = note(notes[2023], 10)

    pages = [(p.page_start, p.page_end) for p in ppe.passages]
    assert len(set(pages)) > 1
    for passage in ppe.passages:
        assert passage.page_start >= ppe.page_start
        assert passage.page_end <= ppe.page_end
        where = (
            f"p. {passage.page_start}"
            if passage.page_start == passage.page_end
            else f"pp. {passage.page_start}-{passage.page_end}"
        )
        assert (
            passage.citation
            == f"CY 2023 AAR, Part I, Notes to Financial Statements, Note 10, {where}"
        )


def test_the_notes_start_where_COAs_table_of_contents_says(notes):
    for year in (2020, 2021, 2022, 2023):
        start, _ = contents_pages(year)
        assert notes[year].notes[0].page_start == start, year


def test_the_notes_end_about_where_Part_II_begins(notes):
    """Part II starts on the page after the Notes, so COA's table of contents dates the end of the
    Notes. Pages derived from Word's saved layout drift by a few pages over long tables."""
    for year in (2020, 2021, 2022, 2023):
        _, part2_start = contents_pages(year)
        last = max(n.page_end for n in notes[year].notes)
        assert abs(last - (part2_start - 1)) <= 4, (year, last, part2_start)


def contents_pages(year: int) -> tuple[int, int]:
    """The first page of the Notes and of Part II according to the Table of Contents."""
    [path] = reports_folder(year).glob("**/04-*.docx")
    texts = [b.text for b in read_blocks(path) if isinstance(b, Paragraph)]
    return (
        int(page_after("Notes to Financial Statements", texts)),
        int(page_after("II Observations and Recommendations", texts)),
    )


def page_after(entry: str, texts: list[str]) -> str:
    return next(m.group(1) for t in texts if (m := re.fullmatch(rf"{entry} (\d+)", t)))


def test_pages_after_2021s_restart_follow_the_restarted_numbering(notes):
    """The last section of the 2021 Notes restarts its page numbers at 45, right after a landscape
    table that is itself on pages 45-46, so Word prints 45 and 46 twice."""
    ppe = note(notes[2021], 10)
    landscape = [
        p for p in ppe.passages if p.text.startswith("| Particulars | Carrying Value Dec.")
    ]
    after = next(p for p in ppe.passages if "increase in Land account is mainly" in p.text)

    assert (landscape[0].page_start, landscape[-1].page_end) == (45, 46)
    assert after.page_start == 45  # not 46: Word saved a page break at the top of the section too
    assert note(notes[2021], 11).page_start == 48
    assert note(notes[2021], 12).citation.endswith("Note 12, pp. 48-50")
    assert note(notes[2021], 33).page_start == 71


def test_a_page_break_saved_in_several_cells_of_a_row_is_one_page_break(notes):
    """The joint-venture table of Note 3 has page breaks in the cells of one row. Word saved the
    same break in each, and counting them all put 2021's Note 4 on page 37 instead of 34."""
    assert note(notes[2021], 3).page_end == 34
    assert note(notes[2021], 4).page_start == 34


# ---------------------------------------------------------------------------------------------
# Pages: the 2024 PDF


def test_2024_notes_are_cited_by_the_pages_the_pdf_prints(notes):
    assert note(notes[2024], 1).page_start == 12  # the file's first PDF page prints "12"
    assert note(notes[2024], 4).citation == (
        "CY 2024 AAR, Part I, Notes to Financial Statements, Note 4, pp. 31-32"
    )
    assert note(notes[2024], 31).page_start == 65
    assert note(notes[2024], 34).page_end == 76


def test_every_2024_note_starts_on_the_page_the_pdf_prints_beside_its_heading(notes):
    [pdf] = reports_folder(2024).glob("**/08-*Notes*.pdf")
    reader = PdfReader(pdf)
    printed = {}
    for page in reader.pages:
        text = page.extract_text()
        number = [ln.strip() for ln in text.splitlines() if re.fullmatch(r"\s*\d{1,3}\s*", ln)][-1]
        for found in re.finditer(r"^\s*Note\s+(\d+)\s*[–-]", text, re.MULTILINE):
            printed[int(found.group(1))] = int(number)

    assert sorted(printed) == list(range(1, 35))
    for n in notes[2024].notes:
        assert n.page_start == printed[n.number], n.number


def test_the_2024_notes_end_the_page_before_Part_II_begins(notes, part2):
    last = max(n.page_end for n in notes[2024].notes)

    assert last == 76
    assert min(c.page_start for c in part2[2024].commendations) == last + 1


# ---------------------------------------------------------------------------------------------
# Tables as markdown


def test_a_word_table_is_written_as_markdown_with_its_exact_amounts(notes):
    text = text_of(note(notes[2022], 4))

    assert "| Accounts | 2022 | 2021 |\n| --- | --- | --- |" in text
    assert "| Cash Local Treasury | 74,452,994.15 | 24,328,888.58 |" in text
    assert "| Total | 8,325,730,232.46 | 10,852,325,069.13 |" in text


def test_a_pdf_table_is_written_as_markdown_with_its_amounts_under_their_columns(notes):
    text = text_of(note(notes[2024], 5))

    assert "| Accounts | 2024 | 2023 |\n| --- | --- | --- |" in text
    assert "| Guaranty Deposits | 28,971,647.38 | 24,797,425.23 |" in text
    receivables = text_of(note(notes[2024], 6))
    assert "| Real Property Tax Receivable | 15,772,554,183.33 | 14,429,240,370.51 |" in receivables
    # A label the PDF spreads over several columns is still one cell.
    funds = "| Due from Other | 5,292,729,661.84 | 1,416,453,798.31 | 1,122,413,860.58 |"
    assert funds in receivables


def test_text_stays_text_between_tables(notes):
    text = text_of(note(notes[2022], 4))

    assert "\n\nThe Cash Local Treasury accounts for" in text
    assert text.index("| Total |") < text.index("The Cash Local Treasury accounts for")


def test_a_list_keeps_its_printed_labels(notes):
    funds = text_of(note(notes[2020], 2))

    assert "1. General Fund\n2. Special Education Fund\n3. Trust Fund" in funds


# ---------------------------------------------------------------------------------------------
# Passages


def test_a_passage_is_at_most_the_size_limit_unless_it_is_one_block(notes):
    for year in YEARS:
        for n in notes[year].notes:
            for passage in n.passages:
                if len(passage.text) > MAX_PASSAGE_CHARS:
                    assert "\n" not in passage.text.strip(), (year, n.number)


def test_a_table_cut_over_passages_repeats_its_header_row(notes):
    restatements = note(notes[2022], 31)
    header = (
        "| Accounts | Previously Reported | Adjustments | Restated |\n| --- | --- | --- | --- |"
    )

    tables = [p for p in restatements.passages if p.text.startswith("| ")]
    assert sum(p.text.startswith(header) for p in tables) > 5
    assert all(p.text.splitlines()[1].startswith("| ---") for p in tables)


@pytest.mark.parametrize("year", YEARS)
def test_the_passages_of_a_note_run_in_page_order(notes, year):
    for n in notes[year].notes:
        starts = [p.page_start for p in n.passages]
        if year == 2021 and n.number == 10:
            continue  # the pages after the restart repeat earlier numbers
        assert starts == sorted(starts), (year, n.number)
