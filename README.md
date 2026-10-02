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

## Extracting Part II

```bash
uv run coa-explorer extract
```

Reads each year's Part II (Audit Observations and Recommendations) Word file under
`coa-audit-reports/` and writes one committed, human-readable JSON file per year to
`data/extracted/part2/`. Re-running produces no diff. To check that the committed records are
current without writing anything (exit code 1 if they are stale):

```bash
uv run coa-explorer extract --check
```

## Asking questions locally

Needs the settings from `scripts/setup-gcp.sh` in `.env` (`GCP_PROJECT_ID`, `GEMINI_LOCATION`,
`GEMINI_ANSWER_MODEL`; see `.env.example`) and Application Default Credentials
(`gcloud auth application-default login`). No API keys are used.

```bash
uv run coa-explorer index   # builds build/coa.sqlite from data/extracted/part2/ (git-ignored)
uv run coa-explorer serve   # http://127.0.0.1:8000
```

`index` needs no GCP access; rebuild it whenever the extracted records change. Open
http://127.0.0.1:8000, ask a question about Part II, and the page shows the summary and key points,
each with Citation chips in COA's format. The page loads React from a CDN, so it needs internet.
The answer model is `GEMINI_ANSWER_MODEL`; change it in `.env` to compare models.

The page streams from `POST /api/ask` (`{"question": "..."}`), which returns newline-delimited
JSON: `status` events while the model searches, then one `answer`, `not_covered` or `error` event.

Verified against real Gemini (2026-10-02) with: "What did COA observe about cash advances in
Manila?" (cited answer), "Did Manila comply with IPSAS 1 in its financial statements? Which years?"
(cited answer across 2022-2024), "What did COA say about Quezon City's budget?" (not covered), and a
Filipino question about 2023 Observation No. 5 (cited answer, but in English; answering in the
question's language is a later ticket).
