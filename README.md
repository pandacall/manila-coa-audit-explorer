# COA Audit Explorer

Plain-language, cited answers to questions about the Commission on Audit's Annual Audit Reports
on the City of Manila, 2020-2024. See `CONTEXT.md` for the project vocabulary and `docs/adr/` for
design decisions.

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```

## Extracting Parts II and III

```bash
uv run coa-explorer extract
```

Reads each year's Part II (Audit Observations and Recommendations) and Part III (Status of
Implementation of Prior Years' Recommendations) Word files under `coa-audit-reports/` and writes
committed, human-readable JSON to `data/extracted/`: `part2/<year>.json`, `part3/<year>.json` (one
record per Prior Years' Recommendation, with COA's Status of Implementation, Management's action and
the reason given) and `link-report.json`. Re-running produces no diff. To check that the committed
records are current without writing anything (exit code 1 if they are stale):

```bash
uv run coa-explorer extract --check
```

Part III's Reference column is parsed to AAR year, observation number and pages, and each block of
rows is linked to its Originating Observation in Part II. References to observations from before
2020 are marked out-of-collection (they still get timelines, cited to the AAR that tracks them), and
any reference that matches nothing is listed as unmatched rather than dropped. `link-report.json`
holds the counts, the unmatched references and the observed page drift (ADR-0001: derived Part II
starting pages against the pages COA cites in the following Part III; exact for 2020-2022, within 2
pages for 2023). Print it with:

```bash
uv run coa-explorer links
```

Where a Word cell's paragraphs cannot be matched one-to-one with the recommendations in it, the
whole cell text is attached to each recommendation it covers and the column is named in the record's
`shared` list, so nothing is dropped and nothing is guessed.

## Asking questions locally

Needs the settings from `scripts/setup-gcp.sh` in `.env` (`GCP_PROJECT_ID`, `GEMINI_LOCATION`,
`GEMINI_ANSWER_MODEL`; see `.env.example`) and Application Default Credentials
(`gcloud auth application-default login`). No API keys are used.

```bash
uv run coa-explorer index   # builds build/coa.sqlite from data/extracted/ (git-ignored)
uv run coa-explorer serve   # http://127.0.0.1:8000
```

`index` needs no GCP access; rebuild it whenever the extracted records change. Open
http://127.0.0.1:8000, ask a question about Part II or about whether the City acted on COA's
recommendations, and the page shows the summary and key points, each with Citation chips in COA's
format. A follow-up question also shows a timeline: when the observation was raised and COA's Status
of Implementation in each later AAR, with Management's action kept apart and attributed. The page
loads React from a CDN, so it needs internet.
The answer model is `GEMINI_ANSWER_MODEL`; change it in `.env` to compare models.

The page streams from `POST /api/ask` (`{"question": "..."}`), which returns newline-delimited
JSON: `status` events while the model searches, then one `answer` (with its `timelines`, if any),
`not_covered` or `error` event.

Verified against real Gemini (2026-10-02) with: "What did COA observe about cash advances in
Manila?" (cited answer), "Did Manila comply with IPSAS 1 in its financial statements? Which years?"
(cited answer across 2022-2024), "What did COA say about Quezon City's budget?" (not covered), and a
Filipino question about 2023 Observation No. 5 (cited answer, but in English; answering in the
question's language is a later ticket).
