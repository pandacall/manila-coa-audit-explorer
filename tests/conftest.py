from pathlib import Path

import pytest

from coa_explorer.part2 import extract_year

REPORTS = Path(__file__).resolve().parents[1] / "coa-audit-reports"
YEARS = (2020, 2021, 2022, 2023, 2024)


@pytest.fixture(scope="session")
def part2():
    """Part II extracted from the real, committed AARs, keyed by AAR year."""
    return {year: extract_year(REPORTS, year) for year in YEARS}
