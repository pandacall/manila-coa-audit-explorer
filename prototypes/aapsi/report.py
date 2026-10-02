"""Compare Gemini and Document AI against the transcribed truth, cell by cell.

    uv run --group prototype python -m prototypes.aapsi.report            # results/comparison.md
    uv run --group prototype python -m prototypes.aapsi.report --overlay  # grid on the scans

Gemini returns table rows directly. Document AI Enterprise OCR returns words with positions, so its
words are bucketed into the truth file's grid (page-fraction column and row boundaries); that gives
it the benefit of a perfect table layout it would not have in practice.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pymupdf

from prototypes.aapsi.compare import (
    FIELDS,
    assign_tokens_to_cells,
    edit_distance,
    normalise,
    score_page,
)
from prototypes.aapsi.extract_gemini import pdf_path

HERE = Path(__file__).parent
TRUTH = HERE / "truth"
RESULTS = HERE / "results"

# USD per million tokens, from third-party price trackers on 2026-10-02; not confirmed on Google's
# own pricing page, which would not load (see FINDINGS.md).
# Thinking tokens are billed as output tokens.
PRICES = {
    "gemini-3.8-flash": {"input": 0.75, "output": 3.75},
    "gemini-3.1-pro-preview": {"input": 2.0, "output": 12.0},
}
DOCAI_OCR_PER_PAGE = 0.0015  # Enterprise OCR, per page, first 5M pages a month


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def gemini_cost(result: dict) -> float:
    price = PRICES[result["model"]]
    usage = result["usage"]
    output = usage["output_tokens"] + usage["thought_tokens"]
    return (usage["prompt_tokens"] * price["input"] + output * price["output"]) / 1_000_000


def docai_rows(truth: dict, docai: dict) -> list[dict]:
    tokens = [(t["text"], t["x"], t["y"]) for t in docai["tokens"]]
    grid = assign_tokens_to_cells(tokens, truth["columns_x"], truth["rows_y"])
    return [dict(zip(FIELDS, cells, strict=True)) for cells in grid]


def column_table(score) -> list[str]:
    lines = ["| Column | Cells | Exact | Mean CER |", "| --- | ---: | ---: | ---: |"]
    for f in FIELDS:
        c = score.columns[f]
        lines.append(f"| {f} | {len(c.errors)} | {c.exact} | {c.mean_error:.3f} |")
    lines.append(
        f"| **all** | {score.cells} | {score.exact_cells} | {score.mean_error:.3f} |"
        f" (missing rows {score.missing_rows}, extra rows {score.extra_rows})"
    )
    return lines


def diff_window(want: str, got: str, margin: int = 30) -> tuple[str, str]:
    """The stretch of each text around its first difference (whitespace ignored)."""
    from difflib import SequenceMatcher

    want, got = "".join(want.split()), "".join(got.split())
    for op, i1, i2, j1, j2 in SequenceMatcher(None, want, got, autojunk=False).get_opcodes():
        if op != "equal":
            lo = max(0, i1 - margin)
            return want[lo : i2 + margin], got[max(0, j1 - (i1 - lo)) : j2 + margin]
    return want[:margin], got[:margin]


def worst_cells(truth_rows, rows, score, limit=8) -> list[str]:
    from prototypes.aapsi.compare import cell_error_rate

    found = []
    for t, e in score.pairs:
        if t is None or e is None:
            continue
        for f in FIELDS:
            err = cell_error_rate(truth_rows[t][f], rows[e][f])
            if err > 0:
                found.append((err, t, f, truth_rows[t][f], rows[e][f]))
    found.sort(reverse=True)
    out = []
    for err, t, f, want, got in found[:limit]:
        a, b = diff_window(want, got)
        out.append(f"- row {t + 1} `{f}` CER {err:.2f}\n  - scan: …{a}\n  - read: …{b}")
    return out


def character_errors(truth_rows, rows, score) -> tuple[int, int]:
    """(edit distance, characters in the scan) over the matched rows' cells."""
    wrong = total = 0
    for t, e in score.pairs:
        if t is None:
            continue
        for f in FIELDS:
            want = normalise(truth_rows[t][f])
            got = normalise(rows[e][f]) if e is not None else ""
            wrong += edit_distance(want, got) if want else len(got)
            total += len(want)
    return wrong, total


def lookalikes(rows) -> int:
    """Characters outside Latin-1 (Cyrillic homoglyphs and the like) in what was read."""
    return sum(
        1 for row in rows for f in FIELDS for ch in row[f] if ord(ch) > 0xFF and ch not in "’‘“”–—•"
    )


def report() -> str:
    out = ["# AAPSI extraction: cell-by-cell comparison", ""]
    summary = [
        "| Page | Engine | Cells exact | Char errors / chars | Rows read/scan | Lookalike chars"
        " | Tokens in/out/think | Cost |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for truth_file in sorted(TRUTH.glob("*.json")):
        truth = load(truth_file)
        stem = truth_file.stem
        out += [
            f"## {truth['year']} AAPSI, PDF page {truth['page']}",
            "",
            f"_{truth['method']}_",
            "",
        ]
        for gem_file in sorted((RESULTS / "gemini").glob(f"{stem}_*.json")):
            gem = load(gem_file)
            score = score_page(truth["rows"], gem["rows"])
            usage = gem["usage"]
            wrong, total = character_errors(truth["rows"], gem["rows"], score)
            summary.append(
                f"| {stem} | {gem_file.stem.removeprefix(stem + '_')}"
                f" | {score.exact_cells}/{score.cells} | {wrong}/{total}"
                f" | {len(gem['rows'])}/{len(truth['rows'])} | {lookalikes(gem['rows'])}"
                f" | {usage['prompt_tokens']}/{usage['output_tokens']}/{usage['thought_tokens']}"
                f" | ${gemini_cost(gem):.4f} |"
            )
            out += [
                f"### Gemini `{gem_file.stem.removeprefix(stem + '_')}`",
                f"{len(gem['rows'])} rows read, {len(truth['rows'])} in the scan;"
                f" {usage['prompt_tokens']} in / {usage['output_tokens']} out /"
                f" {usage['thought_tokens']} thinking tokens, {gem['seconds']} s,"
                f" ${gemini_cost(gem):.4f}.",
                "",
                *column_table(score),
                "",
                *worst_cells(truth["rows"], gem["rows"], score),
                "",
            ]
        docai_file = RESULTS / "docai" / f"{stem}.json"
        if docai_file.exists():
            docai = load(docai_file)
            rows = docai_rows(truth, docai)
            score = score_page(truth["rows"], rows)
            wrong, total = character_errors(truth["rows"], rows, score)
            summary.append(
                f"| {stem} | document-ai-ocr | {score.exact_cells}/{score.cells} | {wrong}/{total}"
                f" | n/a | {lookalikes(rows)} | n/a | ${DOCAI_OCR_PER_PAGE} |"
            )
            out += [
                "### Document AI Enterprise OCR",
                f"{len(docai['tokens'])} words, image quality {docai['image_quality']:.2f},"
                f" ${DOCAI_OCR_PER_PAGE}/page, words bucketed into the truth grid.",
                "",
                *column_table(score),
                "",
                *worst_cells(truth["rows"], rows, score),
                "",
            ]
    return "\n".join([out[0], "", *summary, "", *out[1:]])


def draw_line(page, start: tuple[float, float], end: tuple[float, float], color) -> None:
    """Draw between page-fraction points; drawing ignores the page's rotation flag, so undo it."""
    w, h = page.rect.width, page.rect.height
    a, b = (pymupdf.Point(x * w, y * h) * page.derotation_matrix for x, y in (start, end))
    page.draw_line(a, b, color=color, width=0.6)


def overlay() -> None:
    for truth_file in sorted(TRUTH.glob("*.json")):
        truth = load(truth_file)
        doc = pymupdf.open(pdf_path(truth["year"], truth["doc"]))
        page = doc[truth["page"] - 1]
        top, bottom = truth["rows_y"][0], truth["rows_y"][-1]
        left, right = truth["columns_x"][0], truth["columns_x"][-1]
        for x in truth["columns_x"]:
            draw_line(page, (x, top), (x, bottom), (1, 0, 0))
        for y in truth["rows_y"]:
            draw_line(page, (left, y), (right, y), (0, 0, 1))
        out = RESULTS / f"overlay_{truth_file.stem}.png"
        page.get_pixmap(dpi=130).save(out)
        print(out)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--overlay", action="store_true")
    args = parser.parse_args()
    if args.overlay:
        overlay()
        return
    text = report()
    (RESULTS / "comparison.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
