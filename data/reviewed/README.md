# Reviewed transcriptions

Text of scanned PDFs, committed in place of the PDF's own text layer. `coa-explorer extract` reads
`data/reviewed/<pdf file name without .pdf>.txt` instead of the PDF whenever one exists; the file
has one `=== page N ===` heading per PDF page, and must have exactly as many pages as the PDF.
Printed page numbers are left out (the page headings carry them).

| File | Replaces the text layer of | Why |
| --- | --- | --- |
| `05-ManilaCity2023_Part1-Auditor's_Report.txt` | `coa-audit-reports/Manila-City-Annual-Audit-Report-2023/AAR/05-ManilaCity2023_Part1-Auditor's_Report.pdf` | The PDF is a scan; its embedded text is a poor OCR ("Qualffled Opinion", "Section 7 4 of Presidential Decree", "P4.577 blJllon") that cannot be cited. |

## Review status

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
