# Reviewed transcriptions

Text of scanned PDFs, committed in place of the PDF's own text layer. `coa-explorer extract` reads
`data/reviewed/<pdf file name without .pdf>.txt` instead of the PDF whenever one exists; the file
has one `=== page N ===` heading per PDF page, and must have exactly as many pages as the PDF.
Printed page numbers are left out (the page headings carry them).

| File | Replaces the text layer of | Why |
| --- | --- | --- |
| `01-ManilaCity2020_Transmittal_Letter.txt` | `.../2020/01-ManilaCity2020_Transmittal_Letter.pdf` | A scan; its text layer is unreliable ("DOMAGOS0", "Part 11", stamp noise). |
| `01-ManilaCity2021_Transmittal_Letter.txt` | the picture inside `.../2021/01-ManilaCity2021_Transmittal_Letter.docx` | The "Word" letter is a 473 x 663 px PNG; only its "Copy furnished" list is text, and Word supplies that. |
| `01-ManilaCity2022_Transmittal_Letter.txt` | `.../2022/01-ManilaCity2022_Transmittal_Letter.pdf` | A scan with no text layer. |
| `01-ManilaCity2023_Transmittal_Letter.txt` | `.../2023/AAR/01-ManilaCity2023_Transmittal_Letter.pdf` | A scan with no text layer. |
| `06-ManilaCity{2020..2024}_Part1-Mgmt_Responsibility_for_FS.txt` | each year's `06-...Mgmt_Responsibility_for_FS.pdf` | Scans with no text layer (CY 2021's has only the "CamScanner" watermark). |
| `05-ManilaCity2023_Part1-Auditor's_Report.txt` | `coa-audit-reports/Manila-City-Annual-Audit-Report-2023/AAR/05-ManilaCity2023_Part1-Auditor's_Report.pdf` | The PDF is a scan; its embedded text is a poor OCR ("Qualffled Opinion", "Section 7 4 of Presidential Decree", "P4.577 blJllon") that cannot be cited. |

## Review status

### Transmittal letters and Management Responsibility statements

Read by Document AI Enterprise OCR (`coa-explorer ocr`, the project's `OCR_PROCESSOR` in `us`,
2026-10-02), then proofread line by line against 200 dpi renders of every page by Claude on the same
day. **They have not yet been proofread by the project owner**; do that before relying on them,
especially the amounts, dates, section numbers and names in the letters (CY 2022: P32.595 million,
P11.388 billion, P5.941 billion, P4.791 billion; CY 2023: P472.415 million, P3,336,539.51, 1,130 and
452 RPUs) and the signatories.

What the proofreading changed, so a reviewer knows where to look: the OCR body text of all nine
documents matched the scans word for word and was kept. Removed as not part of the document: the
City seal's lettering, "BAGONG PILIPINAS" and the CamScanner watermark, received-stamps and their
handwriting, and signature strokes the OCR read as text ("CARMINA PAULITA" once, stray symbols).
Fixed: the reading order of the CY 2021 letter (the OCR started with the date; the page starts with
the letterhead) and the CY 2020 signature block; the bullets of the CY 2023 letter (the OCR
separated each bullet from its text); "RPUS" to "RPUs"; "above-" and "mentioned" split over a line
(now one word); a doubled "MD, FPDS"; and the mayor's nickname quotes (the OCR dropped or mis-marked
some: "ISKO MORENO" and "HONEY" are in curly double quotes as printed). Apostrophes are straight
throughout, as the OCR gives them; the scans mix straight and curly. Not transcribed: letterhead
artwork, stamps, handwriting and signatures.

### CY 2023 Auditor's Report

The CY 2023 Auditor's Report was transcribed from the page images (extracted from the PDF at
1225 x 1755 px) and proofread line by line against them on 2026-10-02, by Claude. **It has not yet
been proofread by the project owner**; do that before relying on it, especially the amounts
(P9.237 billion, P106.634 million, P182.123 million, P4.577 billion, P525.085 million), the legal
citations (Section 74 of PD No. 1445, Paragraph 27 of IPSAS 1) and the dates (April 24, 2023 and
May 6, 2024). The signatory's surname is partly covered by the signature on the scan; "ISIP" is
read from the visible letters and matches the CY 2024 Auditor's Report, which names the same
Supervising Auditor.

Change a transcription, run `uv run coa-explorer extract`, and commit the regenerated
`data/extracted/auditors_report/2023.json` with it; `extract --check` fails otherwise.
