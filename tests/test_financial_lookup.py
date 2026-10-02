"""Seam 2: `financial_lookup` over an index built from small fixture records.

Expected amounts and differences are worked out by hand from the fixture figures, not computed
with the code under test.
"""

from decimal import Decimal

import pytest

from coa_explorer.index import build_index
from coa_explorer.search import Index
from tests.fake_embedder import FakeEmbedder
from tests.fixtures import write_fixture_records


@pytest.fixture()
def index(tmp_path):
    records = write_fixture_records(tmp_path / "records")
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())
    with Index.open(tmp_path / "coa.sqlite", FakeEmbedder()) as opened:
        yield opened


def test_returns_the_exact_amount_with_a_citation_to_the_statement_and_line_item(index):
    result = index.financial_lookup("Cash and Cash Equivalents", years=[2022])

    [figure] = result.figures
    assert figure.aar_year == 2022
    assert figure.fund == "All Funds"
    assert figure.amounts == {"Amount": Decimal("8325730232.46")}
    assert (
        figure.citation
        == "CY 2022 AAR, Part I, Statement of Financial Position, Cash and Cash Equivalents"
    )
    assert figure.key == "2022-FS-PartI-SFPo-10-ALL"


def test_shows_amounts_in_pesos_with_the_unit_spelled_out(index):
    [figure] = index.financial_lookup("Cash and Cash Equivalents", years=[2022]).figures

    assert figure.display == {"Amount": "₱8,325,730,232.46 (about ₱8.33 billion)"}


def test_small_amounts_are_not_rounded_into_words(index):
    figures = index.financial_lookup("Cash and Cash Equivalents", years=[2023], fund="General Fund")

    assert figures.figures[0].display == {"Amount": "₱1,000.50"}


def test_matches_a_line_item_by_its_words_not_only_its_exact_label(index):
    result = index.financial_lookup("cash equivalents", years=[2022])

    assert [f.line_item for f in result.figures] == ["Cash and Cash Equivalents"]


def test_a_year_that_was_not_asked_for_is_not_returned(index):
    result = index.financial_lookup("Cash and Cash Equivalents", years=[2021])

    assert [f.aar_year for f in result.figures] == [2021]


def test_the_difference_between_two_years_is_computed_by_the_tool(index):
    result = index.financial_lookup("Cash and Cash Equivalents", years=[2021, 2022])

    [change] = result.changes
    assert (change.from_year, change.to_year) == (2021, 2022)
    assert change.column == "Amount"
    assert change.change == Decimal("-2539183804.07")
    assert change.percent == Decimal("-23.4")
    assert change.display_change == "-₱2,539,183,804.07 (about -₱2.54 billion)"
    assert change.display_percent == "-23.4%"
    assert [f.key for f in result.figures] == [
        "2021-FS-PartI-SFPo-10-ALL",
        "2022-FS-PartI-SFPo-10-ALL",
    ]
    assert change.keys == ("2021-FS-PartI-SFPo-10-ALL", "2022-FS-PartI-SFPo-10-ALL")


def test_with_three_years_each_step_is_computed_and_so_is_the_whole_span(index):
    result = index.financial_lookup("Cash and Cash Equivalents", years=[2023, 2021, 2022])

    steps = [(c.from_year, c.to_year, c.change) for c in result.changes]
    assert steps == [
        (2021, 2022, Decimal("-2539183804.07")),
        (2022, 2023, Decimal("978684215.41")),
        (2021, 2023, Decimal("-1560499588.66")),
    ]


def test_a_figure_printed_in_only_one_year_has_no_change(index):
    result = index.financial_lookup("Investments", years=[2021, 2022])

    assert [f.aar_year for f in result.figures] == [2022]
    assert result.changes == []


def test_annex_lines_come_back_broken_down_by_fund(index):
    result = index.financial_lookup("Cash and Cash Equivalents", years=[2023], fund=None)

    annex = {
        f.fund: f.amounts["Amount"] for f in result.figures if f.key.startswith("2023-FS-Annex")
    }
    assert annex == {
        "General Fund": Decimal("1000.50"),
        "Special Education Fund": Decimal("2000.25"),
        "Trust Fund": Decimal("3000.25"),
        "All Funds": Decimal("6001.00"),
    }
    assert any(f.key == "2023-FS-PartI-SFPo-10-ALL" for f in result.figures)


def test_asking_for_one_fund_returns_only_that_fund(index):
    result = index.financial_lookup(
        "Cash and Cash Equivalents", years=[2023], fund="Special Education Fund"
    )

    [figure] = result.figures
    assert figure.amounts == {"Amount": Decimal("2000.25")}
    assert (
        figure.citation
        == "CY 2023 AAR, Part IV, Annex A, Statement of Financial Position, Cash and Cash Equivalents"
    )


def test_the_statement_filter_keeps_only_that_statement(index):
    assert index.financial_lookup("Cash", years=[2022], statement="SFPe").figures == []
    result = index.financial_lookup("Cash", years=[2022], statement="SFPo")
    assert {f.statement for f in result.figures} == {"SFPo"}


def test_the_same_line_item_in_two_sections_is_told_apart_and_compared_like_for_like(index):
    result = index.financial_lookup("Total Cash Inflows", years=[2021, 2022], statement="SCF")

    changes = {c.section: c.change for c in result.changes}
    assert changes == {
        "Operating": Decimal("270896859.15"),
        "Investing": Decimal("-1252406307.61"),
    }


def test_budget_and_actual_come_back_together_as_separate_columns(index):
    result = index.financial_lookup("Tax Revenue - Property", years=[2022], statement="SCBAA")

    [figure] = result.figures
    assert figure.amounts == {
        "Original budget": Decimal("6060000000.00"),
        "Final budget": Decimal("6060000000.00"),
        "Actual": Decimal("5313670150.25"),
        "Difference final budget and actual": Decimal("746329849.75"),
    }


def test_a_line_item_the_reports_do_not_have_returns_nothing(index):
    result = index.financial_lookup("Quezon City bridge loan", years=[2022])

    assert result.figures == []
    assert result.changes == []


def test_years_outside_the_collection_return_nothing(index):
    assert index.financial_lookup("Cash and Cash Equivalents", years=[2019]).figures == []


def test_budget_and_actual_are_compared_across_years_but_not_the_difference_columns(index):
    result = index.financial_lookup("Tax Revenue - Property", years=[2022, 2023])

    steps = {c.column: (c.change, c.display_percent) for c in result.changes}
    assert steps == {
        "Original budget": (Decimal("-60000000.00"), "-1.0%"),
        "Final budget": (Decimal("-60000000.00"), "-1.0%"),
        "Actual": (Decimal("-63670149.75"), "-1.2%"),
    }


def test_a_total_is_ranked_with_the_line_it_totals_not_after_the_sub_lines(index):
    result = index.financial_lookup("cash", years=[2024], fund="General Fund")

    assert [f.line_item for f in result.figures] == [
        "Total Cash and Cash Equivalents",
        "Petty Cash",
    ]


def test_no_percentage_is_given_when_the_earlier_amount_is_not_positive(index):
    [change] = index.financial_change("2023-FS-AnnexB-SFPe-30-GF", "2024-FS-AnnexB-SFPe-30-GF")

    assert change.change == Decimal("150.00")
    assert change.percent is None
    assert change.display_percent is None


def test_two_lines_labelled_differently_in_two_years_can_still_be_compared_by_the_tool(index):
    # General Fund cash is "Cash and Cash Equivalents" in 2023 and "Total Cash and Cash
    # Equivalents" in 2024, so a lookup alone cannot pair them.
    assert index.financial_lookup("cash", years=[2023, 2024], fund="General Fund").changes == []

    [change] = index.financial_change("2023-FS-AnnexA-SFPo-9-GF", "2024-FS-AnnexA-SFPo-18-GF")

    assert (change.from_year, change.to_year) == (2023, 2024)
    assert change.change == Decimal("500.25")
    assert change.display_percent == "+50.0%"
    assert change.keys == ("2023-FS-AnnexA-SFPo-9-GF", "2024-FS-AnnexA-SFPo-18-GF")
    assert change.line_item == "Total Cash and Cash Equivalents"


def test_a_change_is_worked_out_forwards_whichever_order_the_lines_are_given(index):
    [change] = index.financial_change("2024-FS-AnnexA-SFPo-18-GF", "2023-FS-AnnexA-SFPo-9-GF")

    assert (change.from_year, change.to_year, change.change) == (2023, 2024, Decimal("500.25"))


def test_lines_for_different_funds_or_statements_or_one_year_are_not_compared(index):
    with pytest.raises(ValueError, match="Fund"):
        index.financial_change("2023-FS-AnnexA-SFPo-9-GF", "2023-FS-AnnexA-SFPo-9-SEF")
    with pytest.raises(ValueError, match="statement"):
        index.financial_change("2023-FS-AnnexA-SFPo-9-GF", "2024-FS-AnnexB-SFPe-30-GF")
    with pytest.raises(ValueError, match="different years"):
        index.financial_change("2023-FS-AnnexA-SFPo-9-GF", "2023-FS-AnnexA-SFPo-9-GF")
    with pytest.raises(ValueError, match="no such"):
        index.financial_change("2023-FS-AnnexA-SFPo-9-GF", "1999-nothing")
