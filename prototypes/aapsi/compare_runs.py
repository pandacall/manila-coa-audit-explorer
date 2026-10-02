"""How much do two whole-document Gemini runs differ, and what did each cost?

    uv run --group prototype python -m prototypes.aapsi.compare_runs [baseline [other]]

Rows are paired with the comparison's own alignment; cells are compared ignoring whitespace and
bullet glyphs. Reproduces the run-to-run figures in FINDINGS.md.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from prototypes.aapsi.compare import FIELDS, normalise, score_page
from prototypes.aapsi.report import gemini_cost

GEMINI = Path(__file__).parent / "results" / "gemini"


def load(model: str) -> dict[tuple[int, int], dict]:
    runs = [
        json.loads(p.read_text(encoding="utf-8")) for p in GEMINI.glob(f"*_AAPSI_p*_{model}.json")
    ]
    return {(r["year"], r["page"]): r for r in runs}


def main() -> None:
    defaults = ["gemini-3.8-flash", "gemini-3.8-flash_think-low"]
    baseline, other = [*sys.argv[1:3], *defaults[len(sys.argv[1:3]) :]]
    a, b = load(baseline), load(other)
    cells = differing = 0
    row_count_differs = []
    for key in sorted(a.keys() & b.keys()):
        if len(a[key]["rows"]) != len(b[key]["rows"]):
            row_count_differs.append(key)
        for t, e in score_page(a[key]["rows"], b[key]["rows"]).pairs:
            if t is None or e is None:
                continue
            for f in FIELDS:
                cells += 1
                differing += normalise(a[key]["rows"][t][f]) != normalise(b[key]["rows"][e][f])
    print(f"{len(a.keys() & b.keys())} pages; {cells} cells paired, {differing} differ")
    print(f"pages with different row counts: {row_count_differs}")
    for model, runs in ((baseline, a), (other, b)):
        rows = {y: sum(len(r["rows"]) for k, r in runs.items() if k[0] == y) for y in (2023, 2024)}
        cost = sum(gemini_cost(r) for r in runs.values())
        secs = sum(r["seconds"] for r in runs.values()) / len(runs)
        print(f"{model}: ${cost:.3f} for {len(runs)} pages, {secs:.1f} s/page, rows {rows}")


if __name__ == "__main__":
    main()
