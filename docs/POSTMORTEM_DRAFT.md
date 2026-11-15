# Post-mortem (draft outline)

Draft written 15 Nov 2026 from `docs/ENHANCEMENT_LOG.md` and the eval results. The team will finish it after the demo. Sections marked _TODO_ need the team's own account.

## What worked

- **Characterization tests first.** 105 tests pinned the old behaviour before the big module was split into `jm_rag/`. The refactor passed them without editing any assertion.
- **Policy in code, not in the prompt.** The input guard, validator, conflict rules, mandatory notes and outcome rules are all code. The model cannot choose the outcome or skip a caveat. Refusals make zero model calls (9/9 offline, 8/8 retrieval).
- **Computed facts.** Counts, totals and date ranges are worked out by code from all matching records. When the model dropped a required figure, code added it in a "Key figures" line. This fixed the most common e2e failure from Phase 5.
- **Cheap, layered evals.** Offline and retrieval modes cost nothing, so they ran after every change. All e2e runs together cost about USD 0.29, well under the USD 1 cap.
- **Cost visible everywhere.** Each answer shows its cost, chat costs are stored with the message, and one command prints the spend report.
- **Privacy habits.** Fixtures are invented. Scripts that touch client data print counts and IDs only. The OCR accuracy report shows no values.

## What we would do differently

- **Measure OCR accuracy on day one.** Against the checked readings only 58% of structured nameplate fields match. Three main-set cases (N4, N6, N10) still fail on OCR errors that a review in the OCR Review tab would fix.
- **Keep the held-out set held out.** We used three manager-set failures to guide fixes, so the manager set no longer measures unseen questions. Its honest pre-fix retrieval score was 15/20.
- **Check meaning, not substrings.** Some case checks failed on wording, not on content: a negated phrase, and a date written as `2026-06-30`. We fixed the prompt and the checks, but only after spending e2e runs on them.
- **Smoke-test the configuration before an e2e run.** The first e2e attempt failed on an empty `OPENAI_BASE_URL`, and 86 calls never reached the API.
- **Route all data inspection through counts-only helpers from the start.** In Phase 5 one person's first name, taken from a workbook title, was printed to the terminal. Nothing reached git, but the name screening list still covers only employees.
- **Test outcomes for follow-ups, not only retrieval.** "and CNC-03?" retrieved the right sources but lost the lubricant conflict. Only the manual demo check found it (fixed in Phase 6).
- _TODO: team process, time split, what we would tell the next team._

## Known limits

- **Retrieval is TF-IDF.** A paraphrase that shares no words with the evidence can miss it.
- **OCR is unverified until reviewed.** On 15 Nov 2026 no review decision had been saved yet for any of the 12 nameplates or 30 forms.
- **Remaining eval failures:**
  - retrieval mode: V8 and X4 (tier 3), manager Q3 and Q15;
  - e2e mode, last full run: the same plus V6 and V9, whose fixes have not been rerun in e2e.
  - See `docs/EVAL_RESULTS.md`.
- **The e2e results are older than the latest code.** The last e2e run (tier 1, once) was in Phase 5c. The tier 1 `--repeat 2` run dates from Phase 5, before the fixes.
- **The client has not confirmed the assumptions:** the severity mapping, the meaning of `ALL`, the shift hours, the currency, and the missing 5-Why documents (`docs/ASSUMPTIONS.md`).
- **Order of trust is per conflict.** The SOP, nameplate and CMMS order is written into each conflict note, not applied as one general rule.
- **"Recently" means newest first**, not a fixed date window.
- **No login.** Saved chats are shared by everyone on the same database.
- **Budget limits exist but are unset.**

## Demo

- _TODO: which questions the panel asked, what the app did, what surprised us._

## Numbers to quote

- Unit tests: see `docs/EVAL_RESULTS.md` for the latest count.
- Retrieval mode: main 64/69 (tier 1 29/29); 64/66 without the three OCR data-error cases.
- Total eval spend: about USD 0.29.
