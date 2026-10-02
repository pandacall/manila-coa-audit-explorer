"""The cell-by-cell comparison is the one piece of the prototype with logic worth pinning down.

Rows are dicts keyed by the AAPSI column fields; OCR tokens are (text, x, y) points in page
fractions, with (0, 0) the top-left corner of the page.
"""

import pytest

from prototypes.aapsi.compare import (
    FIELDS,
    assign_tokens_to_cells,
    cell_error_rate,
    score_page,
)


def row(**cells):
    return {field: cells.get(field, "") for field in FIELDS}


def test_identical_cells_have_no_error():
    text = "Submitted the Bank Reconciliation"
    assert cell_error_rate(text, text) == 0


def test_line_wraps_and_bullets_are_not_errors():
    truth = "Land-for-the-Landless Program, to OCAT on a timely basis."
    wrapped = "Land-for-the-\nLandless Program,\nto OCAT on a timely\nbasis."
    assert cell_error_rate(truth, wrapped) == 0
    assert cell_error_rate("•Maintain SLs", "Maintain SLs") == 0


def test_one_wrong_character_in_twenty_is_five_percent():
    assert cell_error_rate("P106.634millionvaria", "P106.634millionvarix") == pytest.approx(0.05)


def test_numbers_are_not_forgiven():
    assert cell_error_rate("P106.634 million", "P106.834 million") > 0


def test_empty_cells():
    assert cell_error_rate("", "") == 0
    assert cell_error_rate("", "invented") == 1
    assert cell_error_rate("Implemented", "") == 1


def test_error_is_capped_at_one():
    assert cell_error_rate("ab", "completely different and much longer") == 1


def test_page_score_is_per_column_and_counts_exact_cells():
    truth = [row(reference="AAR 2023 Observation No. 1 Page 79", status="Fully Implemented")]
    extracted = [row(reference="AAR 2023 Observation No. 1 Page 79", status="Fully Implementd")]

    score = score_page(truth, extracted)

    assert score.columns["reference"].mean_error == 0
    assert score.columns["reference"].exact == 1
    assert score.columns["status"].mean_error > 0
    assert score.columns["status"].exact == 0
    assert score.missing_rows == 0 and score.extra_rows == 0


def test_rows_are_matched_by_content_not_position():
    truth = [
        row(recommendations="1.7.1 Reconcile the variances per bank confirmations and books"),
        row(recommendations="1.7.2 Cause the timely preparation of monthly BRSs for each bank"),
    ]
    extracted = [  # a spurious row up front, as a model might invent for a page header
        row(recommendations="CITY OF MANILA"),
        row(recommendations="1.7.1 Reconcile the variances per bank confirmations and books"),
        row(recommendations="1.7.2 Cause the timely preparation of monthly BRSs for each bank"),
    ]

    score = score_page(truth, extracted)

    assert score.extra_rows == 1
    assert score.missing_rows == 0
    assert score.columns["recommendations"].mean_error == 0


def test_a_dropped_row_is_reported_missing_and_counts_as_total_error():
    truth = [
        row(recommendations="1.7.1 Reconcile the variances per bank confirmations", status="Fully"),
        row(recommendations="1.7.2 Cause the timely preparation of monthly BRSs", status="Fully"),
    ]
    extracted = [truth[0]]

    score = score_page(truth, extracted)

    assert score.missing_rows == 1
    assert score.columns["status"].mean_error == pytest.approx(0.5)


def test_text_in_the_wrong_column_is_an_error_in_both_columns():
    truth = [row(person_responsible="OCAT and CTO", action_plan="")]
    extracted = [row(person_responsible="", action_plan="OCAT and CTO")]

    score = score_page(truth, extracted)

    assert score.columns["person_responsible"].mean_error == 1
    assert score.columns["action_plan"].mean_error == 1


def test_tokens_are_assigned_to_the_cell_they_sit_in_and_keep_reading_order():
    columns_x = [0.0, 0.5, 1.0]  # two columns
    rows_y = [0.0, 0.5, 1.0]  # two rows
    tokens = [
        ("Reference", 0.1, 0.1),
        ("AAR", 0.1, 0.2),
        ("Status", 0.7, 0.1),
        ("Fully", 0.6, 0.7),
        ("Implemented", 0.8, 0.7),
    ]

    cells = assign_tokens_to_cells(tokens, columns_x, rows_y)

    assert cells[0][0] == "Reference AAR"
    assert cells[0][1] == "Status"
    assert cells[1][0] == ""
    assert cells[1][1] == "Fully Implemented"


def test_tokens_outside_the_table_are_ignored():
    cells = assign_tokens_to_cells([("CITY", 0.5, 0.01), ("OF", 0.9, 0.99)], [0.2, 1.0], [0.1, 0.9])

    assert cells == [[""]]
