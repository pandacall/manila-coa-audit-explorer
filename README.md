# COA Audit Explorer

Plain-language, cited answers to questions about the Commission on Audit's Annual Audit Reports
on the City of Manila, 2020-2024. See `CONTEXT.md` for the project vocabulary and `docs/adr/` for
design decisions.

**Live demo:** https://coa-explorer-417534361115.us-central1.run.app (on Cloud Run, so the first
question after a quiet spell takes a few seconds longer).

## Development

```bash
uv sync
uv run pytest
uv run ruff check .
```

## Extracting the AARs

```bash
uv run coa-explorer extract
```

Reads each year's Executive Summary, Auditor's Report, Part II (Audit Observations and
Recommendations) and Part III (Status of Implementation of Prior Years' Recommendations) under
`coa-audit-reports/` and writes committed, human-readable JSON to `data/extracted/`:
`executive_summary/<year>.json`, `auditors_report/<year>.json` (one record per section),
`part2/<year>.json`, `part3/<year>.json` (one record per Prior Years' Recommendation, with COA's
Status of Implementation, Management's action and the reason given) and `link-report.json`.
Re-running produces no diff. To check that the committed
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

### Executive Summary and Auditor's Report

Both are split into COA's own sections, each one a piece with its own Citation: the Executive
Summary's lettered sections ("CY 2023 AAR, Executive Summary, Section E, p. iii"; its pages are the
lowercase Roman numerals COA prints) and the Auditor's Report's standard headings ("CY 2022 AAR,
Part I, Auditor's Report, pp. 2-3"). Which file is read differs by year: the Executive Summary is
Word for 2020-2023 and PDF for 2024; the Auditor's Report is Word for 2020-2021 and PDF for
2022-2024. The PDF Executive Summaries COA also published for 2020-2023 (`_duplicates/`) are never
extracted; the tests use them only to check the Word-derived Roman pages.

PDF pages are the PDF's real pages (the reader checks that the page number each page prints is
its position in the PDF), read from the text the PDF already carries; nothing is OCR'd. PDF text
layers have small spacing artefacts from how COA's files were produced ("relat ed"), which are left
as they are. Word pages are derived from the saved layout (ADR-0001), so they are best-effort: the
2021-2023 Executive Summaries agree exactly with COA's PDF renderings, but the CY 2020 one is
derived a page early from Section C on because Word saved no page break after its first table.
The section letter is the exact anchor.

The CY 2023 Auditor's Report is a scan whose text layer is too garbled to cite ("Qualffled", "Section
7 4"), so its text comes from a reviewed transcription in `data/reviewed/` instead; see the README
there. `extract --reviewed <dir>` reads transcriptions from another folder.

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

`index` embeds every piece with `GEMINI_EMBEDDING_MODEL` (gemini-embedding-001, 768 dimensions) on
Vertex AI, so it needs the same GCP access as `serve` and takes about half a minute; rebuild it
whenever the extracted records or the embedding model change. Search merges keyword (FTS5) and
vector (sqlite-vec) matches into one ranking, can be narrowed by year, part (`ES` Executive
Summary, `I` Auditor's Report, `II`, `III`) or observation number, and with no year named returns
the newest year first. Open http://127.0.0.1:8000, ask a question
about Part II or about whether the City acted on COA's recommendations, and the page shows the
summary and key points, each with Citation chips in COA's format. A follow-up question also shows a
timeline: when the observation was raised and COA's Status of Implementation in each later AAR,
with Management's action kept apart and attributed. The page loads React from a CDN, so it needs
internet.
The answer model is `GEMINI_ANSWER_MODEL`; change it in `.env` to compare models.

The page streams from `POST /api/ask` (`{"question": "..."}`), which returns newline-delimited
JSON: `status` events while the model searches, then one `answer` (with its `timelines`, if any),
`not_covered` or `error` event.

Verified against real Gemini (2026-10-02) with: "What did COA observe about cash advances in
Manila?" (cited answer), "Did Manila comply with IPSAS 1 in its financial statements? Which years?"
(cited answer across 2022-2024), "What did COA say about Quezon City's budget?" (not covered), and a
Filipino question about 2023 Observation No. 5 (cited answer, but in English; answering in the
question's language is a later ticket).

Hybrid search verified against real Gemini (2026-10-02) with: "Did the city ever fail to collect
money that employees borrowed and never paid back?" (everyday wording; cited answer from the
cash-advance and GSIS-loan observations), "What does 2023 Observation No. 5 say?" (direct lookup),
"What did COA say about Quezon City's budget?" (not covered), and "Which years did COA raise
problems with the City's bank account balances?" (cited answer naming each year).

## Deployment

Pull requests run `ruff check`, `ruff format --check`, `pytest` and `coa-explorer extract --check`
(`.github/workflows/ci.yml`). A merge to `main` then builds `build/coa.sqlite` from the committed
records, bakes it into the container image (`Dockerfile`, ADR-0002), pushes the image to Artifact
Registry and deploys it to Cloud Run in `us-central1`: runtime service account, scale to zero, at
most 2 instances, public. It finishes by asking the deployed URL a real question
(`coa-explorer smoke --url ...`), so a deploy that cannot answer fails the run.

GitHub Actions authenticates with Workload Identity Federation: no service-account key exists, in
the repository or in GitHub secrets. The workflow reads only the repository *variables* that
`scripts/setup-gcp.sh` sets (project, region, provider, service accounts, Artifact Registry
repository and the Gemini model names). Re-run the script after pulling this change: it is safe to
repeat, grants the deployer account Vertex AI access for the index build, and sets the model
variables. To switch the answer model without code changes, change the `GEMINI_ANSWER_MODEL`
variable and re-run the workflow (Actions, "CI/CD", Run workflow, on `main`).
