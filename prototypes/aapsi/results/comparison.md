# AAPSI extraction: cell-by-cell comparison

| Page | Engine | Cells exact | Char errors / chars | Rows read/scan | Lookalike chars | Tokens in/out/think | Cost |
| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |
| 2023_AAPSI_p02 | gemini-3.1-pro-preview | 38/40 | 2/2083 | 4/4 | 0 | 1711/948/3939 | $0.0621 |
| 2023_AAPSI_p02 | gemini-3.8-flash | 39/40 | 1/2083 | 4/4 | 0 | 1711/761/1852 | $0.0111 |
| 2023_AAPSI_p02 | gemini-3.8-flash_think-low | 38/40 | 3/2083 | 4/4 | 0 | 1711/761/0 | $0.0041 |
| 2023_AAPSI_p02 | document-ai-ocr | 31/40 | 16/2083 | n/a | 3 | n/a | $0.0015 |
| 2023_AAPSI_p06 | gemini-3.1-pro-preview | 48/50 | 2/2054 | 5/5 | 0 | 1711/903/0 | $0.0143 |
| 2023_AAPSI_p06 | gemini-3.8-flash | 47/50 | 4/2054 | 5/5 | 0 | 1711/814/20623 | $0.0817 |
| 2023_AAPSI_p06 | gemini-3.8-flash_think-low | 48/50 | 3/2054 | 5/5 | 0 | 1711/813/0 | $0.0043 |
| 2023_AAPSI_p06 | document-ai-ocr | 37/50 | 27/2054 | n/a | 2 | n/a | $0.0015 |
| 2024_AAPSI_p03 | gemini-3.1-pro-preview | 30/30 | 0/2025 | 3/3 | 0 | 1716/798/3159 | $0.0509 |
| 2024_AAPSI_p03 | gemini-3.8-flash | 30/30 | 0/2025 | 3/3 | 0 | 1716/798/1944 | $0.0116 |
| 2024_AAPSI_p03 | gemini-3.8-flash_think-low | 30/30 | 0/2025 | 3/3 | 0 | 1716/661/0 | $0.0038 |
| 2024_AAPSI_p03 | document-ai-ocr | 29/30 | 1/2025 | n/a | 0 | n/a | $0.0015 |


## 2023 AAPSI, PDF page 2

_Model draft proofread line by line against 230-dpi crops of the scan; Observations 'CiB' confirmed against Part II Word text. i/l/I glyphs are ambiguous in this font._

### Gemini `gemini-3.1-pro-preview`
4 rows read, 4 in the scan; 1711 in / 948 out / 3939 thinking tokens, 32.0 s, $0.0621.

| Column | Cells | Exact | Mean CER |
| --- | ---: | ---: | ---: |
| reference | 4 | 4 | 0.000 |
| observations | 4 | 3 | 0.001 |
| recommendations | 4 | 4 | 0.000 |
| action_plan | 4 | 4 | 0.000 |
| person_responsible | 4 | 4 | 0.000 |
| target_from | 4 | 4 | 0.000 |
| target_to | 4 | 4 | 0.000 |
| status | 4 | 4 | 0.000 |
| reason_for_delay | 4 | 4 | 0.000 |
| action_taken | 4 | 3 | 0.004 |
| **all** | 40 | 38 | 0.000 | (missing rows 0, extra rows 0)

- row 1 `action_taken` CER 0.02
  - scan: …econciliationStatementsfortheCiBAccountsaffected
  - read: …econciliationStatementsfortheCIBAccountsaffected
- row 1 `observations` CER 0.00
  - scan: …TheaccuracyoftheCash-in-Bank(CiB)accountsbalanceasofDecember3
  - read: …TheaccuracyoftheCash-in-Bank(CIB)accountsbalanceasofDecember3

### Gemini `gemini-3.8-flash`
4 rows read, 4 in the scan; 1711 in / 761 out / 1852 thinking tokens, 18.5 s, $0.0111.

| Column | Cells | Exact | Mean CER |
| --- | ---: | ---: | ---: |
| reference | 4 | 4 | 0.000 |
| observations | 4 | 4 | 0.000 |
| recommendations | 4 | 4 | 0.000 |
| action_plan | 4 | 4 | 0.000 |
| person_responsible | 4 | 4 | 0.000 |
| target_from | 4 | 4 | 0.000 |
| target_to | 4 | 4 | 0.000 |
| status | 4 | 4 | 0.000 |
| reason_for_delay | 4 | 4 | 0.000 |
| action_taken | 4 | 3 | 0.004 |
| **all** | 40 | 39 | 0.000 | (missing rows 0, extra rows 0)

- row 1 `action_taken` CER 0.02
  - scan: …econciliationStatementsfortheCiBAccountsaffected
  - read: …econciliationStatementsfortheCIBAccountsaffected

### Gemini `gemini-3.8-flash_think-low`
4 rows read, 4 in the scan; 1711 in / 761 out / 0 thinking tokens, 5.9 s, $0.0041.

| Column | Cells | Exact | Mean CER |
| --- | ---: | ---: | ---: |
| reference | 4 | 4 | 0.000 |
| observations | 4 | 3 | 0.001 |
| recommendations | 4 | 4 | 0.000 |
| action_plan | 4 | 4 | 0.000 |
| person_responsible | 4 | 4 | 0.000 |
| target_from | 4 | 4 | 0.000 |
| target_to | 4 | 4 | 0.000 |
| status | 4 | 4 | 0.000 |
| reason_for_delay | 4 | 4 | 0.000 |
| action_taken | 4 | 3 | 0.004 |
| **all** | 40 | 38 | 0.000 | (missing rows 0, extra rows 0)

- row 1 `action_taken` CER 0.02
  - scan: …econciliationStatementsfortheCiBAccountsaffected
  - read: …econciliationStatementsfortheCIBAccountsaffected
- row 1 `observations` CER 0.00
  - scan: …TheaccuracyoftheCash-in-Bank(CiB)accountsbalanceasofDecember3
  - read: …TheaccuracyoftheCash-in-Bank(CIB)accountsbalanceasofDecember3

### Document AI Enterprise OCR
484 words, image quality 0.99, $0.0015/page, words bucketed into the truth grid.

| Column | Cells | Exact | Mean CER |
| --- | ---: | ---: | ---: |
| reference | 4 | 4 | 0.000 |
| observations | 4 | 2 | 0.002 |
| recommendations | 4 | 2 | 0.004 |
| action_plan | 4 | 4 | 0.000 |
| person_responsible | 4 | 2 | 0.075 |
| target_from | 4 | 4 | 0.000 |
| target_to | 4 | 4 | 0.000 |
| status | 4 | 4 | 0.000 |
| reason_for_delay | 4 | 4 | 0.000 |
| action_taken | 4 | 1 | 0.015 |
| **all** | 40 | 31 | 0.010 | (missing rows 0, extra rows 0)

- row 2 `person_responsible` CER 0.20
  - scan: …OCATandCTO
  - read: …OCATandCТО
- row 1 `person_responsible` CER 0.10
  - scan: …OCATandCTO
  - read: …OCATandCTО
- row 1 `action_taken` CER 0.03
  - scan: …SubmittedtheBankReconciliationStatementsfortheCiBAccoun
  - read: …SubmittedtheBankReconcillationStatementsfortheCIBAccoun
- row 4 `action_taken` CER 0.02
  - scan: …erlyaccountthepayablesperSupplier.Theamountofthevarianceisalr
  - read: …erlyaccountthepayablesperSuppller.Theamountofthevarlanceisalr
- row 1 `recommendations` CER 0.01
  - scan: …ndtheCTO:1.7.1.Reconcilethevariancesbetweenthebalancesperbank
  - read: …ndtheCTO:1.7.1.Reconcilethevarlancesbetweenthebalancesperbank
- row 3 `action_taken` CER 0.01
  - scan: …TheOCATandCTOiscurrentlyimplementingadocumenttrackingsy
  - read: …TheOCATandCTOiscurrentlyImplementingadocumenttrackingsy
- row 1 `observations` CER 0.01
  - scan: …1.TheaccuracyoftheCash-in-Bank(CiB)accountsbalanceasof
  - read: …1.TheaccuracyoftheCash-In-Bank(CiB)accountsbalanceasof
- row 3 `recommendations` CER 0.01
  - scan: …1.7.3.Formulateadocumenttrackingsyst
  - read: …1.7.3,Formulateadocumenttrackingsyst

## 2023 AAPSI, PDF page 6

_Transcribed independently (not from model output) from 220-dpi crops of the scan. Keeps the scan's own typos ('Pparagraph', 'Section. 7'). Reference column mixes prior-year references. Target-date cells are blank._

### Gemini `gemini-3.1-pro-preview`
5 rows read, 5 in the scan; 1711 in / 903 out / 0 thinking tokens, 10.9 s, $0.0143.

| Column | Cells | Exact | Mean CER |
| --- | ---: | ---: | ---: |
| reference | 5 | 5 | 0.000 |
| observations | 5 | 5 | 0.000 |
| recommendations | 5 | 4 | 0.001 |
| action_plan | 5 | 5 | 0.000 |
| person_responsible | 5 | 5 | 0.000 |
| target_from | 5 | 5 | 0.000 |
| target_to | 5 | 5 | 0.000 |
| status | 5 | 5 | 0.000 |
| reason_for_delay | 5 | 4 | 0.001 |
| action_taken | 5 | 5 | 0.000 |
| **all** | 50 | 48 | 0.000 | (missing rows 0, extra rows 0)

- row 3 `reason_for_delay` CER 0.01
  - scan: …etailsandinformation(forClarifitems)forGSIS.Ontheotherhandthe
  - read: …etailsandinformation(forClarifItems)forGSIS.Ontheotherhandthe
- row 1 `recommendations` CER 0.00
  - scan: …TeaminaccordancewithPparagraph,3.1.1ofDILG-MCNo.2014-135andSe
  - read: …TeaminaccordancewithPparagraph.3.1.1ofDILG-MCNo.2014-135andSe

### Gemini `gemini-3.8-flash`
5 rows read, 5 in the scan; 1711 in / 814 out / 20623 thinking tokens, 147.2 s, $0.0817.

| Column | Cells | Exact | Mean CER |
| --- | ---: | ---: | ---: |
| reference | 5 | 5 | 0.000 |
| observations | 5 | 4 | 0.001 |
| recommendations | 5 | 3 | 0.003 |
| action_plan | 5 | 5 | 0.000 |
| person_responsible | 5 | 5 | 0.000 |
| target_from | 5 | 5 | 0.000 |
| target_to | 5 | 5 | 0.000 |
| status | 5 | 5 | 0.000 |
| reason_for_delay | 5 | 5 | 0.000 |
| action_taken | 5 | 5 | 0.000 |
| **all** | 50 | 47 | 0.000 | (missing rows 0, extra rows 0)

- row 1 `recommendations` CER 0.01
  - scan: …TeaminaccordancewithPparagraph,3.1.1ofDILG-MCNo.2014-135andSe
  - read: …TeaminaccordancewithPparagraph3.1.1ofDILG-MCNo.2014-135andSe
- row 2 `recommendations` CER 0.01
  - scan: …nowNTA)inaccordancewithSection.14ofRANo.9729.
  - read: …nowNTA)inaccordancewithSection14ofRANo.9729.
- row 1 `observations` CER 0.01
  - scan: …ct(RA)No.9729,otherwiseknownastheClimateChangeActof2009,asam
  - read: …ct(RA)No.9729,otherwiseknownas,theClimateChangeActof2009,asam

### Gemini `gemini-3.8-flash_think-low`
5 rows read, 5 in the scan; 1711 in / 813 out / 0 thinking tokens, 6.1 s, $0.0043.

| Column | Cells | Exact | Mean CER |
| --- | ---: | ---: | ---: |
| reference | 5 | 5 | 0.000 |
| observations | 5 | 5 | 0.000 |
| recommendations | 5 | 3 | 0.003 |
| action_plan | 5 | 5 | 0.000 |
| person_responsible | 5 | 5 | 0.000 |
| target_from | 5 | 5 | 0.000 |
| target_to | 5 | 5 | 0.000 |
| status | 5 | 5 | 0.000 |
| reason_for_delay | 5 | 5 | 0.000 |
| action_taken | 5 | 5 | 0.000 |
| **all** | 50 | 48 | 0.000 | (missing rows 0, extra rows 0)

- row 1 `recommendations` CER 0.01
  - scan: …TeaminaccordancewithPparagraph,3.1.1ofDILG-MCNo.2014-135andSe
  - read: …TeaminaccordancewithPparagraph3.1.1ofDILG-MCNo.2014-135andSe
- row 2 `recommendations` CER 0.01
  - scan: …nowNTA)inaccordancewithSection.14ofRANo.9729.
  - read: …nowNTA)inaccordancewithSection14ofRANo.9729.

### Document AI Enterprise OCR
496 words, image quality 0.99, $0.0015/page, words bucketed into the truth grid.

| Column | Cells | Exact | Mean CER |
| --- | ---: | ---: | ---: |
| reference | 5 | 4 | 0.006 |
| observations | 5 | 2 | 0.208 |
| recommendations | 5 | 0 | 0.010 |
| action_plan | 5 | 5 | 0.000 |
| person_responsible | 5 | 4 | 0.040 |
| target_from | 5 | 5 | 0.000 |
| target_to | 5 | 5 | 0.000 |
| status | 5 | 5 | 0.000 |
| reason_for_delay | 5 | 3 | 0.006 |
| action_taken | 5 | 4 | 0.005 |
| **all** | 50 | 37 | 0.027 | (missing rows 0, extra rows 0)

- row 5 `observations` CER 1.00
  - scan: …
  - read: …b
- row 3 `person_responsible` CER 0.20
  - scan: …OCATandCTO
  - read: …OCATandCТО
- row 4 `reference` CER 0.03
  - scan: …CY2021AAR,ObservationNo.4,Page83
  - read: …CY2021AAR,ObservatlonNo.4,Page83
- row 4 `observations` CER 0.02
  - scan: …cialassistance(FA)tobeneficiariesinCOVID-19lockdowntranslated
  - read: …cialassistance(FA)tobeneficiarlesInCOVID-19lockdowntranslated
- row 3 `action_taken` CER 0.02
  - scan: …TheOCATincoordinationwithCTOiscontinuo
  - read: …TheOCATIncoordinationwithCTOIscontinuo
- row 3 `reason_for_delay` CER 0.02
  - scan: …Issuesrelatedtoemployeesdetailsandinformation(forClarifitem
  - read: …IssuesrelatedtoemployeesdetallsandInformation(forClarifItem
- row 1 `observations` CER 0.02
  - scan: …PAsforLCCAPinCY2023,whichisnotinconsonancewithSection14ofRepu
  - read: …PAsforLCCAPinCY2023,whichisnotInconsonancewithSection14ofRepu
- row 5 `recommendations` CER 0.01
  - scan: …b.IncoordinationwiththeDSWD,sup
  - read: ….IncoordinationwiththeDSWD,sup

## 2024 AAPSI, PDF page 3

_Transcribed from 200-dpi crops of the scan. The merged right-hand cells on the first two bands continue from the previous page and are blank here; the third band is cut off by the page end._

### Gemini `gemini-3.1-pro-preview`
3 rows read, 3 in the scan; 1716 in / 798 out / 3159 thinking tokens, 28.8 s, $0.0509.

| Column | Cells | Exact | Mean CER |
| --- | ---: | ---: | ---: |
| reference | 3 | 3 | 0.000 |
| observations | 3 | 3 | 0.000 |
| recommendations | 3 | 3 | 0.000 |
| action_plan | 3 | 3 | 0.000 |
| person_responsible | 3 | 3 | 0.000 |
| target_from | 3 | 3 | 0.000 |
| target_to | 3 | 3 | 0.000 |
| status | 3 | 3 | 0.000 |
| reason_for_delay | 3 | 3 | 0.000 |
| action_taken | 3 | 3 | 0.000 |
| **all** | 30 | 30 | 0.000 | (missing rows 0, extra rows 0)


### Gemini `gemini-3.8-flash`
3 rows read, 3 in the scan; 1716 in / 798 out / 1944 thinking tokens, 18.4 s, $0.0116.

| Column | Cells | Exact | Mean CER |
| --- | ---: | ---: | ---: |
| reference | 3 | 3 | 0.000 |
| observations | 3 | 3 | 0.000 |
| recommendations | 3 | 3 | 0.000 |
| action_plan | 3 | 3 | 0.000 |
| person_responsible | 3 | 3 | 0.000 |
| target_from | 3 | 3 | 0.000 |
| target_to | 3 | 3 | 0.000 |
| status | 3 | 3 | 0.000 |
| reason_for_delay | 3 | 3 | 0.000 |
| action_taken | 3 | 3 | 0.000 |
| **all** | 30 | 30 | 0.000 | (missing rows 0, extra rows 0)


### Gemini `gemini-3.8-flash_think-low`
3 rows read, 3 in the scan; 1716 in / 661 out / 0 thinking tokens, 5.5 s, $0.0038.

| Column | Cells | Exact | Mean CER |
| --- | ---: | ---: | ---: |
| reference | 3 | 3 | 0.000 |
| observations | 3 | 3 | 0.000 |
| recommendations | 3 | 3 | 0.000 |
| action_plan | 3 | 3 | 0.000 |
| person_responsible | 3 | 3 | 0.000 |
| target_from | 3 | 3 | 0.000 |
| target_to | 3 | 3 | 0.000 |
| status | 3 | 3 | 0.000 |
| reason_for_delay | 3 | 3 | 0.000 |
| action_taken | 3 | 3 | 0.000 |
| **all** | 30 | 30 | 0.000 | (missing rows 0, extra rows 0)


### Document AI Enterprise OCR
473 words, image quality 0.99, $0.0015/page, words bucketed into the truth grid.

| Column | Cells | Exact | Mean CER |
| --- | ---: | ---: | ---: |
| reference | 3 | 3 | 0.000 |
| observations | 3 | 3 | 0.000 |
| recommendations | 3 | 2 | 0.001 |
| action_plan | 3 | 3 | 0.000 |
| person_responsible | 3 | 3 | 0.000 |
| target_from | 3 | 3 | 0.000 |
| target_to | 3 | 3 | 0.000 |
| status | 3 | 3 | 0.000 |
| reason_for_delay | 3 | 3 | 0.000 |
| action_taken | 3 | 3 | 0.000 |
| **all** | 30 | 29 | 0.000 | (missing rows 0, extra rows 0)

- row 3 `recommendations` CER 0.00
  - scan: …Managementrequire:a.TheOCATto:•MaintainSLsforallreceivableacc
  - read: …Managementrequire:a.TheOCATto:MaintainSLsforallreceivableacc
