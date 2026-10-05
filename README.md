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

Reads each year's transmittal letter, Management Responsibility statement, Executive Summary,
Auditor's Report, Notes to Financial Statements, Part II (Audit Observations and Recommendations)
and Part III (Status of Implementation of Prior Years' Recommendations) under
`coa-audit-reports/` and writes committed, human-readable JSON to `data/extracted/`:
`executive_summary/<year>.json`, `auditors_report/<year>.json` (one record per section),
`transmittal_letter/<year>.json`, `management_responsibility/<year>.json` (one section each),
`notes/<year>.json` (one record per Note, cut into cited passages),
`part2/<year>.json`, `part3/<year>.json` (one record per Prior Years' Recommendation, with COA's
Status of Implementation, Management's action and the reason given), `financial/<year>.json` (see
below) and `link-report.json`. Re-running produces no diff. To check that the committed
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

### Notes to Financial Statements

Each Note ("Note 4 – Cash and Cash Equivalents") is one record, cut into passages of at most 1,800
characters on paragraph and table-row boundaries; each passage is a piece of the index with its own
Citation by Note and page ("CY 2023 AAR, Part I, Notes to Financial Statements, Note 4, p. 30").
Tables are written as markdown, and a table cut over several passages repeats its header row in
each. The Notes are Word for 2020-2023 and PDF for 2024 (all 5 years, 31 to 35 Notes each).

Pages are the ones COA prints (ADR-0004). Word's are derived from the saved layout, which follows
a document's restarts of its page numbering: the 2021 Notes restart at page 45 in their last
section, so pages 45 and 46 occur twice. The 2024 file begins part-way through the AAR, so its
first PDF page is cited as page 12. Derived Word pages can drift by a few pages over long tables:
the Notes end within 4 pages of where COA's table of contents puts the start of Part II (the 2024
PDF ends exactly one page before Part II). The PDF's tables are rebuilt from the column spacing of
its text layer, and a table without amounts in it (a list of lessees, say) is read as prose.

The CY 2023 Auditor's Report is a scan whose text layer is too garbled to cite ("Qualffled", "Section
7 4"), so its text comes from a reviewed transcription in `data/reviewed/` instead; see the README
there. `extract --reviewed <dir>` reads transcriptions from another folder.

Where a Word cell's paragraphs cannot be matched one-to-one with the recommendations in it, the
whole cell text is attached to each recommendation it covers and the column is named in the record's
`shared` list, so nothing is dropped and nothing is guessed.

### Transmittal letters and Management Responsibility statements (scanned)

```bash
uv run coa-explorer ocr   # explicit only: Document AI, a few cents, needs GCP access
```

These short documents are each one section, cited by their pages ("CY 2023 AAR, Transmittal Letter,
pp. 1-3"; "CY 2022 AAR, Part I, Management Responsibility for Financial Statements, p. 1"). All of
them but CY 2024's transmittal letter (a native-text PDF, read as it is) are pictures of paper: the
2022 and 2023 letters and every year's statement are PDF scans, CY 2020's letter is a scan with an
unreliable text layer, and CY 2021's letter is a picture inside a Word file. `ocr` reads them with
Document AI Enterprise OCR (`DOCUMENT_AI_LOCATION`, and the project's `OCR_PROCESSOR`) into
`data/reviewed/<file name>.txt`, one `=== page N ===` heading per page. The OCR is proofread against
the scan (stamps, seals and signatures out, bodies word for word) and committed; `extract` and
`index` read only that committed text and need no GCP access. `ocr` refuses to replace a
transcription unless you pass `--overwrite`, because it may hold a reviewer's corrections. Pages are
the PDF's real pages; the CY 2021 picture is page 1 and the "Copy furnished" list Word holds as text
is page 2 (derived, ADR-0001). See `data/reviewed/README.md` and ADR-0004.

### Financial Statements and Annexes

The two spreadsheets of each AAR (Part I's five statements and Part IV's Annexes) become long-format
lines in `financial/<year>.json`: one amount per line, with its statement (SFPo, SFPe, SCNAE, SCF,
SCBAA), where it is printed (Part I, or an Annex), its Fund, the headings above it, its line item,
its column and its Citation ("CY 2022 AAR, Part I, Statement of Financial Position, Cash and Cash
Equivalents"). Part I is for the City as a whole ("All Funds"); the Annexes give the General Fund,
the Special Education Fund and the Trust Fund too. The budget statement's columns are Original
budget, Final budget, Actual and COA's two difference columns; Part I's other statements also keep
the prior-year comparative column. Amounts are exact to the centavo, taken from the values Excel
last cached for each formula (a formula with no cached value stops the extraction).

A sheet is a statement because its title says so, not because of its name or position, so the
swapped Annex lettering of 2023 and the unprefixed sheet names of 2024 need no special cases. Hidden
working sheets (2022's `NFS`, `PPE`, `Restatement` ...) are never read; the record's
`ignored_sheets` lists them. Rows with an amount but no label (balance checks, scratch sums below a
table) are skipped. Line items are as COA printed them, typos included, and a label wrapped over two
rows is joined. The tests check that the Fund columns of every Annex add up to its Total column and
that each year's statement of financial position balances.

## Extracting the AAPSI and APMT (scanned)

The 2023 and 2024 AAPSI (Management's Action Plans and Reported Status) and APMT (COA's validation
of them, with COA's Status of Implementation) are scans. Gemini reads them page by page into the
table's columns (ADR-0003); this needs the same GCP access as `serve`, costs a few cents, and is
not part of `extract` or `extract --check`:

```bash
uv run coa-explorer extract-aapsi
```

It writes `aapsi/<year>.json` and `apmt/<year>.json` under `data/extracted/` (one block of rows per
Reference, each row cited to its real PDF page) and `monitoring-link-report.json`. Each page is read
twice; pages whose readings differ are listed in the record's `review_notes`. **Review the records
against the scans before committing them**, starting with those pages: Gemini normalises small
punctuation and, rarely, drops a phrase. The command will not overwrite existing records (which may
hold your corrections) without `--overwrite`. `coa-explorer links` prints how the AAPSI and APMT
references link to Part II, which are out of the collection and which are unmatched.

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
Summary, `I` Auditor's Report, `TL` transmittal letter, `MR` Management Responsibility statement,
`NOTES` Notes to Financial Statements, `II`, `III`, `AAPSI`, `APMT`) or observation number (a Note
number with `NOTES`), and with no year named returns
the newest year first. Open http://127.0.0.1:8000, ask a question
about Part II or about whether the City acted on COA's recommendations, and the page shows the
summary and key points, each with Citation chips in COA's format. A follow-up question also shows a
timeline: when the observation was raised and COA's Status of Implementation in each later AAR,
with Management's action kept apart and attributed. For 2023 and 2024 the timeline also shows
Management's Action Plan and Reported Status (AAPSI) and COA's validation (APMT) as separate,
attributed entries, and says where Management's Reported Status and COA's Status of Implementation
disagree; an answer can carry a "What the City said" section. Questions about amounts ("How much cash
did Manila have at the end of 2022?", "How did actual spending compare to budget in 2023?") go to the
`financial_lookup` tool, which returns the exact peso amount, by Fund where the Annexes give one,
cited to the statement and line item, and works out the difference between years itself; the model
never does the arithmetic. Where COA labelled a line differently in two years (an Annex's "Total
Cash" becomes "Total Cash and Cash Equivalents"), the model pairs the two lines and the
`financial_change` tool computes the difference. Each year's figure is the one printed in that
year's own AAR, so a later AAR that restated it is not reflected. The page loads React from a CDN, so it needs
internet.
The answer model is `GEMINI_ANSWER_MODEL`; change it in `.env` to compare models.

## Public-demo limits, logging and feedback

`serve` guards the app for a public demo and needs `FIRESTORE_DATABASE` (see `.env.example`); it
refuses to start without it rather than run unguarded. `serve --no-demo-limits` skips all of this,
and needs no Firestore.

- **Rate limit**: `HOURLY_LIMIT_PER_IP` questions an hour per visitor (default 10), keyed on a salted
  hash of the IP (`IP_HASH_SALT`; set the same value on every instance). The IP is only used for
  this counter and is never stored with a logged question.
- **Daily cap**: `DAILY_QUESTION_CAP` questions a day across all visitors (default 300, UTC days),
  counted in Firestore, so it is right across instances and restarts. Over either limit,
  `POST /api/ask` answers 429 with one `rate_limited` or `demo_limit` event and never calls the
  model. When capped, the page shows "Demo limit reached for today" with the example questions and
  their saved answers (`data/saved-answers.json`, regenerated against the real model with
  `uv run coa-explorer save-examples`). If Firestore can't be reached the demo fails closed (503).
- **Question log**: each question is logged to Firestore with its outcome, Citations, latency and
  token counts; no IP and no user ID. Records expire 30 days after the question
  (`scripts/setup-gcp.sh` creates the TTL policies). The final streamed event carries the logged
  `question_id`; a failed log write never costs the visitor their answer.
- **Feedback**: 👍/👎 on an answer is sent to `POST /api/feedback`
  (`{"question_id": "...", "rating": "up" | "down"}`) and stored on the logged question.

The page streams from `POST /api/ask` (`{"question": "...", "history": [...]}`), which returns
newline-delimited JSON: `status` events while the model searches, then one `answer` (with its
`timelines`, if any), `not_covered` or `error` event. A `not_covered` event has a `reason`
(`not_found`, or `out_of_scope` for a question about other cities, news or politics, which is
refused with a short explanation of what the app covers) and up to three `suggestions`: related
questions the reports can answer, or the example questions when the model offers none.
`GET /api/examples` gives the example questions the page shows.

## Conversation and languages

The page keeps the conversation and sends the last three exchanges with each question as
`history` (`[{"question": "...", "answer": "..."}]`, oldest first; an earlier answer is sent as
plain text with its Citations, at most 3,000 characters). The server passes them to the model so a
follow-up such as "What about 2022?" or "Did they fix it?" makes sense, and stores none of it: the
question log holds only the new question. Each follow-up runs its own searches, and its key points
can cite only what those searches returned, never the earlier answer. "New conversation" clears it.

Ask in English, Filipino or Taglish and the answer comes in the same language; the model searches
in English (the reports' language) and quotes COA's English words where precision matters.

Verified against real Gemini (2026-10-05) with a conversation: "Ano ang napansin ng COA tungkol sa
cash advances noong 2023?" (cited answer in Filipino, with COA's "Implemented" quoted), then "What
about 2022?" (searched cash advances in 2022 again; cited answer in English, from 2022's own
sources), "Sino ang mananalo sa susunod na eleksyon sa Quezon City?" (refused in Filipino, saying
what the app covers, with three suggested questions), one of those suggestions, and "Did they fix
it?" (COA's statuses for the 2021 cash-advance recommendations in 2022 and 2023).

Verified against real Gemini (2026-10-02) with: "What did COA observe about cash advances in
Manila?" (cited answer), "Did Manila comply with IPSAS 1 in its financial statements? Which years?"
(cited answer across 2022-2024), "What did COA say about Quezon City's budget?" (not covered), and a
Filipino question about 2023 Observation No. 5 (cited answer, but in English at the time; answers
now follow the question's language, see "Conversation and languages").

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

## Measuring quality

```bash
uv run coa-explorer eval                     # every approved item in data/eval/reference.json
uv run coa-explorer eval --limit 5           # the small subset CI runs on pull requests
uv run coa-explorer eval --answer-model gemini-3.8-flash --judge-model gemini-3.1-pro-preview
```

`eval` runs each **approved** reference item through the real answer engine and writes
`build/eval/results.json` (every score and every item's outcome, for machines) and
`build/eval/summary.md` (the same as tables, for people). It needs the index, the settings above and
`GEMINI_JUDGE_MODEL`; the answer and judge models come from `.env` and can be overridden per run
with `--answer-model` and `--judge-model`, so models are compared without code changes.

A reference item in `data/eval/reference.json` has an `id`, the `question`, its `language` (`en`,
`fil` or `taglish`), `question_type` (`observation`, `follow_up` or `financial`), the
`expected_citations` (COA's format) and `key_facts` a good answer states, an `unanswerable` flag
(then the app must refuse, and the item has neither citations nor facts) and an `approved` flag.
Agents draft items; the owner checks each against the AAR and sets `"approved": true`. Items
without it are never scored. The ten Part II items and two unanswerable ones there now are drafts:
their expected pages are the ones the index derives, so check them against the Word file (or COA's
own later citation in the next year's Part III) when approving.

Scores, pooled over items:

- **Retrieval hit rate**: answerable items for which the passages the model was shown include an
  expected source (same AAR year, Part and observation, any page).
- **Citation correctness**: expected Citations the answer cites (same source), out of all expected
  Citations. **Page drift** is reported apart: for sources cited correctly, how many pages the cited
  starting page is from the expected one (ADR-0001 makes pages best-effort, so this is measured, not
  assumed).
- **Faithfulness** and **key-fact coverage**: Gemini Pro judges, in one Vertex AI batch job over all
  answers, whether each key point is supported by the passages the answer cites and whether each
  key fact appears in the answer. A judge reply that can't be used is counted as `unjudged`, not as a pass.
- **Correct refusal**: unanswerable items the app refused. **False refusal**: answerable items it
  refused (they also score no Citations and no facts).

The judge runs as a batch job because it is cheaper and nobody waits on it; batch jobs exchange
files through Cloud Storage, so `EVAL_BATCH_BUCKET` must name a bucket (`scripts/setup-gcp.sh`
creates one, plus a separate CI evaluator account that may only call Vertex AI and use the
bucket, and sets the variables CI reads). Re-run the wizard once to get those.
`.github/workflows/eval.yml` runs the first five approved items on every pull request from this
repository and posts the summary on the run page; it reports and does not block the merge.
