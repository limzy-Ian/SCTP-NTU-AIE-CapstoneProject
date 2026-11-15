# Eval re-baseline

The 69 catalogue cases (`evals/cases.yaml`) and the 20 manager cases (`evals/manager_cases.yaml`) were ported from the RAG_Capstone reference.

## Rule

Expected values come from the data as it really is, never from this repo's OCR errors.

- Nameplate and incident-form values come from the team's checked reference readings (`data/extraction/06_images_extraction.csv`, git-ignored client data; nothing from it is copied here).
- CMMS, sensor, spares and SOP values come from MySQL, the spares workbook and the SOP text.
- When this repo's OCR reads a value wrongly, the case keeps the true value and fails. The runner labels the failure "OCR data error, fix via OCR Review" when `scripts/ocr_accuracy_report.py` finds one of the case's `ocr_fields` wrong. The fix is to correct the reading in the app's OCR Review tab, not to change the case.

Only machine IDs, part numbers, report and work-order IDs, counts and similar values are frozen in the case files. No names and no free text from incident forms.

## Correction (Phase 5 review)

A first version of this file re-baselined N4, N6, N10 and V2 to match this repo's OCR or its missing features. That was wrong and has been reverted:

| Case | Wrong re-baseline (reverted) | Now |
|---|---|---|
| N4 | expected the OCR's misread grease interval | reference value; fails as an OCR data error (CNC-02 grease interval) |
| N6 | dropped CNC-01 and CRN-02 from the VG32 list | reference list of five machines |
| N10 | expected `conflict` because the OCR misreads the CRN-02 capacity | reference `answer` (plate and SOP agree); fails as an OCR data error (CRN-02 capacity) |
| V2 | expected `abstain` because there was no day/night split | reference `answer`; the pipeline now has a day/night sensor source (shift hours assumed, see below) and the case passes |

## Format changes that apply to every case

| Change | Reason |
|---|---|
| `tools:` and `flags_in:` removed | They drive the reference's free `tools` mode. This repo's no-model mode is `--mode retrieval`, which runs the real pipeline on live data. |
| `restart: true` removed from M3 | Restart persistence is a Phase 6 task here. M3 still runs as two turns. |
| `must_cite` IDs translated to `source_type:title fragment` | The reference used its own evidence IDs; the intent is kept. `img:nameplate_X.jpg` became `nameplate:X|processed_nameplate:X|processed_ocr_text:X`, `critical_spare_machines:HYD-32:ALL` became `tabular:HYD-32`, `cmms_safety_incidents:917` became `incident:Incident 917`, `sop:SOP-…` became `document:SOP-…`, `sensor_agg:CNC-02` became `sensor_trend_monthly:CNC-02|sensor_summary:CNC-02`. Affected: N1, N2, N3, N4, I7, V1, P1–P6, X2, Q10, Q18. |
| `ocr_fields:` added to N1–N10, S7, I7, I11, X2, M2, M3 | Names the nameplate or form fields the expected value comes from, so an OCR error is labelled. |
| outcome `clarify` allowed | Plan section 5.3 (used by Q7 and the added case A7). |

## Checked against the reference readings and unchanged

Every nameplate and incident case was re-checked against the reference readings: N1–N10, S7, M2, M3, X2 and manager Q14 (lubricants, grease intervals, serial and year, capacities), and I7, I8, I11, I12, I14 (incident forms). Every reference value agrees with the checked readings. No nameplate or incident case differs from the reference.

The other cases were checked against MySQL, the workbook and the SOPs and also agree: I1–I6, I9, I10, I13, W1–W6, S1–S6, V1, V3–V9, P1–P8, X1, X3, X4, G1–G8, M1 and the manager values Q4 (16 in 2026) and Q8 (34 in 2025).

## Cases added (not in the reference)

`evals/added_cases.yaml` holds 8 main-set cases (A1–A8) for fixes made in Phase 5: relative years (A14), ordering questions read as spares questions, "the crane sling" not being an ambiguous machine, and the day/night split. The manager cases are unchanged.

## Assumptions behind the new day/night split

Day is 07:00–18:59 and night is 19:00–06:59, Singapore time (UTC+8). The CMMS does not record shift times; the source text says the hours are assumed.

## Cases dropped

None.
