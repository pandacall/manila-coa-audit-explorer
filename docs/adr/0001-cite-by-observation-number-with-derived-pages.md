# Cite by observation number, with pages derived from Word's last layout

Most AAR parts are .docx, which have no fixed pages, and no faithful renderer is available (LibreOffice is absent and paginates differently from Word; Word automation failed). We cite the way COA cites itself — AAR year, Part, Audit Observation number, page — treating the observation number as the exact anchor and the page as a best-effort pointer. Pages are derived from each section's `w:pgNumType w:start` plus the `w:lastRenderedPageBreak` markers Word saved; checked against COA's own later citations this is exact for 2020–2022 and within ±2 pages for 2023–2024. Native PDFs use their real page numbers.

## Consequences

- Page accuracy is measured in the evaluation set rather than assumed.
- Re-saving a .docx in a different Word version can shift the saved breaks; treat the committed files as the source of truth.
