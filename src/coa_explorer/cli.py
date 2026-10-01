"""Command line for COA Audit Explorer."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from coa_explorer.part2 import extract_year

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORTS = REPO_ROOT / "coa-audit-reports"
DEFAULT_OUT = REPO_ROOT / "data" / "extracted" / "part2"
YEARS = (2020, 2021, 2022, 2023, 2024)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coa-explorer", description=__doc__)
    steps = parser.add_subparsers(dest="step", required=True)

    extract = steps.add_parser("extract", help="extract Part II Audit Observations to JSON records")
    extract.add_argument("--reports", type=Path, default=DEFAULT_REPORTS, help="raw AAR folder")
    extract.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where the records go")
    extract.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if the records in --out differ from a fresh extraction",
    )

    args = parser.parse_args(argv)
    return extract_step(args.reports, args.out, check=args.check)


def extract_step(reports: Path, out: Path, *, check: bool = False) -> int:
    stale: list[str] = []
    for year in YEARS:
        text = render(extract_year(reports, year).to_dict())
        target = out / f"{year}.json"
        if check:
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                stale.append(target.name)
            continue
        out.mkdir(parents=True, exist_ok=True)
        # newline="" keeps the line endings identical on every platform, so reruns never diff.
        with target.open("w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"wrote {target}")
    if stale:
        print(f"stale records: {', '.join(stale)}; run `coa-explorer extract`", file=sys.stderr)
        return 1
    return 0


def render(record: dict) -> str:
    """Indented, human-readable JSON with a stable key order and LF line endings."""
    return json.dumps(record, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
