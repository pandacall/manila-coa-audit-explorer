"""Seam 1: COA's reference variants normalise to AAR year, observation number and pages."""

import pytest

from coa_explorer.references import Reference, parse_reference


@pytest.mark.parametrize(
    "text,expected",
    [
        # The variants COA uses across the 2020-2024 Part III tables.
        ("CY 2023 AAR, Observation No. 1, Page 71", Reference(2023, 1, 71, 71)),
        ("AAR 2020 / Observation No. 1 / Pages 69-71", Reference(2020, 1, 69, 71)),
        ("AAR 2024 Observation No. 6, Page 101", Reference(2024, 6, 101, 101)),
        ("AAR 2020 Observation No. 1 Pages 69-71", Reference(2020, 1, 69, 71)),
        ("CY 2022 AAR, Observation No. 3 Page 77", Reference(2022, 3, 77, 77)),
        # No year of its own: the table prints it in a heading row above ("AAR CY 2019").
        ("Observation No. 1, Pages 63-67", Reference(None, 1, 63, 67)),
        ("Observation No. 2. Pages 68-71", Reference(None, 2, 68, 71)),
        # Line breaks inside the printed reference.
        (
            "Observation No. 6, Pages 78-80".replace("Observation ", "Observation\n"),
            Reference(None, 6, 78, 80),
        ),
        (
            "Observation No. 24, Pages 108-112".replace("Pages ", "Pages\n"),
            Reference(None, 24, 108, 112),
        ),
        # En dash ranges, "pp." and "Pages" spelled in lower case.
        ("CY 2021 AAR, Observation No. 2, pages 79–81", Reference(2021, 2, 79, 81)),
        ("CY 2021 AAR, Observation No. 2, pp. 79-81", Reference(2021, 2, 79, 81)),
        # The year-only heading rows.
        ("AAR CY 2019", Reference(2019, None, None, None)),
        ("2021", Reference(2021, None, None, None)),
    ],
)
def test_reference_variants_parse(text, expected):
    assert parse_reference(text) == expected


def test_text_with_no_reference_in_it_parses_to_nothing():
    assert parse_reference("Reference") == Reference(None, None, None, None)
    assert parse_reference("") == Reference(None, None, None, None)


def test_a_page_number_is_never_mistaken_for_the_year():
    assert parse_reference("Observation No. 3, Page 2019") == Reference(None, 3, 2019, 2019)
