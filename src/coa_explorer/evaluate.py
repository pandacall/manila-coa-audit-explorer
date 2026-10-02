"""The evaluation harness: runs approved reference items through the answer engine and scores them.

Per item it measures, without a model: whether the passages the model was shown include an expected
source (retrieval), whether the answer cites the expected sources (Citation correctness, with page
drift reported apart since pages are best-effort, ADR-0001), and whether an unanswerable question
was refused. A stronger model judges, in one batch, whether each key point is supported by the
passages it cites (faithfulness) and whether the answer states each key fact (coverage).

Rates are pooled over items: Citation correctness is expected Citations matched over expected
Citations, faithfulness is supported key points over key points, coverage is facts covered over
facts. An item that errors or refuses wrongly counts for nothing rather than dropping out.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from typing import Protocol

from coa_explorer.answer import Answer, AnswerEngine, NotCovered
from coa_explorer.citation import ParsedCitation, Source, parse_citation
from coa_explorer.reference import ReferenceItem
from coa_explorer.search import Piece

MAX_PASSAGE_CHARS = 2500  # as much of a passage as the answer model was given

JUDGE_SYSTEM = """\
You are a strict, impartial grader of answers about the Commission on Audit's (COA) Annual Audit \
Reports on the City of Manila. You are given a question, the source passages an answer was allowed \
to use, the answer's key points, and the key facts a good answer must state.

Faithfulness: a key point is supported only if the source passages state or directly entail every \
claim in it, including each number, year, status and who said it. Wording may differ. A point that \
adds outside information, overstates what the passage says (for example calls a deficiency fraud), \
or presents Management's claim as COA's own assessment is not supported. Judge only against the \
passages, never your own knowledge.

Coverage: a key fact is covered if the answer's summary or key points state it, in any wording or \
language. A vague gesture at the topic does not cover a specific fact.

Reply with JSON only: {"supported": [...], "facts_covered": [...]} holding one true/false per key \
point and one per key fact, in the order given."""


class BatchModel(Protocol):
    """A model that answers many prompts in one batch; None for a prompt that got no reply."""

    def generate_batch(self, system: str, prompts: list[str]) -> list[str | None]: ...


@dataclass
class CitationMatch:
    expected: str
    cited: str | None  # the Citation in the answer that names the same source, if any
    page_drift: int | None  # cited start page minus expected start page, when both have one


@dataclass
class ItemResult:
    id: str
    question: str
    question_type: str
    language: str
    unanswerable: bool
    outcome: str  # "answered", "refused" or "error"
    detail: str | None = None  # the engine's error, or its not-covered message
    summary: str | None = None
    key_points: list[dict] = field(default_factory=list)  # {"text", "citations"}
    retrieved_citations: list[str] = field(default_factory=list)
    retrieval_hit: bool | None = None  # answerable items only
    citation_matches: list[CitationMatch] = field(default_factory=list)
    refusal_correct: bool | None = None  # unanswerable items only
    supported: list[bool] | None = None  # per key point, from the judge
    facts_covered: list[bool] | None = None  # per key fact, from the judge
    judge_error: str | None = None


@dataclass
class Evaluation:
    items: list[ItemResult]
    scores: dict

    def to_dict(self) -> dict:
        return {"scores": self.scores, "items": [asdict(item) for item in self.items]}


def evaluate(
    items: list[ReferenceItem],
    engine: AnswerEngine,
    judge: BatchModel | None,
    progress: Callable[[str], None] = lambda message: None,
) -> Evaluation:
    """Score `items`. `judge` is only needed (and called, once) if some item produced an answer."""
    results: list[ItemResult] = []
    passages: dict[str, list[Piece]] = {}  # item id -> the pieces its answer cites
    for position, item in enumerate(items, start=1):
        progress(f"[{position}/{len(items)}] {item.id}")
        result, cited = answer_item(engine, item)
        results.append(result)
        passages[item.id] = cited
    by_id = {item.id: item for item in items}
    judging = [r for r in results if r.outcome == "answered"]
    if judging:
        if judge is None:
            raise ValueError("a judge model is needed to score the answered items")
        progress(f"judging {len(judging)} answers in one batch")
        prompts = [judge_prompt(by_id[r.id], r, passages[r.id]) for r in judging]
        replies = judge.generate_batch(JUDGE_SYSTEM, prompts)
        if len(replies) != len(prompts):
            raise ValueError(
                f"the judge returned {len(replies)} replies for {len(prompts)} prompts"
            )
        for result, reply in zip(judging, replies, strict=True):
            apply_verdict(result, by_id[result.id], reply)
    return Evaluation(results, score(items, results))


def answer_item(engine: AnswerEngine, item: ReferenceItem) -> tuple[ItemResult, list[Piece]]:
    result = ItemResult(
        id=item.id,
        question=item.question,
        question_type=item.question_type,
        language=item.language,
        unanswerable=item.unanswerable,
        outcome="error",
    )
    retrieved: dict[str, Piece] = {}
    final = None
    try:
        for event in engine.ask(item.question, retrieved):
            final = event
    except Exception as error:  # one bad item must not lose the rest of the run
        result.detail = f"{type(error).__name__}: {error}"
        final = None
    result.retrieved_citations = sorted({piece.citation for piece in retrieved.values()})
    if not item.unanswerable:
        found = sources(result.retrieved_citations)
        result.retrieval_hit = any(s in found for s in expected_sources(item))
    cited_pieces: list[Piece] = []
    cited: list[str] = []
    if isinstance(final, NotCovered):
        result.outcome, result.detail = "refused", final.message
    elif isinstance(final, Answer):
        result.outcome, result.summary = "answered", final.summary
        result.key_points = [
            {"text": kp.text, "citations": [c.text for c in kp.citations]}
            for kp in final.key_points
        ]
        cited_texts = {citation for kp in result.key_points for citation in kp["citations"]}
        for timeline in final.timelines:  # a timeline's steps are cited by the page, not the text
            cited_texts.update(retrieved[key].citation for key in timeline.keys if key in retrieved)
        cited = sorted(cited_texts)
        cited_pieces = [piece for piece in retrieved.values() if piece.citation in cited_texts]
    elif result.detail is None:
        result.detail = "the engine produced no answer"
    if item.unanswerable:
        result.refusal_correct = result.outcome == "refused"
    else:
        result.citation_matches = match_citations(item, cited)
    return result, cited_pieces


def expected_sources(item: ReferenceItem) -> list[Source]:
    return [parse_citation(c).source for c in item.expected_citations]


def sources(citations: list[str]) -> set[Source]:
    found = set()
    for citation in citations:
        try:
            found.add(parse_citation(citation).source)
        except ValueError:
            continue  # a Citation we cannot read can't match an expected one
    return found


def match_citations(item: ReferenceItem, cited: list[str]) -> list[CitationMatch]:
    """For each expected Citation, the cited one naming the same source, and how far its page is."""
    parsed: list[tuple[str, ParsedCitation]] = []
    for text in cited:
        try:
            parsed.append((text, parse_citation(text)))
        except ValueError:
            continue
    matches = []
    for expected_text in item.expected_citations:
        expected = parse_citation(expected_text)
        same = [(text, c) for text, c in parsed if c.source == expected.source]
        if not same:
            matches.append(CitationMatch(expected_text, None, None))
            continue
        text, best = min(same, key=lambda pair: distance(pair[1], expected))
        drift = None
        if best.page_start is not None and expected.page_start is not None:
            drift = best.page_start - expected.page_start
        matches.append(CitationMatch(expected_text, text, drift))
    return matches


def distance(cited: ParsedCitation, expected: ParsedCitation) -> int:
    """How far apart two Citations' starting pages are, for picking the closest of several."""
    if cited.page_start is None or expected.page_start is None:
        return 0
    return abs(cited.page_start - expected.page_start)


def judge_prompt(item: ReferenceItem, result: ItemResult, cited: list[Piece]) -> str:
    passages = "\n\n".join(
        f"[{piece.citation}]\n{piece.text[:MAX_PASSAGE_CHARS]}" for piece in cited
    )
    points = "\n".join(
        f"{n}. {kp['text']} (cites: {'; '.join(kp['citations'])})"
        for n, kp in enumerate(result.key_points, start=1)
    )
    facts = "\n".join(f"{n}. {fact}" for n, fact in enumerate(item.key_facts, start=1))
    return (
        f"Question: {item.question}\n\n"
        f"Source passages the answer could use:\n{passages or '(none)'}\n\n"
        f"Answer summary: {result.summary}\n\n"
        f"Answer key points ({len(result.key_points)}):\n{points}\n\n"
        f"Key facts a good answer must state ({len(item.key_facts)}):\n{facts or '(none)'}\n"
    )


def apply_verdict(result: ItemResult, item: ReferenceItem, reply: str | None) -> None:
    """Record the judge's verdict on an item, or why there is none."""
    try:
        if reply is None:
            raise ValueError("the judge gave no reply")
        verdict = json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", reply.strip()))
        supported, covered = verdict["supported"], verdict["facts_covered"]
        for name, values, wanted in (
            ("supported", supported, len(result.key_points)),
            ("facts_covered", covered, len(item.key_facts)),
        ):
            valid = isinstance(values, list) and all(isinstance(v, bool) for v in values)
            if not valid or len(values) != wanted:
                raise ValueError(f"'{name}' should be {wanted} true/false values")
    except (ValueError, KeyError, TypeError) as error:
        result.judge_error = f"unusable judge reply: {error}"
        return
    result.supported, result.facts_covered = supported, covered


def rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 4) if denominator else None


def score(items: list[ReferenceItem], results: list[ItemResult]) -> dict:
    answerable = [r for r in results if not r.unanswerable]
    unanswerable = [r for r in results if r.unanswerable]
    matches = [m for r in answerable for m in r.citation_matches]
    matched = [m for m in matches if m.cited is not None]
    drifts = [abs(m.page_drift) for m in matched if m.page_drift is not None]
    facts_by_id = {item.id: len(item.key_facts) for item in items}
    # A judged item contributes its verdict; a refused or errored one, no facts covered. An item
    # whose judge reply was unusable is left out here and counted under `unjudged`.
    coverage = [r for r in answerable if r.outcome != "answered" or r.facts_covered is not None]
    judged = [r for r in results if r.supported is not None]
    return {
        "answerable_items": len(answerable),
        "unanswerable_items": len(unanswerable),
        "retrieval_hit_rate": rate(sum(bool(r.retrieval_hit) for r in answerable), len(answerable)),
        "citation_correctness": rate(len(matched), len(matches)),
        "page_drift": {
            "matched_citations": len(drifts),
            "exact": sum(d == 0 for d in drifts),
            "mean_abs_pages": round(sum(drifts) / len(drifts), 2) if drifts else None,
            "max_abs_pages": max(drifts) if drifts else None,
        },
        "faithfulness": rate(
            sum(sum(r.supported) for r in judged), sum(len(r.supported) for r in judged)
        ),
        "key_fact_coverage": rate(
            sum(sum(r.facts_covered or []) for r in coverage),
            sum(facts_by_id[r.id] for r in coverage),
        ),
        "refusal_correctness": rate(
            sum(bool(r.refusal_correct) for r in unanswerable), len(unanswerable)
        ),
        "false_refusal_rate": rate(
            sum(r.outcome == "refused" for r in answerable), len(answerable)
        ),
        "errors": sum(r.outcome == "error" for r in results),
        "unjudged": sum(r.judge_error is not None for r in results),
    }
