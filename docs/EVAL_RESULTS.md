# Eval results

Latest runs: 14 Nov 2026, branch `enhance/rag-hardening`. Counts only. Commands are in `evals/README.md`. Expected values for nameplate and incident cases are the team's checked readings; failures caused by this repo's OCR are labelled "OCR data error, fix via OCR Review".

## Offline (`--mode offline`)

Fixture corpus, scripted mock model. Offline cases 20/20, main-set refusals 7/7, manager refusal 1/1, legitimate questions 72/72, hostile prompts 40/40. Refusals 9/9 with no model call.

## Retrieval (`--mode retrieval`)

Live data, no model. Main 66/69 (tier 1 29/29, tier 2 25/27, tier 3 12/13), added 8/8, manager 18/20, legitimate 72/72, hostile 40/40, refusals 8/8 with no model call. Cost USD 0.

Failures: N4 and N10 (OCR data errors), X4 (tier 3), manager Q3 and Q15.

## End to end (`--mode e2e`, gpt-4o-mini)

### Tier 1, `--repeat 2`

Projected USD 0.055; actual USD 0.0697 (103 model calls including retries, 380,923 prompt + 20,979 completion tokens).

| Set | Passed |
|---|---|
| main tier 1 | 26/29 |
| added tier 1 | 4/5 |
| manager tier 1 | 9/11 |
| refusals | 4/4, no model call |

Failures: I1, I3, W1, A4 (main/added, gating), Q1, Q3 (manager). Every failed case failed the same way in both runs; no outcome changed between runs.

### Full main, added and manager sets, once

Projected USD 0.053; actual USD 0.0640 (100 model calls, 356,560 prompt + 17,554 completion tokens).

| Set | Passed | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|---|
| main (69) | 56 | 25/29 | 21/27 (78%, below the 90% target) | 10/13 |
| added (8) | 7 | 4/5 | 3/3 | |
| manager (20) | 16 | 9/11 | 7/9 | |
| refusals | 8/8, no model call | | | |

| Case | Tier | Failure | Kind |
|---|---|---|---|
| N4, N6, N10 | 2 | values from wrong OCR readings | OCR data error, fix via OCR Review |
| I1 | 1 | answer omits that the scale mapping is unconfirmed | model left out a computed caveat |
| I2 | 1 | answer omits the normalised counts (27, 11, "least severe") | model left out computed facts (passed in the tier 1 run) |
| I3 | 1 | answer omits the incident ID 978 | model left out computed facts |
| W1 | 1 | answer omits the count 34 and the data-end date | model left out computed facts |
| A4 | 1 | answer lists 2 of the 3 parts below minimum | model left out computed facts |
| S6 | 3 | no currency caveat | model left out computed facts |
| I8 | 2 | lists 2 of the 4 near misses with lost days | model left out computed facts |
| I13 | 2 | no date of the latest incident | model left out computed facts |
| V6 | 2 | no data-end date | model left out computed facts |
| V9 | 3 | does not say values are in Celsius | wording |
| X4 | 3 | cross-source question not implemented | pipeline gap |
| Q1 | 1 (manager) | answer contains "is in good shape" | wording |
| Q3 | 1 (manager) | CNC-02 summary has no oil conflict | pipeline gap |
| Q15 | 2 (manager) | machines without sensors not listed | pipeline gap |
| Q18 | 2 (manager) | LOTO SOP summary does not name "LOTO" | wording |

The main pattern: the computed facts are in the evidence, but the model summarises and drops counts, IDs and caveats that the cases check for. The retrieval-mode template shows them; the model's wording often does not.

### Total e2e spend so far

USD 0.1337 across 289 logged eval model calls (`logs/spend.jsonl`, source "eval"). This includes 86 calls from a first attempt that never reached the API (see the log), recorded with zero tokens and no cost.
