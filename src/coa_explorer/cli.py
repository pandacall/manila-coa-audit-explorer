"""Command line for COA Audit Explorer."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from coa_explorer import links, part2, part3, smoke
from coa_explorer.config import DEFAULT_INDEX, REPO_ROOT, load_settings
from coa_explorer.embedder import Embedder, GeminiEmbedder
from coa_explorer.index import build_index, load_records

DEFAULT_REPORTS = REPO_ROOT / "coa-audit-reports"
DEFAULT_OUT = REPO_ROOT / "data" / "extracted"
LINK_REPORT = "link-report.json"
YEARS = (2020, 2021, 2022, 2023, 2024)


def main(argv: Sequence[str] | None = None, *, embedder: Embedder | None = None) -> int:
    """Run a step. `embedder` replaces Gemini for `index` (tests pass a fake)."""
    parser = argparse.ArgumentParser(prog="coa-explorer", description=__doc__)
    steps = parser.add_subparsers(dest="step", required=True)

    extract = steps.add_parser(
        "extract", help="extract Part II and Part III into JSON records, and report their links"
    )
    extract.add_argument("--reports", type=Path, default=DEFAULT_REPORTS, help="raw AAR folder")
    extract.add_argument(
        "--out", type=Path, default=DEFAULT_OUT, help="where part2/, part3/ and the report go"
    )
    extract.add_argument(
        "--check",
        action="store_true",
        help="write nothing; exit 1 if the records in --out differ from a fresh extraction",
    )

    index = steps.add_parser(
        "index", help="build the SQLite search index (keyword and embeddings) from the records"
    )
    index.add_argument("--records", type=Path, default=DEFAULT_OUT, help="extracted records")
    index.add_argument("--out", type=Path, default=DEFAULT_INDEX, help="the SQLite file to write")

    link = steps.add_parser(
        "links", help="print how Part III references link to Part II, with unmatched ones and drift"
    )
    link.add_argument("--records", type=Path, default=DEFAULT_OUT, help="extracted records")

    serve = steps.add_parser("serve", help="run the web app locally")
    serve.add_argument("--host", default="127.0.0.1")
    # Cloud Run says which port to listen on through $PORT.
    serve.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))

    check = steps.add_parser("smoke", help="ask a running app a question and check the answer")
    check.add_argument("--url", required=True, help="base URL of the running app")
    check.add_argument("--question", default=smoke.QUESTION)
    check.add_argument(
        "--timeout", type=float, default=smoke.TIMEOUT_SECONDS, help="seconds to wait per request"
    )

    args = parser.parse_args(argv)
    if args.step == "index":
        return index_step(args.records, args.out, embedder or gemini_embedder())
    if args.step == "serve":
        return serve_step(args.host, args.port)
    if args.step == "links":
        return links_step(args.records)
    if args.step == "smoke":
        return smoke_step(args.url, args.question, args.timeout)
    return extract_step(args.reports, args.out, check=args.check)


def extract_step(reports: Path, out: Path, *, check: bool = False) -> int:
    part2_records = {year: part2.extract_year(reports, year) for year in YEARS}
    part3_records = {year: part3.extract_year(reports, year) for year in YEARS}
    link_report = links.report(
        links.build_links(
            {year: record.to_dict() for year, record in part2_records.items()},
            {year: record.to_dict() for year, record in part3_records.items()},
        )
    )
    outputs = {
        **{
            Path("part2") / f"{year}.json": record.to_dict()
            for year, record in part2_records.items()
        },
        **{
            Path("part3") / f"{year}.json": record.to_dict()
            for year, record in part3_records.items()
        },
        Path(LINK_REPORT): link_report,
    }
    stale: list[str] = []
    for relative, record in outputs.items():
        text = render(record)
        target = out / relative
        if check:
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                stale.append(relative.as_posix())
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        # newline="" keeps the line endings identical on every platform, so reruns never diff.
        with target.open("w", encoding="utf-8", newline="") as f:
            f.write(text)
        print(f"wrote {target}")
    if stale:
        print(f"stale records: {', '.join(stale)}; run `coa-explorer extract`", file=sys.stderr)
        return 1
    return 0


def gemini_embedder() -> GeminiEmbedder:
    settings = load_settings()
    return GeminiEmbedder(
        project=settings.gcp_project_id,
        location=settings.gemini_location,
        model=settings.gemini_embedding_model,
    )


def index_step(records: Path, out: Path, embedder: Embedder) -> int:
    count = build_index(records, out, embedder)
    print(f"indexed {count} pieces into {out}")
    return 0


def links_step(records: Path) -> int:
    part2_records = load_records(records / "part2")
    part3_records = load_records(records / "part3")
    result = links.report(links.build_links(part2_records, part3_records))
    counts = result["counts"]
    print(
        f"{sum(counts.values())} Part III references: {counts[links.LINKED]} linked to Part II,"
        f" {counts[links.OUT_OF_COLLECTION]} out of the collection,"
        f" {counts[links.UNMATCHED]} unmatched"
    )
    for item in result["unmatched"]:
        print(f"unmatched: CY {item['tracked_in']} Part III, {item['reference']}: {item['reason']}")
    drifts = [d["drift"] for d in result["page_drift"]]
    if drifts:
        print(
            f"derived Part II starting page vs COA's citation: {len(drifts)} links, drift from"
            f" {min(drifts)} to {max(drifts)} pages"
        )
    for d in result["page_drift"]:
        if d["drift"]:
            print(f"  CY {d['tracked_in']} Part III cites {d['origin']}: drift {d['drift']:+d}")
    return 0


def smoke_step(url: str, question: str, timeout: float) -> int:
    problems = smoke.check(url, question, timeout)
    for problem in problems:
        print(f"smoke check failed: {problem}", file=sys.stderr)
    if not problems:
        print(f"{url} answered with cited key points")
    return 1 if problems else 0


def serve_step(host: str, port: int) -> int:
    # Imported here so `extract` and `index` don't need Gemini or the web stack loaded.
    import uvicorn

    from coa_explorer.answer import AnswerEngine
    from coa_explorer.api import create_app
    from coa_explorer.gemini import GeminiAdapter
    from coa_explorer.search import Index

    settings = load_settings()
    adapter = GeminiAdapter(
        project=settings.gcp_project_id,
        location=settings.gemini_location,
        model=settings.gemini_answer_model,
    )
    index = Index.open(settings.index_path, gemini_embedder())
    app = create_app(AnswerEngine(adapter, index))
    uvicorn.run(app, host=host, port=port)
    return 0


def render(record: dict) -> str:
    """Indented, human-readable JSON with a stable key order and LF line endings."""
    return json.dumps(record, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
