from pathlib import Path

import pytest

from coa_explorer import front_matter
from coa_explorer.part2 import extract_year
from coa_explorer.part3 import extract_year as extract_part3_year

REPORTS = Path(__file__).resolve().parents[1] / "coa-audit-reports"
YEARS = (2020, 2021, 2022, 2023, 2024)


@pytest.fixture(scope="session")
def part2():
    """Part II extracted from the real, committed AARs, keyed by AAR year."""
    return {year: extract_year(REPORTS, year) for year in YEARS}


@pytest.fixture(scope="session")
def part3():
    """Part III extracted from the real, committed AARs, keyed by AAR year."""
    return {year: extract_part3_year(REPORTS, year) for year in YEARS}


@pytest.fixture(scope="session")
def executive_summaries():
    """The Executive Summary extracted from the real, committed AARs, keyed by AAR year."""
    return {year: front_matter.extract_executive_summary(REPORTS, year) for year in YEARS}


@pytest.fixture(scope="session")
def auditors_reports():
    """The Auditor's Report extracted from the real, committed AARs, keyed by AAR year."""
    return {year: front_matter.extract_auditors_report(REPORTS, year) for year in YEARS}
