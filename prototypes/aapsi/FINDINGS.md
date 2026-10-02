# AAPSI extraction prototype: findings and decision

Ticket #7. Question: can Gemini, reading the scanned AAPSI PDF directly, extract its landscape table
rows faithfully into the known column schema, or do we need Document AI Layout Parser as the
fallback?

## Decision

**Gemini structured extraction, Flash model, low thinking. No Layout Parser fallback.**

On three scanned pages, Flash with low thinking made 6 character errors in 6,162 characters
(0.10%; default thinking made 5); Document AI Enterprise OCR made 44 (0.71%) even after being
handed a perfect table grid. Gemini returned every
row of every page it was run on (32 pages, 2023 and 2024 AAPSI) with no omissions on the pages that
could be checked. Cost is about $0.004 and 5 seconds a page.

Conditions that belong in the production ticket (#8), each backed by something observed below:

1. **Run with low thinking.** Default thinking cost 5x as much ($0.56 vs $0.115 for the 32 pages,
   up to $0.08 and 147 s on one dense page) and was no more faithful (see the table).
2. **Don't trust row boundaries.** Where one observation has several Recommendations, the model
   chose different row splits on 2 of 32 pages between runs (2024 p8: 2 rows vs 1; p12: 1 vs 3), with
   the same text. Key records on the Recommendation number ("1.7.2", "2.9.1.1", "b.") and group by
   reference, rather than on the number of rows.
3. **Gemini normalises small things.** It silently dropped scan punctuation (`Section. 14` became
   `Section 14`, `Pparagraph, 3.1.1` lost its comma) and changed `CiB` to `CIB` in places. It kept
   the scan's real typo `Pparagraph`. This is harmless for search but means "exact source quote"
   from an AAPSI row is the scan as read, not verbatim; the human review step in the spec covers it.
4. **Keep Document AI, but as a cross-check, not the primary reader** (reasons below). A plain-text
   comparison is too noisy to use as a gate, so the check has to be column-aware (see "Cross-check").
5. **The low-thinking run once dropped a phrase** (2024 p13, "unremitted taxes from prior years and
   SLs with", 9 words) that the default run kept. One omission in 32 pages, silent, found only by
   diffing two runs and Document AI's text. Omission is the failure the review must be designed to
   catch.

## Method

- Pages sent one at a time as single-page PDFs (rotation flag intact: the 2023 pages carry a 180-degree
  rotation flag). Structured output with a 10-field row schema (the 9 columns, with Target Date split
  into From/To), `temperature=0`, high media resolution. Prompt and schema:
  [extract_gemini.py](extract_gemini.py).
- Document AI Enterprise OCR (`OCR_PROCESSOR`, `us`): [extract_docai.py](extract_docai.py). It
  returns words with positions, not cells, so its words are bucketed into the table grid
  ([compare.py](compare.py), `assign_tokens_to_cells`). The grid came from the truth file, which
  flatters Document AI: in practice it would have to find the table layout itself.
- Truth: three pages transcribed from 200-230 dpi crops of the scan ([truth/](truth/)):
  - 2023 p6: transcribed independently of any model. Dense, narrow columns, populated Reason and
    Action Taken cells, prior-year references, and scan typos. The hard page.
  - 2024 p3: transcribed independently. Merged cells continuing from the previous page and a row
    cut off by the page end.
  - 2023 p2: **seeded from the Flash output, then proofread** against the crops, so it flatters
    Gemini. Only two differences were found (`CiB`). Treat its Gemini numbers as an upper bound.
- Scoring: character error rate per cell after ignoring whitespace and bullet glyphs; numbers and
  punctuation count. Tests: [test_compare.py](test_compare.py).
- Whole-document runs on all 32 pages of the 2023 and 2024 AAPSI, cross-checked against the
  committed Part II records and against Document AI's text.

## Results on the three transcribed pages

| Page | Engine | Cells exact | Char errors / chars | Lookalike chars | Tokens in/out/thinking | Cost |
| --- | --- | ---: | ---: | ---: | --- | ---: |
| 2023 p6 | Flash, default | 47/50 | 4/2054 | 0 | 1711/814/20623 | $0.0817 |
| 2023 p6 | Flash, low thinking | 48/50 | 3/2054 | 0 | 1711/813/0 | $0.0043 |
| 2023 p6 | Pro | 48/50 | 2/2054 | 0 | 1711/903/0 | $0.0143 |
| 2023 p6 | Document AI OCR | 37/50 | 27/2054 | 2 | n/a | $0.0015 |
| 2024 p3 | Flash, default | 30/30 | 0/2025 | 0 | 1716/798/1944 | $0.0116 |
| 2024 p3 | Flash, low thinking | 30/30 | 0/2025 | 0 | 1716/661/0 | $0.0038 |
| 2024 p3 | Pro | 30/30 | 0/2025 | 0 | 1716/798/3159 | $0.0509 |
| 2024 p3 | Document AI OCR | 29/30 | 1/2025 | 0 | n/a | $0.0015 |
| 2023 p2 (seeded) | Flash, default | 39/40 | 1/2083 | 0 | 1711/761/1852 | $0.0111 |
| 2023 p2 (seeded) | Flash, low thinking | 38/40 | 3/2083 | 0 | 1711/761/0 | $0.0041 |
| 2023 p2 (seeded) | Pro | 38/40 | 2/2083 | 0 | 1711/948/3939 | $0.0621 |
| 2023 p2 (seeded) | Document AI OCR | 31/40 | 16/2083 | 3 | n/a | $0.0015 |

Full per-column tables and every differing cell: [results/comparison.md](results/comparison.md).

Row counts matched the scan for every Gemini run on all three pages (5/5, 3/3, 4/4).

### Failure modes

**Gemini**
- Silent normalisation of punctuation and letter case (point 3 above): every Gemini error on the
  three pages is of this kind (a dropped or added comma or full stop, `CiB` vs `CIB`). No wrong digits, no wrong peso amounts, no wrong item numbers, nothing
  moved to a neighbouring column.
- Row segmentation varies between runs on pages with several Recommendations per observation
  (point 2).
- Rare silent omission (point 5).
- Slow tail with default thinking: 20,623 thinking tokens and 147 s on the densest page.
- Pro was not more faithful than Flash on these pages and costs 3-15x as much as low-thinking Flash.

**Document AI Enterprise OCR**
- Emits non-Latin lookalikes: `CTO` came out as `CТО` with Cyrillic Te and O. Across all 32 pages
  (14,736 words) there are 33 Cyrillic and 3 Arabic characters, against none from Gemini. These
  break exact-term search ("CTO") invisibly.
- Confuses `i`/`l`/`I` in this scan's font (`Reconcillation`, `Suppller`, `Implementing`), and
  spaces out punctuation (`CiB ) ,`). The spacing was forgiven in the scoring; the letter errors were not.
- Gives words and boxes, not cells. One stray word from the neighbouring column landed in the wrong
  cell even with a perfect grid (2023 p6, the "b" of "b. In coordination").
- Drops list bullets.
- Its image-quality score is 0.95-0.99 on all 32 pages, so it does not flag the pages it reads badly.

**Layout Parser** (tried only to see whether the fallback would work, [layout_parser.py](layout_parser.py))
- Finds the table and its columns (it merges the From/To sub-columns into one) but returns one
  *row per printed line* of text, not per table row: 31, 33 and 21 rows for pages that have 5, 4
  and 3. Rows would need re-grouping afterwards, which is the hard part. Reads `Inconsonance` and
  `Is` with the same letter confusion. $10 per 1,000 pages, nearly 7x Enterprise OCR. Not worth
  choosing over Gemini on this evidence.

### Cross-check against Document AI's text

The spec has Document AI's OCR text check Gemini's rows. Two simple versions were tried
([completeness.py](completeness.py)):

- A bag of words (Document AI words missing from Gemini's cells, after tolerating near-misspellings
  and dropping page furniture) is clean, leaving only the cover letters and the sign-off page
  (130 words over 32 pages, nearly all on those), but **missed the 9-word omission** because those words occur elsewhere
  on the page.
- A check on runs of missing word triples **found** it, but flags ~170 stretches over 32 pages,
  because Document AI's reading order interleaves neighbouring columns. It is only useful as the
  *difference* between two runs: for the low-thinking run it isolates the p13 omission and a few
  cosmetic differences.

So the cross-check needs to be column-aware (assign Document AI words to columns by position, then
compare column by column) to work as a gate. That is design work for #8, not settled here.

## Cost per page

| | Per page | 32 pages (both AAPSIs) |
| --- | ---: | ---: |
| Flash, low thinking | $0.0036 (5.5 s) | $0.115 |
| Flash, default thinking | $0.0176 (29 s) | $0.562 |
| Document AI Enterprise OCR | $0.0015 | $0.048 |
| Document AI Layout Parser | $0.010 | $0.32 |

Pricing caveat: Google's own pricing pages would not load for me. The Gemini rates ($0.75 in /
$3.75 out per million tokens for 3.8 Flash; $2 / $12 for 3.1 Pro) come from third-party price
trackers, and the Document AI rates ($1.50 and $10 per 1,000 pages) from a search summary of
Google's published tiers. Token counts are in the results files so the figures can be re-priced.
Thinking tokens are billed as output.

The 2023-2024 AAPSI plus APMT is about 47 pages, so extraction is a few cents either way.

## What this means for other tickets

Found while cross-checking all 32 pages against the committed Part II records
([crosscheck.py](crosscheck.py)):

- **Reference parser (#6) must handle a second shape**: carried-over rows cite earlier AARs as
  `CY 2022 AAR, Observation No. 6, Page 81` (note: year first, "CY ... AAR"), as well as
  `AAR 2023 Observation No. 1 Page 79`. The AAPSI also numbers carried-over items in the
  observation text as if they were this year's ("7. The City has not remitted...") while the
  Reference column holds the *original* AAR year and number.
- Carried-over references resolved: `CY 2022 Obs 6 p.81` and `CY 2021 Obs 4 p.83` both match the
  page derived for those observations exactly (ADR-0001). `CY 2018 Obs 15/16` and `CY 2019 Obs 1`
  are before 2020, so out of collection and need to be reported, not matched.
- **2023 AAPSI cites pages 7-9 higher than the page derived from the Word file** for its own
  observations (Obs 1: cites p.79, derived p.71), and the scan does print "Page 79". The 2024 AAPSI
  agrees within 1 page for 23 of 26 observations, but not for Obs 18 (-4), 21 (-3) and 29 (-9; cites
  p.169, derived p.178), also as printed in the scan. Part III or the following year's citations are
  the reference ADR-0001 used; the AAPSI is a weaker check on page numbers.
- **The AAPSI is incomplete against Part II**: 2024 has no rows for Observations 22, 27 and 28 (the
  scan jumps 21 to 23, 26 to 29, confirmed by eye), and 2023 has none for Observation 7 (Part II
  gives it no Recommendation).
- **Reported Status is mostly blank for 2024**: 47 rows, no target dates, no Reason or Action Taken,
  and a status on only 3 rows (all carried-over, "Not Implemented"). The Action Plan text and
  Person Responsible are filled. 2023 has status on all 24 rows ("Ongoing" 16, "Fully Implemented"
  8) with dates on 18.
- The 2023 AAPSI has an empty Action Plan column on every row.
- Row counts: 24 rows for 2023 (Part II has 19 Recommendations; the rest are carried-over items)
  and 47 for 2024 (Part II has 132 Recommendations). Many 2024 rows hold all of an observation's
  Recommendations in one cell, so rows do not map one to one to Recommendations.
- The APMT was not run; it has COA's Status of Implementation columns and so a different schema.

## Limits of this prototype

- Three transcribed pages out of 32, one of them seeded from the model. The error rates are
  indicative, not a measured accuracy. A human should spot-check the committed output, as the spec
  already requires.
- The truth is one reader's transcription of low-resolution scans; `i`/`l`/`I` are often
  indistinguishable in this font, so a few of the "errors" on both engines could be the scan's.
- Gemini is not strictly deterministic even at temperature 0; two runs differed on 32 of 690 cells
  (mostly row splits).
- The low-thinking whole-document run was only compared with the default run and Document AI, not
  with a transcription.

## Reproducing

```bash
uv sync --group prototype
uv run --group prototype python -m prototypes.aapsi.extract_gemini 2023 AAPSI 6 --thinking LOW
uv run --group prototype python -m prototypes.aapsi.extract_docai 2023 AAPSI 6
uv run --group prototype python -m prototypes.aapsi.report            # results/comparison.md
uv run --group prototype python -m prototypes.aapsi.crosscheck gemini-3.8-flash_think-low
uv run --group prototype python -m prototypes.aapsi.completeness
uv run --group prototype pytest prototypes
```

Needs the `.env` from `scripts/setup-gcp.sh` and Application Default Credentials. The Document AI
processors (`coa-explorer-aapsi-ocr`, `coa-explorer-aapsi-layout`, location `us`) are created on
first use and left in the project; they cost nothing while idle.
