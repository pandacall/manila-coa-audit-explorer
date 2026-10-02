"""Does Gemini's extraction leave out anything Document AI saw on the page?

    uv run --group prototype python -m prototypes.aapsi.completeness [model-suffix]

The spec checks Gemini's table rows against Document AI's OCR text. This measures how well that
check works: per page, the words Document AI read that Gemini's cells lack (counted as a multiset,
since the two list words in different orders), after setting aside the page title, column headings
and footer, which are not table content. Silent omissions show up as a deficit above that baseline.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

from prototypes.aapsi.compare import FIELDS

RESULTS = Path(__file__).parent / "results"
FURNITURE = """city of manila agency action plan and status of implementation audit observations and
recommendations for the calendar year as of reference audit observations audit recommendations
action plan person dept responsible target implementation date from to status of implementation
reason for partial delay non-implementation if applicable action taken action to be taken page of
2023 2024 2025 july august 31 as"""


def words(text: str) -> Counter:
    return Counter(re.findall(r"[a-z0-9]+", text.lower()))


def triples(tokens: list[str]) -> set[tuple[str, ...]]:
    return {tuple(tokens[i : i + 3]) for i in range(len(tokens) - 2)}


def omissions(model: str, run: int = 4) -> dict[tuple[int, int], list[str]]:
    """Stretches of Document AI text, at least `run` word-triples long, that appear in no cell.

    A triple is "missing" when no cell of Gemini's rows contains it. One misread word spoils up to
    three triples, so short runs are OCR noise; a dropped phrase leaves a longer run."""
    furniture = set(words(FURNITURE))
    found = {}
    for path in sorted((RESULTS / "gemini").glob(f"*_AAPSI_p*_{model}.json")):
        gemini = json.loads(path.read_text(encoding="utf-8"))
        docai_path = RESULTS / "docai" / f"{gemini['year']}_AAPSI_p{gemini['page']:02d}.json"
        text = json.loads(docai_path.read_text(encoding="utf-8"))["text"]
        seen = set()
        for row in gemini["rows"]:
            for f in FIELDS:
                seen |= triples(re.findall(r"[a-z0-9]+", row[f].lower()))
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        missing = [tuple(tokens[i : i + 3]) not in seen for i in range(len(tokens) - 2)]
        stretches, i = [], 0
        while i < len(missing):
            if missing[i]:
                j = i
                while j < len(missing) and missing[j]:
                    j += 1
                span = tokens[i : j + 2]
                if j - i >= run and not all(w in furniture for w in span):
                    stretches.append(" ".join(span))
                i = j
            else:
                i += 1
        found[(gemini["year"], gemini["page"])] = stretches
    return found


def main() -> None:
    baseline, other = (sys.argv[1:] + ["gemini-3.8-flash", "gemini-3.8-flash_think-low"])[:2]
    base, new = omissions(baseline), omissions(other)
    flagged, flagged_base = sum(map(len, new.values())), sum(map(len, base.values()))
    print(f"{other}: {flagged} stretches flagged; {baseline}: {flagged_base}")
    print(f"Flagged only for {other}:")
    for key, stretches in new.items():
        for stretch in stretches:
            if stretch not in base[key]:
                print(f"  {key[0]} p{key[1]}: {stretch[:110]}")


if __name__ == "__main__":
    main()
