"""The `financial_lookup` tool: exact peso amounts from the Financial Statements and Annexes, and
the differences between years, computed here and never by the model.

A line item is found by its words (every word of the query must be in the printed label). Each match
is a figure: one printed row for one Fund in one AAR, with all its columns (the budget statement's
Original, Final, Actual and difference columns come together). When a line item is found in several
years, the change from each year to the next is worked out exactly, and the whole span too when
there are more than two years. Figures are only ever compared like for like: the same statement,
printed in the same place (Part I or an Annex), for the same Fund, under the same headings.
"""

from __future__ import annotations

import re
import sqlite3
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from coa_explorer.financial import PRIOR_YEAR

MAX_ROWS_PER_YEAR = 6  # printed rows kept per year (each may come back for several Funds)
STOPWORDS = frozenset({"of", "and", "the", "in", "for", "to", "on", "a", "an", "from"})
BILLION = Decimal(10) ** 9
MILLION = Decimal(10) ** 6
CENTAVOS = Decimal(100)
ONE_PLACE = Decimal("0.1")
TWO_PLACES = Decimal("0.01")


@dataclass(frozen=True)
class FinancialFigure:
    """One printed row of one statement, for one Fund, in one AAR."""

    key: str  # the id the model cites
    aar_year: int
    source: str  # "Part I" or "Annex A"
    statement: str
    fund: str
    section: str
    line_item: str
    citation: str
    amounts: dict[str, Decimal]  # by column
    display: dict[str, str]  # the same, written in pesos


@dataclass(frozen=True)
class FinancialChange:
    """How one amount moved from one year to a later one, worked out exactly."""

    statement: str
    fund: str
    section: str
    line_item: str
    column: str
    from_year: int
    to_year: int
    from_amount: Decimal
    to_amount: Decimal
    change: Decimal
    percent: Decimal | None  # of the earlier amount; None when that was zero
    display_change: str
    display_percent: str | None
    keys: tuple[str, str]  # the two figures it compares


@dataclass(frozen=True)
class FinancialLookup:
    figures: list[FinancialFigure] = field(default_factory=list)
    changes: list[FinancialChange] = field(default_factory=list)


def lookup(
    db: sqlite3.Connection,
    line_item: str,
    years: list[int],
    statement: str | None = None,
    fund: str | None = None,
) -> FinancialLookup:
    wanted = words(line_item)
    if not wanted or not years:
        return FinancialLookup()
    where = [f"aar_year IN ({','.join('?' * len(years))})", "column_name != ?"]
    params: list = [*years, PRIOR_YEAR]
    if statement:
        where.append("statement = ? COLLATE NOCASE")
        params.append(statement)
    if fund:
        where.append("fund = ?")
        params.append(fund)
    rows = db.execute(
        f"SELECT * FROM financial_lines WHERE {' AND '.join(where)} ORDER BY aar_year, id", params
    ).fetchall()
    figures = figures_of(rows, wanted)
    return FinancialLookup(figures=[f for f, _ in figures], changes=changes_of(figures))


def words(text: str) -> list[str]:
    tokens = [t for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]
    return [t[:-1] if len(t) > 3 and t.endswith("s") else t for t in tokens]


def figures_of(
    rows: list[sqlite3.Row], wanted: list[str]
) -> list[tuple[FinancialFigure, sqlite3.Row]]:
    """The figures whose label holds every wanted word, best matches first within each year."""
    matched = [row for row in rows if set(wanted) <= set(words(row["line_item"]))]
    if not matched:  # fall back on the headings above the line too
        matched = [
            row for row in rows if set(wanted) <= set(words(f"{row['section']} {row['line_item']}"))
        ]
    by_year: dict[int, dict[tuple, list[sqlite3.Row]]] = defaultdict(lambda: defaultdict(list))
    for row in matched:
        by_year[row["aar_year"]][(row["sheet"], row["sheet_row"])].append(row)
    result = []
    for year in sorted(by_year):
        printed = sorted(by_year[year].values(), key=lambda group: rank(group[0], wanted))
        for group in printed[:MAX_ROWS_PER_YEAR]:
            by_fund: dict[str, list[sqlite3.Row]] = defaultdict(list)
            for row in group:
                by_fund[row["fund"]].append(row)
            for fund_rows in by_fund.values():
                result.append((figure_of(fund_rows), fund_rows[0]))
    return result


def rank(row: sqlite3.Row, wanted: list[str]) -> tuple:
    label = words(row["line_item"])
    exactness = 0 if label == wanted else 1 if label[: len(wanted)] == wanted else 2
    return (exactness, row["source"] != "Part I", len(label), row["sheet_row"])


def figure_of(rows: list[sqlite3.Row]) -> FinancialFigure:
    first = rows[0]
    amounts = {row["column_name"]: Decimal(row["centavos"]) / CENTAVOS for row in rows}
    return FinancialFigure(
        key=first["key"],
        aar_year=first["aar_year"],
        source=first["source"],
        statement=first["statement"],
        fund=first["fund"],
        section=first["section"],
        line_item=first["line_item"],
        citation=first["citation"],
        amounts=amounts,
        display={column: peso(amount) for column, amount in amounts.items()},
    )


def changes_of(figures: list[tuple[FinancialFigure, sqlite3.Row]]) -> list[FinancialChange]:
    """Compare each line item with itself in the other years, like for like.

    A label printed more than once in a statement (every "Total Cash Inflows") is only matched
    across years under the same headings.
    """
    found = [f for f, _ in figures]
    rows_per_label = Counter((f.aar_year, place(f), norm(f.line_item)) for f in found)
    repeated = {(where, label) for (_, where, label), n in rows_per_label.items() if n > 1}
    identities: dict[tuple, list[FinancialFigure]] = defaultdict(list)
    for figure in found:
        where, label = place(figure), norm(figure.line_item)
        heading = norm(figure.section) if (where, label) in repeated else None
        identities[(where, label, heading)].append(figure)
    changes = []
    for same in identities.values():
        years = [f.aar_year for f in same]
        if len(same) < 2 or len(set(years)) != len(years):
            continue  # in one year only, or printed twice in a year: nothing safe to compare
        ordered = sorted(same, key=lambda f: f.aar_year)
        pairs = list(zip(ordered, ordered[1:], strict=False))
        if len(ordered) > 2:
            pairs.append((ordered[0], ordered[-1]))
        for earlier, later in pairs:
            for column in earlier.amounts.keys() & later.amounts.keys():
                if not column.startswith("Difference"):  # a gap, not an amount to trend
                    changes.append(change_between(earlier, later, column))
    changes.sort(
        key=lambda c: (
            c.statement,
            c.section,
            c.line_item,
            c.column,
            c.to_year - c.from_year,
            c.from_year,
        )
    )
    return changes


def place(figure: FinancialFigure) -> tuple[str, str, str]:
    """Where a figure is printed and for whom, so that like is only compared with like."""
    return ("Part I" if figure.source == "Part I" else "Annex", figure.statement, figure.fund)


def norm(text: str) -> str:
    return " ".join(words(text))


def change_between(
    earlier: FinancialFigure, later: FinancialFigure, column: str
) -> FinancialChange:
    before, after = earlier.amounts[column], later.amounts[column]
    change = after - before
    percent = None
    if before != 0:
        percent = (change / abs(before) * 100).quantize(ONE_PLACE, rounding=ROUND_HALF_UP)
    return FinancialChange(
        statement=later.statement,
        fund=later.fund,
        section=later.section,
        line_item=later.line_item,
        column=column,
        from_year=earlier.aar_year,
        to_year=later.aar_year,
        from_amount=before,
        to_amount=after,
        change=change,
        percent=percent,
        display_change=peso(change),
        display_percent=None if percent is None else f"{percent:+.1f}%",
        keys=(earlier.key, later.key),
    )


def peso(amount: Decimal) -> str:
    """ "₱8,325,730,232.46 (about ₱8.33 billion)": the exact figure, then a rounded one in words."""
    sign = "-" if amount < 0 else ""
    size = abs(amount)
    exact = f"{sign}₱{size:,.2f}"
    for unit, name in ((BILLION, "billion"), (MILLION, "million")):
        if size >= unit:
            rounded = (size / unit).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
            return f"{exact} (about {sign}₱{rounded} {name})"
    return exact
