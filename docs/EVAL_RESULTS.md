# Eval results

Final summary, 15 Nov 2026, branch `enhance/rag-hardening`. Counts and case IDs only. The cases are listed in `docs/QUESTION_CATALOGUE.md`; options and gating rules are in `evals/README.md`. Expected values for nameplate and incident cases are the team's checked readings; a failure caused by this repo's OCR is labelled "OCR data error, fix via OCR Review".

## Commands

From the repo root:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m evals.run --mode offline
.\.venv\Scripts\python.exe -m evals.run --mode retrieval
.\.venv\Scripts\python.exe -m evals.run --mode e2e --tier 1 --repeat 2   # not rerun in Phase 6 or 7
.\.venv\Scripts\python.exe -m jm_rag.observability                         # spend report
```

## Unit tests (15 Nov 2026)

536 tests, all pass.

## Offline (15 Nov 2026)

Fixture corpus and a scripted mock model; no MySQL, no cost. Exit code 0.

| Set | Passed |
|---|---|
| offline cases | 20/20 |
| main-set refusals | 7/7 |
| manager refusal | 1/1 |
| legitimate questions | 72/72 |
| hostile prompts | 40/40 |
| refusals with no model call | 9/9 |

## Retrieval (15 Nov 2026)

Live MySQL and files, no model; the answer is the code-built template. Cost USD 0. Exit code 0 (no gating failure).

| Set | Passed | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|---|
| main (69) | 64 | 29/29 | 24/27 | 11/13 |
| main without N4, N6, N10 (66) | 64 | 29/29 | 24/24 | 11/13 |
| added (8) | 8 | 5/5 | 3/3 | |
| manager (20) | 18 | 10/11 | 8/9 | |
| legitimate (72) | 72 | | | |
| hostile (40) | 40 | | | |
| refusals | 8/8, no model call | | | |

## End to end (gpt-4o-mini)

No e2e run was made in Phase 6 or Phase 7. The latest runs are older than the current code:

- Phase 5c changed the date format, the Celsius caveat and the condition-judgement check.
- Phase 6 made follow-ups keep their conflicts and notes.

| Run | Date and phase | Projected USD | Actual USD | Result |
|---|---|---|---|---|
| Tier 1, once | 14 Nov 2026, Phase 5c | 0.0368 | 0.0399 | main 29/29, added 5/5, manager 10/11 (Q3), refusals 4/4 with no model call |
| Main, added and manager sets, once | 14 Nov 2026, Phase 5b | 0.0705 | 0.0720 | main 62/69 (tier 1 28/29, tier 2 23/27, tier 3 11/13); 62/66 without N4, N6, N10 (tier 2 23/24 = 96%); added 8/8; manager 17/20; refusals 8/8 with no model call |
| Tier 1, `--repeat 2` | 14 Nov 2026, Phase 5, before the 5b and 5c fixes | 0.055 | 0.0697 | main 26/29, added 4/5, manager 9/11; the same failures in both runs, so outcomes were stable |

The 5b full-run failures W1 (tier 1) and Q1 were fixed in 5c and passed in the 5c tier 1 run. V6 and V9 were fixed in 5c but have not been rerun in e2e.

## Remaining failures and why

| Case | Tier | Mode | Failure | Cause |
|---|---|---|---|---|
| N4, N6, N10 | 2 | retrieval, e2e | wrong or missing values; N10 shows a conflict | OCR data errors in the nameplate readings (grease interval, lubricant, capacity). Fix via OCR Review; the cases were not re-baselined to match the OCR. |
| V8 | 3 | retrieval | the gap count is not in the template answer | The figure is in the evidence but the template does not show it. V8 passed in the 5b e2e run, where the model stated it. |
| X4 | 3 | retrieval, e2e | no data-end date | A cross-source question (open work orders and no sensor data) that the pipeline does not join. |
| Q3 | manager tier 1 | retrieval, e2e | answer instead of conflict | A machine summary does not pull in the lubricant conflict. Pipeline gap. |
| Q15 | manager tier 2 | retrieval, e2e | a machine without sensors is not listed | The answer lists the machines with sensors but not the ones without. Pipeline gap. |
| V6, V9 | 2, 3 | e2e (5b) | date format; Celsius wording | Fixed in 5c; pass in retrieval; not rerun in e2e. |

The tier 3 and manager failures are reported but do not gate. The manager set is no longer fully held out, because three of its failures guided fixes in Phase 5. Its pre-fix retrieval score was 15/20.

## One traced hard question

"What is the max load of CRN-01?" (case N9), retrieval mode, 15 Nov 2026. The steps come from the response trace; no values are shown.

1. Input guard: pass, no flag.
2. Retrieval: 2 sources (SOP chunks).
3. Related sources: code added the CRN-01 nameplate and its processed OCR, so the plate sits beside the SOP. That makes 4 sources.
4. Computed facts: none apply.
5. Path: template (no model in this mode). In the app the model drafts here and the validator checks the draft.
6. Conflicts: 2. One is the SOP load against a plate with no tonnage, with the SOP trusted. The other is the SOP's near-miss mention against the incident records.
7. Notes: 5 (OCR unverified, the flagged capacity reading, both conflicts, and no model).
8. Outcome: conflict, citing all 4 sources.

## Spend

| Item | USD |
|---|---|
| All e2e eval runs (Phases 5 to 5c), from `logs/spend.jsonl` | 0.2870 |
| Phase 6 live AppTest answer (chat; the test chat was deleted afterwards) | 0.000358 |
| Phase 7 | 0 (no model calls) |

`python -m jm_rag.observability` on 15 Nov 2026 reports eval USD 0.2870, chat USD 0.0000 and other USD 0.0000 for all time.
