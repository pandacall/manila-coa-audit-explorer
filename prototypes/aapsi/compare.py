"""Cell-by-cell comparison of an extraction against a transcription of the scan.

Prototype code (ticket #7): throwaway, but the comparison is what the decision rests on, so it is
tested. A row is a dict keyed by FIELDS; one row per horizontal band of the Audit Observations /
Recommendations columns, with merged cells on the right attributed to the first band they cover.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# AAPSI columns, left to right. "Target Implementation Date" has From and To sub-columns.
FIELDS = (
    "reference",
    "observations",
    "recommendations",
    "action_plan",
    "person_responsible",
    "target_from",
    "target_to",
    "status",
    "reason_for_delay",
    "action_taken",
)

BULLETS = "•·●▪◦"
MATCH_THRESHOLD = 0.4  # a row pairs with a transcribed row only if at least this similar


def normalise(text: str) -> str:
    """Whitespace and bullet glyphs carry no content; everything else, digits included, does."""
    return "".join(ch for ch in text if not ch.isspace() and ch not in BULLETS)


def cell_error_rate(truth: str, extracted: str) -> float:
    """Character error rate of one cell, 0 (exact) to 1 (nothing right or invented text)."""
    truth, extracted = normalise(truth), normalise(extracted)
    if not truth:
        return 0.0 if not extracted else 1.0
    return min(1.0, edit_distance(truth, extracted) / len(truth))


def edit_distance(a: str, b: str) -> int:
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


@dataclass
class ColumnScore:
    errors: list[float] = field(default_factory=list)

    @property
    def mean_error(self) -> float:
        return sum(self.errors) / len(self.errors) if self.errors else 0.0

    @property
    def exact(self) -> int:
        return sum(1 for e in self.errors if e == 0)


@dataclass
class PageScore:
    columns: dict[str, ColumnScore]
    missing_rows: int
    extra_rows: int
    pairs: list[tuple[int | None, int | None]]  # (truth index, extracted index)

    @property
    def cells(self) -> int:
        return sum(len(c.errors) for c in self.columns.values())

    @property
    def exact_cells(self) -> int:
        return sum(c.exact for c in self.columns.values())

    @property
    def mean_error(self) -> float:
        errors = [e for c in self.columns.values() for e in c.errors]
        return sum(errors) / len(errors) if errors else 0.0


def row_text(row: dict) -> str:
    return " ".join(row.get(f, "") for f in FIELDS)


def row_similarity(truth: dict, extracted: dict) -> float:
    return 1 - cell_error_rate(row_text(truth), row_text(extracted))


def align_rows(truth: list[dict], extracted: list[dict]) -> list[tuple[int | None, int | None]]:
    """Order-preserving pairing that maximises total similarity; unpaired rows pair with None."""
    n, m = len(truth), len(extracted)
    sim = [[row_similarity(t, e) for e in extracted] for t in truth]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s = sim[i - 1][j - 1]
            paired = best[i - 1][j - 1] + s if s >= MATCH_THRESHOLD else -1
            best[i][j] = max(best[i - 1][j], best[i][j - 1], paired)
    pairs, i, j = [], n, m
    while i > 0 or j > 0:
        if (
            i > 0
            and j > 0
            and sim[i - 1][j - 1] >= MATCH_THRESHOLD
            and (best[i][j] == best[i - 1][j - 1] + sim[i - 1][j - 1])
        ):
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif i > 0 and best[i][j] == best[i - 1][j]:
            pairs.append((i - 1, None))
            i -= 1
        else:
            pairs.append((None, j - 1))
            j -= 1
    return pairs[::-1]


def score_page(truth: list[dict], extracted: list[dict]) -> PageScore:
    """Per-column error over the transcribed rows; a row the extraction dropped scores 1 per
    non-empty cell (and 0 for cells that are empty in the scan)."""
    pairs = align_rows(truth, extracted)
    columns = {f: ColumnScore() for f in FIELDS}
    for t, e in pairs:
        if t is None:
            continue
        for f in FIELDS:
            truth_cell = truth[t].get(f, "")
            extracted_cell = extracted[e].get(f, "") if e is not None else ""
            columns[f].errors.append(cell_error_rate(truth_cell, extracted_cell))
    return PageScore(
        columns=columns,
        missing_rows=sum(1 for t, e in pairs if e is None),
        extra_rows=sum(1 for t, e in pairs if t is None),
        pairs=pairs,
    )


def assign_tokens_to_cells(
    tokens: list[tuple[str, float, float]], columns_x: list[float], rows_y: list[float]
) -> list[list[str]]:
    """Bucket OCR tokens into the table grid by their centre point, keeping the OCR's reading
    order within a cell. Boundaries are page fractions; N boundaries make N-1 columns or rows.
    Tokens outside the grid (page titles, footers) are dropped."""
    cells: list[list[list[str]]] = [[[] for _ in columns_x[1:]] for _ in rows_y[1:]]
    for text, x, y in tokens:
        col = _bucket(x, columns_x)
        row = _bucket(y, rows_y)
        if col is not None and row is not None:
            cells[row][col].append(text)
    return [[" ".join(words) for words in row] for row in cells]


def _bucket(value: float, bounds: list[float]) -> int | None:
    for i in range(len(bounds) - 1):
        if bounds[i] <= value < bounds[i + 1]:
            return i
    return None
