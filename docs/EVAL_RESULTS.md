# Eval results

Latest runs: 14 Nov 2026, branch `enhance/rag-hardening`. Counts only. Commands are in `evals/README.md`. Expected values for nameplate and incident cases are the team's checked readings; failures caused by this repo's OCR are labelled "OCR data error, fix via OCR Review".

## Offline (`--mode offline`)

Fixture corpus, scripted mock model. Offline cases 20/20, main-set refusals 7/7, manager refusal 1/1, legitimate questions 72/72, hostile prompts 40/40. Refusals 9/9 with no model call.

## Retrieval (`--mode retrieval`)

Live data, no model. `must_include` is checked against the template answer only. Main 64/69 (tier 1 29/29, tier 2 24/27, tier 3 11/13), added 8/8, manager 18/20, legitimate 72/72, hostile 40/40, refusals 8/8 with no model call. Cost USD 0.

Failures: N4, N6, N10 (OCR data error, fix via OCR Review), V8 and X4 (tier 3), manager Q3 and Q15.

## End to end (`--mode e2e`, gpt-4o-mini), Phase 5b

### Tier 1, once

Projected USD 0.0366 (1.3x for retries); actual USD 0.0413 (59 calls, 223,949 prompt + 12,853 completion tokens). Main 29/29, added 5/5, manager 10/11 (Q3 fails), refusals 4/4 with no model call.

### Full main, added and manager sets, once

Projected USD 0.0705; actual USD 0.0720 (109 calls, 398,628 prompt + 20,371 completion tokens).

| Set | Passed | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|---|
| main (69) | 62 | 28/29 | 23/27 (85%) | 11/13 |
| main without N4, N6, N10 (66) | 62 | 28/29 | 23/24 (96%) | 11/13 |
| added (8) | 8 | 5/5 | 3/3 | |
| manager (20) | 17 | 9/11 | 8/9 | |
| refusals | 8/8, no model call | | | |

| Case | Tier | Failure | Cause |
|---|---|---|---|
| N4, N6, N10 | 2 | wrong values | OCR data error, fix via OCR Review |
| W1 | 1 | no "30 Jun" | answer gives the data end as 2026-06-30; the check looks for "30 Jun" |
| V6 | 2 | no "30 Jun" | same date-format cause |
| V9 | 3 | no "Celsius" | answer says "°C"; code accepted it for the Celsius caveat |
| X4 | 3 | no "30 Jun" | cross-source question not implemented (table path) |
| Q1 | 1 (manager) | contains "is in good shape" | negated sentence ("does not support a conclusion that ... is in good shape") fails a substring check |
| Q3 | 1 (manager) | answer, not conflict | CNC-02 summary does not pick up the oil conflict |
| Q15 | 2 (manager) | no BLAST-01 | machines without sensors not listed |

### Spend

Phase 5b USD 0.1133. Total eval spend USD 0.2470 (`logs/spend.jsonl`, source "eval"), including 86 calls in Phase 5 that never reached the API and cost nothing.

## End to end, Phase 5c (tier 1, once)

Projected USD 0.0368 (1.3x for retries); actual USD 0.0399 (57 calls, 219,126 prompt + 11,749 completion tokens).

| Set | Passed |
|---|---|
| main tier 1 | 29/29 |
| added tier 1 | 5/5 |
| manager tier 1 | 10/11 |
| refusals | 4/4, no model call |

W1 now passes (the answer writes "30 Jun 2026"); manager Q1 now passes (no condition judgement). Remaining tier 1 failure: manager Q3 (CNC-02 summary has no oil conflict; pipeline gap). V3 passed on the template: the model's answer was rejected twice and code answered. Tier 2 and 3 cases (V6, V9) were not rerun.

Total eval spend: USD 0.2870.