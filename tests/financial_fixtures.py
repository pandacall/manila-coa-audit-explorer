"""Small financial-line records in the shape `coa-explorer extract` writes, for Seam 2 and 3."""

from __future__ import annotations

FUNDS = {
    "GF": "General Fund",
    "SEF": "Special Education Fund",
    "TF": "Trust Fund",
    "ALL": "All Funds",
}
CODES = {name: code for code, name in FUNDS.items()}


def line(
    year: int,
    statement: str,
    row: int,
    line_item: str,
    amount: str,
    *,
    fund: str = "All Funds",
    column: str = "Amount",
    source: str = "Part I",
    section: str = "",
    citation: str | None = None,
) -> dict:
    where = f"Part I, {statement}" if source == "Part I" else f"Part IV, {source}, {statement}"
    return {
        "key": f"{year}-FS-{source.replace(' ', '')}-{statement}-{row}-{CODES[fund]}",
        "source": source,
        "statement": statement,
        "sheet": statement,
        "row": row,
        "fund": fund,
        "section": section,
        "line_item": line_item,
        "column": column,
        "period": year,
        "amount": amount,
        "citation": citation or f"CY {year} AAR, {where}, {line_item}",
    }


def record(year: int, lines: list[dict]) -> dict:
    return {"aar_year": year, "source_files": [], "ignored_sheets": [], "lines": lines}


def cash(year: int, amount: str) -> dict:
    return line(year, "SFPo", 10, "Cash and Cash Equivalents", amount)


FIXTURE_FINANCIAL = {
    2021: record(
        2021,
        [
            cash(2021, "10864914036.53"),
            line(2021, "SCF", 12, "Total Cash Inflows", "21231995763.94", section="Operating"),
            line(2021, "SCF", 26, "Total Cash Inflows", "1257327371.54", section="Investing"),
        ],
    ),
    2022: record(
        2022,
        [
            cash(2022, "8325730232.46"),
            line(2022, "SFPo", 11, "Investments", "1429078656.95"),
            line(2022, "SCF", 15, "Total Cash Inflows", "21502892623.09", section="Operating"),
            line(2022, "SCF", 27, "Total Cash Inflows", "4921063.93", section="Investing"),
            line(
                2022,
                "SCBAA",
                11,
                "Tax Revenue - Property",
                "6060000000.00",
                column="Original budget",
            ),
            line(
                2022, "SCBAA", 11, "Tax Revenue - Property", "6060000000.00", column="Final budget"
            ),
            line(2022, "SCBAA", 11, "Tax Revenue - Property", "5313670150.25", column="Actual"),
            line(
                2022,
                "SCBAA",
                11,
                "Tax Revenue - Property",
                "746329849.75",
                column="Difference final budget and actual",
            ),
        ],
    ),
    2023: record(
        2023,
        [
            cash(2023, "9304414447.87"),
            *(
                line(2023, "SCBAA", 11, "Tax Revenue - Property", amount, column=column)
                for column, amount in (
                    ("Original budget", "6000000000.00"),
                    ("Final budget", "6000000000.00"),
                    ("Actual", "5250000000.50"),
                    ("Difference final budget and actual", "749999999.50"),
                )
            ),
            *(
                line(
                    2023,
                    "SFPo",
                    9,
                    "Cash and Cash Equivalents",
                    amount,
                    fund=fund,
                    source="Annex A",
                )
                for fund, amount in (
                    ("General Fund", "1000.50"),
                    ("Special Education Fund", "2000.25"),
                    ("Trust Fund", "3000.25"),
                    ("All Funds", "6001.00"),
                )
            ),
        ],
    ),
}
