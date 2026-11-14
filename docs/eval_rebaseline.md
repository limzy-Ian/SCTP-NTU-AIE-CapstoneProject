# Eval re-baseline

The 69 catalogue cases (`evals/cases.yaml`) and the 20 manager cases (`evals/manager_cases.yaml`) were ported from the RAG_Capstone reference. Each expected value was checked against this repo's data: MySQL (`safety_incidents`, `work_orders`, `employees` codes only, sensor tables), the spares workbook, the SOP text, and the nameplate OCR (structured fields and raw OCR text). This file lists every case that differs from the reference, and why. Cases not listed here are unchanged.

Only machine IDs, part numbers, report and work-order IDs, counts and similar values are frozen in the case files. No names and no free text from incident forms.

## Format changes that apply to every case

| Change | Reason |
|---|---|
| `tools:` and `flags_in:` removed (N1, N5, N6, N8, N9, N10, S1–S5, S7, I1–I9, I11, I12, I14, W1–W4, W6, V1–V9, P3, P7, P8, G7) | They drive the reference's free `tools` mode, which calls its tool layer directly. This repo has no tool layer; its no-model mode is `--mode retrieval`, which runs the real pipeline with the live data and the deterministic template. |
| `restart: true` removed from M3 | The reference re-ran the last turn in a new process. Restart persistence is a Phase 6 task here (chat history in MySQL). M3 still runs as two turns. |
| `must_cite` IDs translated to `source_type:title fragment` | The reference used its own evidence IDs. The intent of each check is kept: `img:nameplate_X.jpg` became `nameplate:X|processed_nameplate:X|processed_ocr_text:X` (the plate's staging record, processed OCR or raw OCR text), `critical_spare_machines:HYD-32:ALL` became `tabular:HYD-32`, `cmms_safety_incidents:917` became `incident:Incident 917`, `sop:SOP-…` became `document:SOP-…`, `sensor_agg:CNC-02` became `sensor_trend_monthly:CNC-02|sensor_summary:CNC-02`. Affected: N1, N2, N3, N4, I7, V1, P1–P6, X2, Q10, Q18. |
| New outcome `clarify` allowed in `expect` | Plan section 5.3. Used by Q7 (unchanged from the reference). |

## Value and outcome changes

| Case | Reference | This repo | Why |
|---|---|---|---|
| N4 | `1000|1,000` (grease interval of CNC-02) | `1600`, plus `llm_include: unverified|OCR` | The reference read the plate with a vision model. This repo's Tesseract OCR reads "GREASE INTERVAL 1600 h" both in the structured field and in the raw OCR text. 1600 is probably a misread of 1000, but the data says 1600 and it is unverified. The case now checks that the app reports what its data holds and labels it unverified. |
| N6 | CNC-01, CNC-02, MILL-01, CRN-02, PMP-T01 use ISO VG32 | CNC-02, MILL-01, PMP-T01 | In this repo's OCR, CNC-01's plate reads "Is0 v632" (probably VG32, but not readable as a grade) and CRN-02's plate has no lubricant text at all. PMP-T01's structured field is empty, but its raw OCR text reads "UBRICANT IS0 VG32". |
| N10 | `answer` (SOP and plate agree on 2,000 kg) | `conflict`, must include `2,000` and `SOP-CRANE-02` | The CRN-02 plate OCR reads "2080 kg"; the SOP says 2,000 kg. The code reports the disagreement and trusts the SOP (controlled document). |
| V2 | `answer`, must include `4.4` (rise is the same day and night) | `abstain`, must include `shift` | The reference had a day/night split. This repo's sensor evidence is monthly aggregates only, so the app cannot say whether the change is limited to the night shift and says so. (The old check passed only by accident: 4.414 is the June monthly mean.) |

## Values checked and unchanged

These were re-derived from this repo's data and match the reference: N2 (CMP-01 grease 500 h, from the raw OCR text; the structured field is empty), N5 (BLAST-01, CMP-01, WELD-02 read Shell Tonna; CMP-01 only in the raw OCR text), N7 (MILL-01 serial and year in the OCR), M2 (CMP-01 Shell Tonna S3 M68, raw OCR text), I1 (4 worst-case on the normalised scale; 11 logged as 1 and 20 logged as 5 mix the scales), I2 (27 at normalised level 1), I3 (978 is the only worst-case incident in 2025), I4 (35, 34, 16 per year), I5 (CNC-01 has the most, 10), I6 (CNC-02 has 8), I8 (near misses with lost days: 902, 917, 944, 966), I9 (35 found during audit), I13 (latest incident 2026-06-18), I14 (30 incidents have a scanned form), I12 and Q13 (the crane SOP mentions an Aug 2025 sling near-miss; the 2 CMMS incidents in Aug 2025 are on CNC-01 and are not about slings), W1 (34 not closed), W2 (11550, 11572, 11591), W3 (11386, 11495, 11529), W4 (11237, 4,057.24), W6 (677, 647, 279), S1 (BRG-6310, SEAL-KIT-KSB, LS-CXT-11 below minimum), S3 (LS-CXT-11 out of stock), S6 (BRG-6310 costs 48; the workbook states no currency), V7 (five machines with sensors), V8 (largest gap 36 minutes), G7 (EMP015 and EMP026 are the one pair of codes that share a name; codes only), Q4 (16 incidents in 2026), Q8 (34 incidents in 2025).

## Cases dropped

None. No case depended only on something this repo deliberately does not have; the vision-model readings (N2, N5, M2) are available in this repo's raw OCR text.

## Expectations that were wrong in a first pass and restored

On the first pass N2 and M2 were re-baselined to `abstain` and N5 dropped CMP-01, because the structured OCR fields for CMP-01 are empty. The raw OCR text of the CMP-01 plate does hold "GREASE INTERVAL 500 h" and "Shell Tonna $3 M68" next to garbled labels, so the reference values are right for this repo too. The cases were restored and the pipeline now reads the raw OCR text when the structured field is empty.
