"""Evaluation results as a machine-readable file and a markdown summary."""

from __future__ import annotations

import json
from pathlib import Path

from coa_explorer.evaluate import Evaluation

RESULTS_FILE = "results.json"
SUMMARY_FILE = "summary.md"


def write_report(out: Path, run: dict, evaluation: Evaluation) -> None:
    out.mkdir(parents=True, exist_ok=True)
    document = {"run": run, **evaluation.to_dict()}
    # newline="" keeps LF endings on every platform, like the extracted records.
    with (out / RESULTS_FILE).open("w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(document, indent=2, ensure_ascii=False) + "\n")
    with (out / SUMMARY_FILE).open("w", encoding="utf-8", newline="") as f:
        f.write(render_summary(run, evaluation))


def percent(value: float | None) -> str:
    return "n/a" if value is None else f"{value * 100:.1f}%"


def render_summary(run: dict, evaluation: Evaluation) -> str:
    s = evaluation.scores
    drift = s["page_drift"]
    lines = [
        "# Evaluation results",
        "",
        f"Answer model `{run['answer_model']}`, judge `{run['judge_model']}`. "
        f"{run['scored']} approved items scored ({s['answerable_items']} answerable, "
        f"{s['unanswerable_items']} unanswerable) of {run['items_in_file']} in the reference file.",
        "",
        "| Measure | Score |",
        "| --- | --- |",
        f"| Retrieval hit rate | {percent(s['retrieval_hit_rate'])} |",
        f"| Citation correctness | {percent(s['citation_correctness'])} |",
        f"| Faithfulness | {percent(s['faithfulness'])} |",
        f"| Key-fact coverage | {percent(s['key_fact_coverage'])} |",
        f"| Correct refusal (unanswerable items) | {percent(s['refusal_correctness'])} |",
        f"| False refusal (answerable items) | {percent(s['false_refusal_rate'])} |",
        "",
        "Page drift of correctly cited sources (cited starting page minus the expected one): "
        + (
            f"{drift['exact']} of {drift['matched_citations']} exact, mean "
            f"{drift['mean_abs_pages']} pages off, at most {drift['max_abs_pages']}."
            if drift["matched_citations"]
            else "no page comparisons."
        ),
    ]
    if s["errors"] or s["unjudged"]:
        lines += [
            "",
            f"**{s['errors']} item(s) errored and {s['unjudged']} could not be judged;** "
            "see `results.json`.",
        ]
    lines += [
        "",
        "## Items",
        "",
        "| Item | Type | Outcome | Retrieved | Citations | Supported | Facts |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in evaluation.items:
        lines.append(
            f"| {r.id} | {r.question_type}{' (unanswerable)' if r.unanswerable else ''} "
            f"| {outcome_cell(r)} | {yes_no(r.retrieval_hit)} | {citations_cell(r)} "
            f"| {ratio(r.supported)} | {ratio(r.facts_covered)} |"
        )
    return "\n".join(lines) + "\n"


def outcome_cell(r) -> str:
    if r.unanswerable:
        return "refused (correct)" if r.refusal_correct else f"{r.outcome} (wrong)"
    return r.outcome


def yes_no(value: bool | None) -> str:
    return "-" if value is None else "yes" if value else "no"


def citations_cell(r) -> str:
    if not r.citation_matches:
        return "-"
    found = sum(m.cited is not None for m in r.citation_matches)
    drifts = [f"{m.page_drift:+d}" for m in r.citation_matches if m.page_drift]
    return f"{found}/{len(r.citation_matches)}" + (
        f" (drift {', '.join(drifts)})" if drifts else ""
    )


def ratio(values: list[bool] | None) -> str:
    return "-" if values is None else f"{sum(values)}/{len(values)}"
