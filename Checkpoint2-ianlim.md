# Checkpoint 2 - Ingestion and Retrieval

**Submission date:** Saturday 14 November 2026  
**Project:** Jurong Marine Services safety and maintenance assistant

## Checkpoint requirement

Demonstrate ingestion and retrieval working end-to-end on at least two source types, including scanned images, and show one answer with source citations.

## Implementation in the repository

- **Scanned images:** `scripts/nameplate_ocr_import.py` extracts nameplate fields; `scripts/ingest_incident_reports.py` processes incident-report scans. OCR review in the app keeps reviewer decisions and corrections separate from the original extraction.
- **Other sources:** `scripts/maintenance_rag.py` loads CMMS evidence from MySQL, SOP text files, critical-spares workbook rows, and processed OCR/sensor evidence.
- **Retrieval and citations:** `app.py` presents retrieved evidence with source IDs and locations. Service-history and incident-history requests also have structured table responses with per-row citations. The RAG layer applies asset filters and flags unverified OCR rather than treating it as confirmed.
- **Limits:** Sensor charts and aggregates are descriptive, not diagnoses. The assistant is read-only and does not authorize or modify maintenance work.

## Evidence verified

- Automated tests: **43 passed** with `.\.venv\Scripts\python.exe -m unittest discover -s tests`.
- The tests cover citation validation, source filtering and selection, workbook row citations, OCR parsing/review status, refusal behavior, and sensor-trend evidence handling.
- Current-tree audit: no raw client-data files are tracked; only `data/README.md` and an assets-directory placeholder are present in those locations. No common key-shaped literals or credential assignments were found in tracked files or reachable text history. Client-data and dotenv paths are ignored, while `.env.example` remains allowed.

**Git history follow-up:** earlier commits still contain evidence assets under `docs/project-plan/evidence/` and `docs/project-plan/proposals/assets/ianlim/`, although these files are absent from the current tree. The new ignore rules prevent accidental re-addition; they do not erase old commits. Purging those commits requires a coordinated history rewrite and force-push, which has not been performed.

**Important:** the automated suite does not prove that the local MySQL database and actual scanned client images have been ingested and exercised together. Complete the live evidence below before submitting.

## Live demonstration evidence — complete before submission

- [ ] Start MySQL and load the team database dump; confirm the expected source tables are available.
- [ ] Run the image OCR ingestion for at least one scanned image and inspect it in the OCR Review tab. Record whether the extracted fields are pending or human-reviewed.
- [ ] Run the app and ask a question whose answer requires a scanned-image source and at least one other source type.
- [ ] Paste the exact question, displayed answer, citation IDs, and source locations here. Include the scanned image's filename and the other source type; do not paste raw client data into this document.
- [ ] Verify every citation opens or identifies the evidence shown, and note any conflicts or uncertainty in the answer.
- [ ] Check API usage against the team's hard budget. Record the observed amount and where it was checked; do not record the API key.

### Demonstrated answer

- **Question:** _Add the exact question used during the live run._
- **Answer:** _Paste the answer shown by the app, retaining its citations._
- **Scanned-image source:** _Filename and citation ID._
- **Second source:** _Source type/location and citation ID._
- **Conflicts or review status:** _State any discrepancy, pending OCR review, or “none observed” only after checking._
- **API spend check:** _Amount, date checked, and measurement source; never include credentials._

## Pre-submission checks

- [ ] `.\.venv\Scripts\python.exe -m unittest discover -s tests` passes.
- [ ] The live two-source retrieval above includes a scanned image and visible citations.
- [ ] No client data, `.env` file, or API key is staged or committed; confirm with `git status` before pushing.
- [ ] Add any issues found during the live run to the data-quality report and the team's checkpoint notes.

## Scheduling note

The briefing handout describes a 10-minute live demo, while `CLIENT_BRIEF.md` and `CHECKPOINTS.md` describe a 5-minute demo. Confirm the final slot length with the instructor.