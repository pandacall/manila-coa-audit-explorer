"""Command line for COA Audit Explorer."""

from __future__ import annotations

import argparse
import functools
import json
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from coa_explorer import links, part2, part3
from coa_explorer.answer import AnswerEngine
from coa_explorer.config import DEFAULT_INDEX, REPO_ROOT, load_settings
from coa_explorer.embedder import Embedder, GeminiEmbedder
from coa_explorer.evaluate import BatchModel, evaluate
from coa_explorer.gemini import GeminiAdapter
from coa_explorer.gemini_judge import GeminiBatchJudge
from coa_explorer.index import build_index, load_records
from coa_explorer.models import ModelAdapter
from coa_explorer.reference import ReferenceFileError, load_reference
from coa_explorer.report import write_report
from coa_explorer.search import Index

DEFAULT_REPORTS = REPO_ROOT / "coa-audit-reports"
DEFAULT_OUT = REPO_ROOT / "data" / "extracted"
DEFAULT_REFERENCE = REPO_ROOT / "data" / "eval" / "reference.json"
DEFAULT_EVAL_OUT = REPO_ROOT / "build" / "eval"
LINK_REPORT = "link-report.json"
YEARS = (2020, 2021, 2022, 2023, 2024)


def main(
    argv: Sequence[str] | None = None,
    *,
    embedder: Embedder | None = None,
    adapter: ModelAdapter | None = None,
    judge: BatchModel | None = None,
) -> int:
    """Run a step. `embedder`, `adapter` and `judge` replace Gemini for `index` and `eval`
    (tests pass fakes)."""
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

    evaluation = steps.add_parser(
        "eval",
        help="score the approved reference items: retrieval, Citations, faithfulness, refusals",
    )
    evaluation.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    evaluation.add_argument("--index", type=Path, help="the SQLite index (default: COA_INDEX_PATH)")
    evaluation.add_argument(
        "--out", type=Path, default=DEFAULT_EVAL_OUT, help="where results.json and summary.md go"
    )
    evaluation.add_argument("--answer-model", help="default: GEMINI_ANSWER_MODEL")
    evaluation.add_argument("--judge-model", help="default: GEMINI_JUDGE_MODEL")
    evaluation.add_argument(
        "--limit", type=int, help="score only the first N approved items (the small CI subset)"
    )

    serve = steps.add_parser("serve", help="run the web app locally")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    if args.step == "index":
        return index_step(args.records, args.out, embedder or gemini_embedder())
    if args.step == "eval":
        return eval_step(args, embedder, adapter, judge)
    if args.step == "serve":
        return serve_step(args.host, args.port)
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


def eval_step(
    args: argparse.Namespace,
    embedder: Embedder | None,
    adapter: ModelAdapter | None,
    judge: BatchModel | None,
) -> int:
    try:
        items = load_reference(args.reference)
    except ReferenceFileError as error:
        print(error, file=sys.stderr)
        return 2
    approved = [item for item in items if item.approved]
    scored = approved[: args.limit] if args.limit is not None else approved

    # Settings are only read for what was not passed in, so tests need no GCP configuration.
    settings = functools.cache(load_settings)
    answer_model = args.answer_model or settings().gemini_answer_model
    judge_model = args.judge_model or settings().gemini_judge_model
    if not judge_model:
        print("no judge model: set GEMINI_JUDGE_MODEL or pass --judge-model", file=sys.stderr)
        return 2
    index_path = args.index or settings().index_path
    if adapter is None:
        adapter = GeminiAdapter(
            project=settings().gcp_project_id,
            location=settings().gemini_location,
            model=answer_model,
        )
    if judge is None and scored:
        if not settings().eval_batch_bucket:
            print(
                "batch judging needs a Cloud Storage bucket: set EVAL_BATCH_BUCKET"
                " (scripts/setup-gcp.sh creates one)",
                file=sys.stderr,
            )
            return 2
        judge = GeminiBatchJudge(
            project=settings().gcp_project_id,
            location=settings().gemini_batch_location or settings().gemini_location,
            model=judge_model,
            bucket=settings().eval_batch_bucket,
        )
    with Index.open(index_path, embedder or gemini_embedder()) as index:
        evaluation = evaluate(
            scored, AnswerEngine(adapter, index), judge, progress=lambda m: print(m, flush=True)
        )
    run = {
        "answer_model": answer_model,
        "judge_model": judge_model,
        "reference": args.reference.name,
        "items_in_file": len(items),
        "approved": len(approved),
        "scored": len(scored),
        "limit": args.limit,
        "finished_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    write_report(args.out, run, evaluation)
    print(f"wrote {args.out / 'results.json'} and {args.out / 'summary.md'}")
    return 0


def serve_step(host: str, port: int) -> int:
    # Imported here so `extract` and `index` don't need Gemini or the web stack loaded.
    import uvicorn

    from coa_explorer.api import create_app

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
