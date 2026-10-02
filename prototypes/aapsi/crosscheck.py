"""Whole-document sanity check of Gemini's AAPSI extraction against the committed Part II records.

    uv run --group prototype python -m prototypes.aapsi.crosscheck [model]

No transcription needed: each AAPSI reference ("AAR 2024 Observation No. 3 Page 87") names an
Audit Observation. Reports which of the Part II observations are referenced, how each cited page
compares with the page derived from the Word file (ADR-0001), and the carried-over references to
earlier AARs.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from coa_explorer.config import REPO_ROOT

HERE = Path(__file__).parent
REFERENCE = re.compile(
    r"(?:AAR\s*(\d{4})|CY\s*(\d{4})\s*AAR).*?Observation\s*No\.?\s*(\d+).*?Pages?\s*(\d+)",
    re.I | re.S,
)  # "AAR 2023 Observation No. 1 Page 79" and "CY 2022 AAR, Observation No. 6, Page 81"
YEARS = (2020, 2021, 2022, 2023, 2024)


def read(model: str, year: int) -> list[dict]:
    rows = []
    for path in sorted((HERE / "results" / "gemini").glob(f"{year}_AAPSI_p*_{model}.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        rows += [{**row, "_page": data["page"]} for row in data["rows"]]
    return rows


def derived_pages() -> dict[tuple[int, int], int]:
    pages = {}
    for year in YEARS:
        path = REPO_ROOT / "data" / "extracted" / "part2" / f"{year}.json"
        for o in json.loads(path.read_text(encoding="utf-8"))["observations"]:
            pages[(year, o["number"])] = o["page_start"]
    return pages


def main() -> None:
    model = sys.argv[1] if len(sys.argv) > 1 else "gemini-3.8-flash"
    derived = derived_pages()
    for year in (2023, 2024):
        rows = read(model, year)
        own, carried, unparsed = {}, {}, []
        for row in rows:
            if not row["reference"].strip():
                continue
            m = REFERENCE.search(row["reference"])
            if not m:
                unparsed.append(row["reference"])
                continue
            ref_year, number, page = int(m.group(1) or m.group(2)), int(m.group(3)), int(m.group(4))
            (own if ref_year == year else carried)[(ref_year, number)] = page
        pages = len({r["_page"] for r in rows})
        expected = sorted(n for (y, n) in derived if y == year)
        print(f"\n{year} AAPSI ({model}): {len(rows)} rows over {pages} pages")
        unreferenced = [n for n in expected if (year, n) not in own]
        drift = {k[1]: page - derived[k] for k, page in own.items() if k in derived}
        unknown = [k for k in own if k not in derived]
        print(f"  references to this year's Part II: {len(own)} of {len(expected)} observations")
        print(f"  Part II observations never referenced: {unreferenced}")
        print(f"  cited page minus derived page: {drift}")
        print(f"  references not in Part II at all: {unknown or 'none'}")
        print(f"  carried-over references to earlier AARs: {len(carried)}")
        for (y, n), page in sorted(carried.items()):
            where = derived.get((y, n))
            note = (
                f"in collection, derived p.{where}"
                if where
                else "out of collection (or not in Part II)"
            )
            print(f"    CY {y} Obs {n} cited p.{page}: {note}")
        print(f"  references the parser could not read: {unparsed or 'none'}")


if __name__ == "__main__":
    main()
