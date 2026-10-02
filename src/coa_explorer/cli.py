"""Command line for COA Audit Explorer."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from coa_explorer import links, part2, part3
from coa_explorer.config import (
    DEFAULT_INDEX,
    DEFAULT_SAVED_ANSWERS,
    REPO_ROOT,
    Settings,
    load_settings,
)
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
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument(
        "--no-demo-limits",
        action="store_true",
        help="skip the rate limits, daily cap, question log and feedback (no Firestore needed)",
    )

    examples = steps.add_parser(
        "save-examples",
        help="ask the example questions of the real model and save the answers shown when the"
        " demo's daily cap is reached",
    )
    examples.add_argument("--out", type=Path, default=DEFAULT_SAVED_ANSWERS)

    args = parser.parse_args(argv)
    if args.step == "index":
        return index_step(args.records, args.out, embedder or gemini_embedder())
    if args.step == "serve":
        return serve_step(args.host, args.port, demo_limits=not args.no_demo_limits)
    if args.step == "save-examples":
        return save_examples_step(args.out)
    if args.step == "links":
        return links_step(args.records)
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


def answer_engine(settings: Settings):
    # Imported here so `extract` and `index` don't need Gemini or the web stack loaded.
    from coa_explorer.answer import AnswerEngine
    from coa_explorer.gemini import GeminiAdapter
    from coa_explorer.search import Index

    adapter = GeminiAdapter(
        project=settings.gcp_project_id,
        location=settings.gemini_location,
        model=settings.gemini_answer_model,
    )
    return AnswerEngine(adapter, Index.open(settings.index_path, gemini_embedder()))


def demo_guard(settings: Settings):
    from coa_explorer.demo import Demo, load_saved_answers
    from coa_explorer.firestore_store import FirestoreStore

    store = FirestoreStore(
        project=settings.gcp_project_id,
        database=settings.firestore_database,
        questions_collection=settings.firestore_log_collection,
        counters_collection=settings.firestore_limits_collection,
        ttl_field=settings.firestore_ttl_field,
    )
    return Demo(
        store,
        salt=settings.ip_hash_salt,
        hourly_limit=settings.hourly_limit_per_ip,
        daily_cap=settings.daily_question_cap,
        examples=load_saved_answers(DEFAULT_SAVED_ANSWERS),
    )


def serve_step(host: str, port: int, *, demo_limits: bool = True) -> int:
    import uvicorn

    from coa_explorer.api import create_app

    settings = load_settings()
    demo = None
    if demo_limits and settings.firestore_database:
        demo = demo_guard(settings)
    else:
        print("running without demo limits, question logging or feedback", file=sys.stderr)
    uvicorn.run(create_app(answer_engine(settings), demo), host=host, port=port)
    return 0


def save_examples_step(out: Path) -> int:
    from coa_explorer.answer import Answer
    from coa_explorer.demo import EXAMPLE_QUESTIONS, SavedAnswer, save_answers

    engine = answer_engine(load_settings())
    saved = []
    for question in EXAMPLE_QUESTIONS:
        final = list(engine.ask(question))[-1]
        answer = final if isinstance(final, Answer) else None
        print(f"{'saved' if answer else 'no answer for'}: {question}")
        saved.append(SavedAnswer(question=question, answer=answer))
    save_answers(out, saved)
    print(f"wrote {out}")
    return 0


def render(record: dict) -> str:
    """Indented, human-readable JSON with a stable key order and LF line endings."""
    return json.dumps(record, indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
