# Read the scanned AAPSI and APMT with Gemini, and commit the rows only after human review

The 2023 and 2024 AAPSI and APMT are scanned landscape tables with no text layer. The ticket #7 prototype compared Gemini structured extraction with Document AI (OCR and Layout Parser) on the scans: Gemini Flash with low thinking made about one character error in a thousand, mostly dropped punctuation, while Document AI made seven times as many, emitted Cyrillic lookalike letters, and returned words rather than cells. So `coa-explorer extract-aapsi` has Gemini read one page at a time into the known column schema, and the rows are committed under `data/extracted/aapsi/` and `data/extracted/apmt/` as the source of truth, like the Word-derived records but not regenerable by `extract --check` (the model is not deterministic and costs money).

Two things were learned while building it, and are built in:

- **Send an image, not the PDF.** The small APMT print came back from the PDF with misread digits ("Page 78" for "Page 79") and reworded recommendations; the same page rendered at 200 dpi and sent as a PNG did not. On the prototype's three transcribed pages the image route made 3 and 4 character errors in 6,162 characters over two runs, against 6 for the PDF route.
- **Read every page twice.** A model can silently drop a phrase. Pages where the two readings differ in their words are listed in the record's `review_notes` for the reviewer to check first. This catches omissions; it does not prove the first reading right.

## Consequences

- Human review is part of the process, not a formality: `extract-aapsi` refuses to overwrite existing records without `--overwrite`, because they may hold a reviewer's corrections.
- Rows are cited to real PDF pages (`CY 2023 AAPSI, CY 2022 Observation No. 3, p. 4`), since the scans print no page numbers of their own.
- The model's row boundaries are not trusted (they vary between runs); a row is whatever the first reading returned, read by the recommendation numbers in its text.
- The APMT repeats the AAPSI's Management columns next to COA's validation, so a disagreement between Management's Reported Status and COA's Status of Implementation is judged within one APMT row, with no cross-document matching.
