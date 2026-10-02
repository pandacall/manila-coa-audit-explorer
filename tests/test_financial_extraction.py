"""Seam 1: the Financial Statements and Annexes, read from the real, committed spreadsheets.

Expected amounts are the figures printed in the spreadsheets (cached formula values), rounded to
the centavo.
"""

from decimal import Decimal

import pytest

from coa_explorer import financial
from coa_explorer.financial import FinancialRecord
from tests.conftest import REPORTS, YEARS


@pytest.fixture(scope="session")
def financials() -> dict[int, FinancialRecord]:
    return {year: financial.extract_year(REPORTS, year) for year in YEARS}


def amount(record, statement, line_item, *, fund="All Funds", column="Amount", source=None):
    matches = [
        line
        for line in record.lines
        if line.statement == statement
        and line.line_item == line_item
        and line.fund == fund
        and line.column == column
        and (source is None or line.source == source)
    ]
    assert len(matches) == 1, [(m.source, m.section, m.line_item) for m in matches]
    return matches[0].amount


def test_every_year_has_lines_from_all_five_statements_and_the_annexes(financials):
    for year in YEARS:
        lines = financials[year].lines
        assert {line.statement for line in lines} == {"SFPo", "SFPe", "SCNAE", "SCF", "SCBAA"}
        assert {line.source.split()[0] for line in lines} == {"Part", "Annex"}, year


def test_a_sample_of_part_I_lines_equals_the_spreadsheet_values(financials):
    assert amount(financials[2022], "SFPo", "Cash and Cash Equivalents") == Decimal("8325730232.46")
    assert amount(financials[2024], "SFPo", "Cash and Cash Equivalents") == Decimal("8084227242.24")
    assert amount(financials[2023], "SFPo", "Cash and Cash Equivalents") == Decimal("9304414447.87")


def test_the_prior_year_column_is_kept_apart_from_the_current_year(financials):
    prior = amount(
        financials[2022], "SFPo", "Cash and Cash Equivalents", column="Prior-year comparative"
    )
    assert prior == Decimal("10852325069.13")
    line = next(
        line
        for line in financials[2022].lines
        if line.line_item == "Cash and Cash Equivalents"
        and line.column == "Prior-year comparative"
        and line.source == "Part I"
    )
    assert line.period == 2021


def test_annex_lines_are_broken_down_by_fund(financials):
    cash = {
        fund: amount(
            financials[2024],
            "SFPo",
            "Total Cash and Cash Equivalents",
            fund=fund,
            source="Annex A",
        )
        for fund in ("General Fund", "Special Education Fund", "Trust Fund", "All Funds")
    }
    assert cash == {
        "General Fund": Decimal("629061926.97"),
        "Special Education Fund": Decimal("3491733890.69"),
        "Trust Fund": Decimal("3963431424.58"),
        "All Funds": Decimal("8084227242.24"),
    }


def test_2020_annex_amounts_in_whole_pesos_are_read_by_fund(financials):
    assert amount(
        financials[2020], "SFPo", "Cash and Cash Equivalents", fund="General Fund", source="Annex A"
    ) == Decimal("10253833046")


def test_budget_and_actual_amounts_are_separate_columns(financials):
    record = financials[2022]
    args = ("SCBAA", "Tax Revenue - Property")
    assert amount(record, *args, column="Original budget") == Decimal("6060000000")
    assert amount(record, *args, column="Final budget") == Decimal("6060000000")
    assert amount(record, *args, column="Actual") == Decimal("5313670150.25")
    assert amount(record, *args, column="Difference final budget and actual") == Decimal(
        "746329849.75"
    )


def test_2023_swapped_annex_lettering_does_not_confuse_the_statements(financials):
    record = financials[2023]
    sources = {
        line.statement: line.source for line in record.lines if line.source.startswith("Annex")
    }
    assert sources["SCF"] == "Annex C"
    assert sources["SCNAE"] == "Annex D"
    assert sources["SFPo"] == "Annex A"


def test_2024_unprefixed_sheet_names_are_read(financials):
    annex_statements = {
        line.statement for line in financials[2024].lines if line.source.startswith("Annex")
    }
    assert annex_statements == {"SFPo", "SFPe", "SCF", "SCNAE", "SCBAA"}


def test_2024_annex_puts_the_total_column_first_but_funds_stay_right(financials):
    general = amount(financials[2024], "SFPo", "Petty Cash", fund="General Fund", source="Annex A")
    assert general == Decimal("916058.08")


def test_hidden_working_sheets_are_ignored(financials):
    # 2022's workbook hides NFS, PPE, Restatement and other working sheets.
    sheets = {line.sheet for line in financials[2022].lines}
    assert sheets.isdisjoint({"NFS", "PPE", "Recon_BAA-FP", "Restatement", "ExecSum", "Part2"})
    assert "SFPo" in sheets


def test_oversized_used_ranges_add_nothing_beyond_the_tables(financials):
    # 2022's SCBAA-GF sheet claims 1,010 rows and 23 columns; the table ends far sooner.
    gf = [line for line in financials[2022].lines if line.sheet == "SCBAA-GF"]
    assert gf
    assert {line.fund for line in gf} == {"General Fund"}
    assert max(line.row for line in gf) < 150


def test_scbaa_annex_sheets_carry_their_fund(financials):
    funds = {
        line.sheet: line.fund for line in financials[2023].lines if line.sheet.startswith("SCBAA-")
    }
    assert funds == {"SCBAA-GF": "General Fund", "SCBAA-SEF": "Special Education Fund"}


def test_wrapped_line_labels_are_joined(financials):
    labels = {line.line_item for line in financials[2022].lines if line.statement == "SCF"}
    assert "Purchase/Construction of Property, Plant and Equipment" in labels


def test_every_line_has_a_citation_naming_the_statement_and_line_item(financials):
    for record in financials.values():
        for line in record.lines:
            assert line.citation.startswith(f"CY {record.aar_year} AAR, Part ")
            assert line.line_item in line.citation


def test_citation_keys_are_unique_within_a_year(financials):
    for record in financials.values():
        keys = [(line.key, line.column) for line in record.lines]
        assert len(keys) == len(set(keys)), record.aar_year


def test_amounts_are_exact_to_the_centavo(financials):
    for record in financials.values():
        for line in record.lines:
            assert line.amount == line.amount.quantize(Decimal("0.01"))


def test_in_every_annex_the_fund_columns_add_up_to_the_total_column(financials):
    for year, record in financials.items():
        rows: dict[tuple, dict[str, Decimal]] = {}
        for line in record.lines:
            if line.source.startswith("Annex") and line.statement != "SCBAA":
                rows.setdefault((line.sheet, line.row), {})[line.fund] = line.amount
        with_total = {k: funds for k, funds in rows.items() if "All Funds" in funds}
        assert with_total, year
        for key, funds in with_total.items():
            parts = sum(a for fund, a in funds.items() if fund != "All Funds")
            assert abs(parts - funds["All Funds"]) <= 2, (year, key, funds)


def test_the_statement_of_financial_position_balances_every_year(financials):
    for year, record in financials.items():
        assets = [
            line.amount
            for line in record.lines
            if line.source == "Part I"
            and line.statement == "SFPo"
            and line.column == "Amount"
            and line.line_item.lower() == "total assets"
        ]
        funded = [
            line.amount
            for line in record.lines
            if line.source == "Part I"
            and line.statement == "SFPo"
            and line.column == "Amount"
            and line.line_item.lower().startswith("total liabilit")
            and "net assets" in line.line_item.lower()
        ]
        assert len(assets) == len(funded) == 1, year
        assert assets == funded, year


def test_the_budget_difference_columns_are_final_budget_minus_actual(financials):
    # COA's own 2024 SEF sheet prints a different difference for its surplus row; it is the one
    # exception, and the lines keep what COA printed.
    exceptions = []
    for year, record in financials.items():
        rows: dict[tuple, dict[str, Decimal]] = {}
        for line in record.lines:
            if line.statement == "SCBAA":
                rows.setdefault((line.sheet, line.row), {})[line.column] = line.amount
        checked = 0
        for key, columns in rows.items():
            if {"Final budget", "Actual", "Difference final budget and actual"} <= columns.keys():
                checked += 1
                expected = columns["Final budget"] - columns["Actual"]
                if abs(expected - columns["Difference final budget and actual"]) > 1:
                    exceptions.append((year, *key))
        assert checked > 20, year
    assert exceptions == [(2024, "SCBAA-SEF", 33)]
