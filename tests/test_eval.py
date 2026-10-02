"""Seam 4: the `eval` command scores reference items through the answer engine and a batch judge.

Tests run `main(["eval", ...])` with a scripted answer model, an index of fixture records with a
fake embedder, and a scripted batch judge, then read the results files an owner would read.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from coa_explorer.cli import main
from coa_explorer.index import build_index
from coa_explorer.reference import load_reference
from tests.fake_embedder import FakeEmbedder
from tests.fixtures import write_fixture_records
from tests.scripted import ScriptedAdapter, ScriptedBatchModel, point, search, submit, verdict

IPSAS_5 = "2023-5-description-1"
CITATION_5 = "CY 2023 AAR, Part II, Observation No. 5, pp. 71-73"


@pytest.fixture()
def index_path(tmp_path):
    records = write_fixture_records(tmp_path / "records")
    build_index(records, tmp_path / "coa.sqlite", FakeEmbedder())
    return tmp_path / "coa.sqlite"


def item(**overrides) -> dict:
    record = {
        "id": "ipsas-1-2023",
        "question": "Did the 2023 statements follow IPSAS 1?",
        "language": "en",
        "question_type": "observation",
        "expected_citations": [CITATION_5],
        "key_facts": ["Comparative information was omitted"],
        "unanswerable": False,
        "approved": True,
    }
    record.update(overrides)
    return record


def run_eval(tmp_path, index_path, items, adapter, judge, *extra):
    reference = tmp_path / "reference.json"
    reference.write_text(json.dumps({"items": items}), encoding="utf-8")
    out = tmp_path / "out"
    code = main(
        [
            "eval",
            "--reference",
            str(reference),
            "--index",
            str(index_path),
            "--out",
            str(out),
            "--answer-model",
            "fake-flash",
            "--judge-model",
            "fake-pro",
            *extra,
        ],
        embedder=FakeEmbedder(),
        adapter=adapter,
        judge=judge,
    )
    results = out / "results.json"
    return code, json.loads(results.read_text(encoding="utf-8")) if results.exists() else None, out


def good_answer():
    return ScriptedAdapter(
        search("IPSAS 1"),
        submit(
            "COA observed the 2023 statements did not fully comply with IPSAS 1.",
            [point("Comparative information was omitted.", IPSAS_5)],
        ),
    )


def test_an_approved_item_answered_well_scores_full_marks_on_every_measure(tmp_path, index_path):
    judge = ScriptedBatchModel(lambda prompt: verdict([True], [True]))

    code, results, out = run_eval(tmp_path, index_path, [item()], good_answer(), judge)

    assert code == 0
    scores = results["scores"]
    assert scores["retrieval_hit_rate"] == 1.0
    assert scores["citation_correctness"] == 1.0
    assert scores["faithfulness"] == 1.0
    assert scores["key_fact_coverage"] == 1.0
    summary = (out / "summary.md").read_text(encoding="utf-8")
    assert "ipsas-1-2023" in summary
    assert "Retrieval hit rate" in summary


CASH_IN_BANK_1 = "2023-1-description-1"
CITATION_1 = "CY 2023 AAR, Part II, Observation No. 1, p. 71"
REFUSAL = submit("", [], covered=False, message="The reports do not cover that.")


def all_true(prompt):
    return verdict([True], [True])


def test_only_approved_items_are_asked_and_scored(tmp_path, index_path):
    items = [item(), item(id="draft", approved=False)]
    judge = ScriptedBatchModel(all_true)

    _, results, _ = run_eval(tmp_path, index_path, items, good_answer(), judge)

    assert [r["id"] for r in results["items"]] == ["ipsas-1-2023"]
    assert results["run"]["items_in_file"] == 2
    assert results["run"]["approved"] == 1


def test_a_citation_to_the_right_observation_on_a_drifted_page_is_correct_with_drift_reported(
    tmp_path, index_path
):
    expected = "CY 2023 AAR, Part II, Observation No. 5, pp. 70-72"  # the index says pp. 71-73
    judge = ScriptedBatchModel(all_true)

    _, results, out = run_eval(
        tmp_path, index_path, [item(expected_citations=[expected])], good_answer(), judge
    )

    assert results["scores"]["citation_correctness"] == 1.0
    assert results["scores"]["page_drift"] == {
        "matched_citations": 1,
        "exact": 0,
        "mean_abs_pages": 1.0,
        "max_abs_pages": 1,
    }
    assert "drift +1" in (out / "summary.md").read_text(encoding="utf-8")


def test_retrieving_the_expected_observation_but_not_citing_it_is_a_hit_without_a_correct_citation(
    tmp_path, index_path
):
    adapter = ScriptedAdapter(
        search("IPSAS 1"),
        submit("s", [point("Cash-in-Bank was not reconciled.", CASH_IN_BANK_1)]),
    )
    # Retrieving observation 5 requires the search to return it; cite another piece it also saw.
    judge = ScriptedBatchModel(all_true)

    _, results, _ = run_eval(tmp_path, index_path, [item()], adapter, judge)

    assert results["scores"]["retrieval_hit_rate"] == 1.0
    assert results["scores"]["citation_correctness"] == 0.0


def test_an_expected_observation_that_search_never_returned_is_a_retrieval_miss(
    tmp_path, index_path
):
    adapter = ScriptedAdapter(
        search("unliquidated cash advances"),
        submit("s", [point("Cash advances were unliquidated.", "2022-3-description-1")]),
    )
    judge = ScriptedBatchModel(all_true)

    _, results, _ = run_eval(tmp_path, index_path, [item()], adapter, judge)

    assert results["scores"]["retrieval_hit_rate"] == 0.0
    assert results["items"][0]["retrieval_hit"] is False


def test_unanswerable_items_are_scored_on_whether_the_app_refused(tmp_path, index_path):
    items = [
        item(id="refused", unanswerable=True, expected_citations=[], key_facts=[]),
        item(id="answered", unanswerable=True, expected_citations=[], key_facts=[]),
    ]
    adapter = ScriptedAdapter(
        REFUSAL,
        search("IPSAS 1"),
        submit("s", [point("An invented answer.", IPSAS_5)]),
    )
    judge = ScriptedBatchModel(lambda prompt: verdict([False], []))

    _, results, out = run_eval(tmp_path, index_path, items, adapter, judge)

    by_id = {r["id"]: r for r in results["items"]}
    assert by_id["refused"]["refusal_correct"] is True
    assert by_id["answered"]["refusal_correct"] is False
    assert results["scores"]["refusal_correctness"] == 0.5
    assert results["scores"]["retrieval_hit_rate"] is None
    assert "refused (correct)" in (out / "summary.md").read_text(encoding="utf-8")


def test_the_judge_scores_faithfulness_per_key_point_and_coverage_per_key_fact(
    tmp_path, index_path
):
    adapter = ScriptedAdapter(
        search("IPSAS 1"),
        submit(
            "s",
            [
                point("Comparative information was omitted.", IPSAS_5),
                point("The City was fined.", IPSAS_5),
            ],
        ),
    )
    judge = ScriptedBatchModel(lambda prompt: verdict([True, False], [True, False, False]))
    facts = ["Comparative information was omitted", "The SEF was affected", "IPSAS 1 applies"]

    _, results, _ = run_eval(tmp_path, index_path, [item(key_facts=facts)], adapter, judge)

    assert results["scores"]["faithfulness"] == 0.5
    assert results["scores"]["key_fact_coverage"] == pytest.approx(0.3333, abs=1e-4)
    # One batch for all the answers, in which the judge sees the answer and the cited passage.
    assert len(judge.batches) == 1
    system, prompts = judge.batches[0]
    assert "Faithfulness" in system
    assert "The City was fined." in prompts[0]
    assert "comparative information was omitted" in prompts[0].lower()
    assert "The SEF was affected" in prompts[0]


def test_an_answerable_item_the_app_refused_counts_as_a_false_refusal_with_no_facts_covered(
    tmp_path, index_path
):
    judge = ScriptedBatchModel(all_true)

    _, results, _ = run_eval(tmp_path, index_path, [item()], ScriptedAdapter(REFUSAL), judge)

    scores = results["scores"]
    assert scores["false_refusal_rate"] == 1.0
    assert scores["key_fact_coverage"] == 0.0
    assert scores["citation_correctness"] == 0.0
    assert judge.batches == []  # nothing was answered, so there was nothing to judge


def test_an_item_that_fails_is_reported_and_the_rest_are_still_scored(tmp_path, index_path):
    def broken(messages):
        raise RuntimeError("model unavailable")

    adapter = ScriptedAdapter(broken, *good_answer()._turns)
    items = [item(id="fails"), item(id="works")]
    judge = ScriptedBatchModel(all_true)

    _, results, _ = run_eval(tmp_path, index_path, items, adapter, judge)

    by_id = {r["id"]: r for r in results["items"]}
    assert by_id["fails"]["outcome"] == "error"
    assert "model unavailable" in by_id["fails"]["detail"]
    assert by_id["works"]["outcome"] == "answered"
    assert results["scores"]["errors"] == 1
    assert results["scores"]["citation_correctness"] == 0.5


def test_a_judge_reply_that_cannot_be_used_is_reported_not_scored(tmp_path, index_path):
    judge = ScriptedBatchModel(lambda prompt: "I think it is fine.")

    code, results, _ = run_eval(tmp_path, index_path, [item()], good_answer(), judge)

    assert code == 0
    assert results["scores"]["unjudged"] == 1
    assert results["scores"]["faithfulness"] is None
    assert results["scores"]["citation_correctness"] == 1.0
    assert "unusable judge reply" in results["items"][0]["judge_error"]


def test_a_judge_reply_in_a_json_code_fence_is_accepted(tmp_path, index_path):
    fenced = '```json\n{"supported": [true], "facts_covered": [true]}\n```'
    judge = ScriptedBatchModel(lambda prompt: fenced)

    _, results, _ = run_eval(tmp_path, index_path, [item()], good_answer(), judge)

    assert results["scores"]["faithfulness"] == 1.0


def test_limit_scores_only_the_first_approved_items(tmp_path, index_path):
    items = [item(id="first"), item(id="second")]
    judge = ScriptedBatchModel(all_true)

    _, results, _ = run_eval(tmp_path, index_path, items, good_answer(), judge, "--limit", "1")

    assert [r["id"] for r in results["items"]] == ["first"]
    assert results["run"]["approved"] == 2
    assert results["run"]["scored"] == 1


def test_the_results_record_which_models_produced_them(tmp_path, index_path):
    judge = ScriptedBatchModel(all_true)

    _, results, out = run_eval(tmp_path, index_path, [item()], good_answer(), judge)

    assert results["run"]["answer_model"] == "fake-flash"
    assert results["run"]["judge_model"] == "fake-pro"
    assert "fake-flash" in (out / "summary.md").read_text(encoding="utf-8")


def test_with_nothing_approved_the_run_succeeds_and_needs_no_judge(tmp_path, index_path):
    code, results, _ = run_eval(
        tmp_path, index_path, [item(approved=False)], ScriptedAdapter(), None
    )

    assert code == 0
    assert results["items"] == []
    assert results["scores"]["retrieval_hit_rate"] is None


@pytest.mark.parametrize(
    "bad, complaint",
    [
        (item(expected_citations=["Observation 5 in 2023"]), "not a Citation in COA's format"),
        (item(key_facts=[]), "needs expected Citations and key facts"),
        (item(unanswerable=True), "no expected Citations or key facts"),
        (item(language="de"), "language"),
        (item(approved=None), "approved"),
    ],
)
def test_an_invalid_reference_item_is_rejected_by_name_before_anything_runs(
    tmp_path, index_path, capsys, bad, complaint
):
    code, results, out = run_eval(tmp_path, index_path, [bad], ScriptedAdapter(), None)

    assert code == 2
    assert results is None
    error = capsys.readouterr().err
    assert "ipsas-1-2023" in error
    assert complaint in error


def test_duplicate_item_ids_are_rejected(tmp_path, index_path, capsys):
    code, _, _ = run_eval(tmp_path, index_path, [item(), item()], ScriptedAdapter(), None)

    assert code == 2
    assert "duplicate" in capsys.readouterr().err


def test_the_committed_reference_set_is_valid_and_cites_observations_that_exist():
    root = Path(__file__).resolve().parents[1]
    items = load_reference(root / "data" / "eval" / "reference.json")
    real = {
        observation["citation"]
        for year in range(2020, 2025)
        for observation in json.loads(
            (root / "data" / "extracted" / "part2" / f"{year}.json").read_text(encoding="utf-8")
        )["observations"]
    }

    assert len(items) >= 10
    assert {item.language for item in items} >= {"en", "fil"}
    assert any(item.unanswerable for item in items)
    for item in items:
        assert set(item.expected_citations) <= real, item.id
