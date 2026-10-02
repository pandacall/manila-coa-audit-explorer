# COA Audit Explorer

Plain-language, cited answers to questions about the Commission on Audit's (COA) Annual Audit Reports on the City of Manila, 2020–2024.

## Language

### The report

**Annual Audit Report (AAR)**:
COA's complete audit report on the City of Manila for one calendar year, delivered as a set of separate files.
_Avoid_: Audit, report (unqualified)

**Part**:
One of the four numbered divisions of an AAR: I (Audited Financial Statements), II (Audit Observations and Recommendations), III (Status of Implementation of Prior Years' Recommendations), IV (Annexes).

**Executive Summary**:
COA's front-matter overview of an AAR, numbered in lowercase Roman pages.

**Auditor's Report**:
COA's formal opinion on whether the Financial Statements are fairly presented.
_Avoid_: Audit opinion letter

**Transmittal Letter**:
COA's cover letter sending an AAR to the Mayor. It restates the opinion and, in most years, the significant observations; it is not part of any Part.
_Avoid_: Cover letter (the "Cover" file is a different, excluded document)

**Management Responsibility statement**:
The City's own Statement of Management's Responsibility for Financial Statements, signed by the City Accountant and the Mayor and carried in Part I. It is Management's words, never COA's.
_Avoid_: Management representation letter

**Management**:
The audited agency: the City Government of Manila, as COA addresses it. In plain-language answers, say "the City of Manila".
_Avoid_: LGU, the city (in document-facing contexts)

**Reviewed transcription**:
A person-proofread text of a scanned document, committed in place of the PDF's own unreliable text layer so that OCR errors never become cited facts.

### Observations

**Audit Observation**:
One numbered item in Part II describing a deficiency, non-compliance or weakness COA found. It is not a finding of fraud or wrongdoing.
_Avoid_: Finding, flag, issue, violation

**Recommendation**:
An action COA asks Management to take in response to an Audit Observation; one observation has one or more.

**Management Comment**:
Management's written response to an Audit Observation, as recorded in the AAR.
_Avoid_: Reply, defense

**Auditor's Rejoinder**:
COA's answer to a Management Comment, when it has one.

**Commendation**:
A positive acknowledgement COA lists in Part II; numbered like observations but not an Audit Observation.

### Follow-up across years

**Prior Years' Recommendation**:
A Recommendation from an earlier AAR whose follow-up is tracked in a later AAR's Part III.

**Status of Implementation**:
COA's assessment of a Prior Years' Recommendation: Implemented, Partially Implemented, or Not Implemented. This is the authoritative status; it comes from Part III or the APMT.
_Avoid_: Using it for Management's own claim (that is the Reported Status)

**Reported Status**:
The status Management claims for its own Action Plan in the AAPSI. Always attributed to Management and never merged with the Status of Implementation.

**Originating Observation**:
The Audit Observation, in an earlier AAR, that a Prior Years' Recommendation was first raised under. It may predate 2020 and so lie outside the collection.

**Reference**:
The first column of Part III's table, naming the earlier Audit Observation (AAR year, observation number, pages) that a block of rows follows up. COA's own word; it is not a Citation.

**Timeline**:
How one Originating Observation's Recommendations fared across the AARs: when it was raised (if in the collection), then, for each AAR, COA's Status of Implementation (from Part III or the APMT), each step with its own Citation. Management's own account (its action, and from the AAPSI its Action Plan and Reported Status) is shown apart and attributed. Where Management's Reported Status and COA's Status of Implementation disagree, the Timeline says so.

**Action Plan**:
Management's stated plan, owner and target date for addressing a Recommendation, as reported in the AAPSI.

**Disagreement**:
Where Management's Reported Status and COA's Status of Implementation for the same Recommendation differ, worded as "Management reported this as implemented; COA assessed it as partially implemented". Management's "Ongoing" has no Status of Implementation equivalent, so it is never a Disagreement.

**AAPSI**:
Agency Action Plan and Status of Implementation: Management's own report of its Action Plans and claimed progress.

**APMT**:
Action Plan Monitoring Tool: COA's validation of the AAPSI, adding COA's own Status of Implementation.

### Financial statements

**Financial Statements**:
The five statements in Part I: Financial Position (SFPo), Financial Performance (SFPe), Changes in Net Assets/Equity (SCNAE), Cash Flows (SCF), and Comparison of Budget and Actual Amounts (SCBAA).

**Notes to Financial Statements**:
Management's explanatory disclosures supporting the Financial Statements, part of Part I.

**Annex**:
A supporting schedule in Part IV, typically a statement broken down by fund.

**Fund**:
A separately accounted pool of City money: the General Fund (GF), the Special Education Fund (SEF) and the Trust Fund. Part I's statements are for the City as a whole ("All Funds"); an Annex breaks the same statement down by Fund and adds a Total column.

**Financial line**:
One amount from the Financial Statements or an Annex: its AAR year, statement, Fund, line item and column (the budget statement has Original budget, Final budget, Actual and COA's two difference columns). Amounts come from the spreadsheets and are never computed by the model; differences between years are computed by the `financial_lookup` tool.

**Figure**:
What `financial_lookup` returns for a line item in one AAR: one printed line of a statement for one Fund, with its amount in each column (so one Figure holds several Financial lines). It has an id the model cites and a Citation. Differences between years compare Figures like for like: the same statement, printed in the same place, for the same Fund.

### Answers

**Citation**:
A pointer from an answer to its source, written the way COA cites itself: AAR year, Part, Audit Observation number where applicable, and page — e.g. "CY 2023 AAR, Part II, Observation No. 5, p. 71", or for a Part III row, "CY 2023 AAR, Part III, CY 2022 Observation No. 3, p. 93" (the AAR whose Part III it is, then the Originating Observation it follows up), and for an AAPSI or APMT row, "CY 2023 APMT, CY 2022 Observation No. 3, p. 2" (the document, the Originating Observation, and the page of the scanned PDF, which prints none of its own).
For the Executive Summary the exact anchor is its section letter and the page is a Roman numeral, "CY 2023 AAR, Executive Summary, Section E, p. iii"; for the Auditor's Report, which sits in Part I, "CY 2022 AAR, Part I, Auditor's Report, pp. 2-3".
For a Financial line it names the statement and the line item, with the Annex where the line comes from an Annex and the headings above it when the line item is printed more than once: "CY 2022 AAR, Part I, Statement of Financial Position, Cash and Cash Equivalents", "CY 2024 AAR, Part IV, Annex A, Statement of Financial Position, Total Cash and Cash Equivalents". Spreadsheets have no page numbers, so there is none.
_Avoid_: source link (and "Reference", which is Part III's column)
