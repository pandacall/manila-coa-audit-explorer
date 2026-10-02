# OCR the scanned short documents with Document AI once, and commit the proofread text

The transmittal letters of 2020–2023 and every year's Management Responsibility statement are pictures of paper (ticket #10). Four are PDF scans without a usable text layer, CY 2020's letter is a scan whose text layer is unreliable, and CY 2021's "Word" letter is a single PNG inside a `.docx` (only its "Copy furnished" list is text). Only CY 2024's letter is native text.

`coa-explorer ocr` reads these with Document AI Enterprise OCR and writes `data/reviewed/<file name>.txt`, the same page-headed format the CY 2023 Auditor's Report's reviewed transcription already uses and that `pdf_reader` already loads. A person proofreads the file against the scan and commits it. `extract` and `index` read only the committed text, so they need no GCP access; `ocr` is never part of a normal run, and it refuses to replace an existing transcription without `--overwrite` because it may hold a reviewer's corrections (as ADR-0003 does for the AAPSI and APMT).

Document AI is used here, rather than Gemini as for the AAPSI/APMT tables (ADR-0003), because these are plain prose pages: the prototype's Document AI errors were letter confusions and lookalike characters in dense tables, and the proofreading step catches them. The OCR was in fact word-for-word right on all nine bodies; what proofreading removed was non-document ink (seals, stamps, signatures) and what it fixed was reading order and bullets.

## Consequences

- Each document is one section with one Citation: `CY 2023 AAR, Transmittal Letter, pp. 1-3`; `CY 2022 AAR, Part I, Management Responsibility for Financial Statements, p. 1`. Pages are the PDF's real pages.
- CY 2021's picture is page 1, and the text Word holds after it is page 2. That is derived, not read from a PDF (ADR-0001): a full-page picture leaves no room for text on its page.
- A scanned document with no committed transcription is an error naming `coa-explorer ocr`; the text layer is never silently used instead.
- The index codes are `TL` and `MR`. `MR` is kept apart from `I` (the Auditor's Report) although both sit in Part I, so a search for COA's opinion is not diluted by Management's own statement, which the answer engine is told to attribute to Management.
- Review by the project owner is still outstanding; `data/reviewed/README.md` says what was changed and where to look first.
