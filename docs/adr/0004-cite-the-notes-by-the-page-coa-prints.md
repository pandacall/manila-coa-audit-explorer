# Cite the Notes by the page COA prints, restarts and all

The Notes to Financial Statements are the first long, table-heavy Word documents we cite (Notes 3 and 10 alone run to dozens of pages), and they showed that ADR-0001's page derivation counted too many pages wherever Word saved a page break more than once for the same break:

- A table row whose cells each hold part of the row's text gets a saved break in every cell the break falls in. Counting each cell added a page per cell: 2021's Note 4 came out on page 37, not 34.
- Word also saves a break at the top of a section's first paragraph, which is the break the section itself made. Counting both added a page to every landscape table, and moved 2021's first paragraph after its restart to page 46 instead of 45.

Both are now counted once. Checked against the pages COA's 2024 AAPSI and APMT cite for Part II, the derived pages' drift went from mostly +1 to mostly 0. This also changed some Part II 2024 and Part III citations, which were regenerated.

We cite a Note by its number and the page COA prints, following Word's page-number restarts. The 2021 Notes restart at page 45 in their last section, straight after a landscape table that is itself on pages 45–46, so Word prints pages 45 and 46 twice; a citation there is ambiguous by page and exact by Note number, which is the anchor (ADR-0001). The 2024 Notes are a PDF cut from the middle of the AAR, so its first PDF page is cited as page 12, as printed, and not as page 1: the Notes then end on page 76 and Part II 2024 begins on page 77.

## Consequences

- Derived Word pages still drift: the Notes end within 4 pages of where COA's table of contents puts the start of Part II (the table of contents is the only independent check there is for those pages). Page accuracy is measured in the evaluation set, not assumed.
- A Note is cited by its passage's own pages, not the whole Note's, so a long Note's citations point at the part that was quoted.
- The Notes are indexed as part `NOTES`, with the Note number as the piece's `observation_number`; `search` only reads that number as a Note number when `parts` asks for the Notes.
