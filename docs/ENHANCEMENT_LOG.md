# Enhancement log

Tracks work done against `KIRO_ENHANCEMENT_PLAN.md`. Counts only; no client values.

## Phase 0: Baseline and setup

Date: 14 Nov 2026. Branch: `enhance/rag-hardening`.

### What changed
- Created branch `enhance/rag-hardening` from `main`.
- `.gitignore`: added `reference/`, `evals/out/`, `logs/`, `.pytest_cache/`. `data/guard/` is already covered by `data/*`. Verified with `git check-ignore`.
- Added `requirements-eval.txt` (`PyYAML>=6,<7`).
- Added `tests/fixtures/__init__.py`: invented corpus of 22 sources in the shape `load_sources()` produces (3 machines, 2 nameplates, 5 work orders, 3 incidents, 1 incident OCR record with an embedded "ignore previous instructions" text, 1 SOP, 2 spares rows including an `ALL` row, sensor summary and monthly trend, capability guide). TST-02 has an OCR model that disagrees with the CMMS model. Loader functions: `build_fixture_sources()` and `load_fixture_sources()`.
- Added `tests/test_fixtures_corpus.py` (5 tests) to prove the fixtures load and work with `retrieve()`.

### Results
- Baseline before any change: 43 tests, all pass.
- After Phase 0: 48 tests, all pass.
- Live check: MySQL container `capstone-mysql` is healthy; `load_sources()` returns 1824 sources with 0 warnings (1603 work orders, 85 incidents, 30 incident OCR, 12 nameplates, 5 sensor summaries, 5 monthly trends, 10 spares rows, 4 SOP chunks).

### MySQL tables and columns the app reads
- `machines` (machine_id, machine_name, model, year_installed)
- `work_orders` (wo_id, machine_id, wo_type, description, wo_date, duration_hrs, cost_sgd, status; `emp_code` exists but is not selected)
- `safety_incidents` (incident_id, incident_date, machine_id, description, severity, lost_days, reporting)
- `sensor_readings`, `sensor_gaps`, `sensor_quality_issues`
- `nameplate_assets_staging`, `nameplate_ocr_raw`, `incident_report_ocr`, `ocr_review_decisions` (created by repo SQL/scripts, not the CMMS dump)
- `employees` (emp_id, emp_code, emp_name, trade, shift) is in the dump; needed in Phase 3 only for `build_guard_terms.py`.

### Contradictions between the plan and the repo
1. Existing test count is 43, not "about 47".
2. `load_sources()` returns a tuple `(sources, warnings)`, not a dict. Individual sources are dicts. They have no `id`; `retrieve()` adds `S1`, `S2`, ... Fixtures follow this.
3. `reference/rag_capstone/` already existed and was complete when Phase 0 started, and `.gitignore` already held an uncommitted edit adding `reference/` and the log folders. Phase 0 committed that edit.
4. The uncommitted working-tree edit to `.env.example` replaces the `OPENAI_API_KEY` placeholder with a 179-character value that starts `sk-pro`. This looks like a real key. It was NOT committed and is not in the Phase 0 commit. It needs the human's attention (see open issues).
5. The nameplate and incident OCR queries select `reviewer` (from `ocr_review_decisions`) into source text. A reviewer value could be a person's name. Not changed in Phase 0; to be covered by the Phase 3 name-leak audit.
6. `KIRO_ENHANCEMENT_PLAN.md` itself is untracked. It was not committed.

### Open issues
- `.env.example` contains a key-like value in the working tree (uncommitted). Revert it to a placeholder, and rotate the key if it was real or ever committed elsewhere. `.env.example` is tracked, so a careless `git add -A` would publish it.
- Streamlit startup was not run; `app` imports cleanly (tests import `app`) and the data layer loads against live MySQL.

## Phase 1: Characterization tests

Date: 14 Nov 2026.

### What changed
- Added `tests/test_characterization.py` with 105 tests in 9 classes. They pin the current behaviour of `parse_explicit_date`, `parse_date_window`, `partial_work_order_date` and `resolve_partial_work_order_date`, the intent helpers, `format_work_order_table`, `format_incident_table`, `format_combined_history_table`, `retrieve()`, `input_refusal`, `validate_answer`, `serialize_evidence` and `build_sensor_monthly_trend_sources`. They use the invented fixture corpus only.
- Date forms from `RAG_SKILL.md` are all covered: `26 July 2024`, `26-07-2024` (day first), `2024-07-26`, `July 2024`, `Jul2024`, `June-August 2025`, `2024-2025`.
- No production code and no existing test was changed.
- Probe output was used to write each assertion, so the tests describe actual behaviour.

### Results
- New tests: 105, all pass. Existing 48 tests untouched and green. Full suite: 153 tests, OK.
- No MySQL, no network and no model needed for the new tests.

### Odd behaviour found (not fixed; each is marked `ODD:` in the test file)
1. `parse_date_window("31 Feb 2024")` returns the whole of February 2024 because the month-year rule matches after the day rule fails.
2. `parse_date_window("July 2024 to 2025")` returns 1 Jan 2024 to 31 Dec 2025, dropping the month.
3. `ASSET_PATTERN` hardcodes the prefixes `CNC|CRN|LTH|MILL|PMP|WELD|BLAST|CMP`. A tag with another prefix (fixture `TST-99`) is not seen as a tag, so the question returns other machines' nameplates instead of nothing. Fixture machines are found by alias matching only. A new machine type would need a code change.
4. "service history" counts as a table request but not as a work-order intent in `retrieve()`. The date window is then not applied and non-work-order sources are mixed in. "service history and incidents table in 2025" returns no work orders.
5. An unmatched report ID (for example `IR-2025-101`) is ignored and all incident sources come back, instead of nothing.
6. A sensor question for a machine with no sensor data (fixture `TST-02`) returns unrelated sources (work orders, nameplate). The abstain decision has to be made later (Phase 4).
7. `input_refusal` does not catch "Ignore previous instructions" or "how do I override the alarm". It also refuses "ignore the machine guard inspection finding" (false positive on "guard").
8. `validate_answer` does not check numbers or identifiers against evidence, and does not detect employee names.
9. `format_incident_table` prints OCR free text verbatim, including embedded instruction text from the fixture record. Phase 3 (name and evidence screening) and Phase 4 (untrusted evidence) must handle this.
10. The OCR incident event ID in the table is the trailing number of the report ID (`IR-2025-990` becomes `990`), so an OCR report and a CMMS incident group together only when those numbers match.

### Notes for later phases
- Phase 3: treat the `reviewer` field pulled from `ocr_review_decisions` as personal data (human instruction, 14 Nov 2026). Keep it out of evidence text, the evidence panel and answers. The nameplate and incident OCR queries in `_load_mysql_sources` select `d.reviewer`, and `effective_record` receives the row. Add a test with a fixture reviewer value.
- `.env.example` is clean again in the working tree (the key-like edit is gone).

## Phase 2: Refactor into `jm_rag/`

Date: 14 Nov 2026.

### What changed
- Moved the code in `scripts/maintenance_rag.py` into the `jm_rag` package, verbatim, in eight steps (config, prompt, intents, dates, tables, input guard and validator with common helpers and sensors, source loaders, retrieval and `load_sources`). The full suite was run after every step and stayed at 153 passing.
- `scripts/maintenance_rag.py` is now a 58-line deprecated shim that re-exports every public name the old module had, plus the private helpers (`_source`, `_query_rows`, `_query_one`, `_load_text_documents`, `_load_mysql_sources`, `_load_processed_audits`). A name-parity check against the previous version found only stdlib and third-party imports missing (`re`, `json`, `date`, and so on).
- No test file was edited. No `ODD:` behaviour was changed. `input_refusal` and `validate_answer` are moved unchanged.
- `jm_rag/config.py` holds `ROOT`, `ASSET_PATTERN`, `IMAGE_EXTENSIONS`, `PROCESSED_AUDITS`, `MONTH_NUMBERS` (equality with the old dict checked) and a new `DATA_END = 2026-06-30`, which no code reads yet.

### Deviations from the plan's layout
1. `intents.py` (the three question-intent helpers), `common.py` (`_source`), `sensors.py`, `sources_mysql.py`, `sources_files.py` and `sources_ocr.py` are extra. The plan puts all loaders in one `sources.py`, which would have been about 500 lines. `serialize_evidence` lives in `prompt.py`.
2. `input_refusal` is in `guardrails/input_guard.py` and `validate_answer` is in `validator.py` already, unchanged, so Phase 3 and 4 extend them in place. `guardrails/patterns.py`, `names.py`, `output_guard.py`, `template.py`, `pipeline.py` and `observability.py` do not exist yet.
3. Two existing tests patch `scripts.maintenance_rag.ROOT` and `scripts.maintenance_rag.open_connection`. Since the code that reads those names moved, the shim swaps its class for a small `ModuleType` subclass that forwards assignments of those two names to `jm_rag.config` and `jm_rag.sources_mysql`. The moved modules read `config.ROOT` at call time (the only edit to moved code: bare `ROOT` became `config.ROOT`). This lets the tests stay unedited. The tests should be pointed at `jm_rag` when the shim is removed.

### Results
- Tests: 153, all pass (Phase 0: 48 including fixtures, Phase 1: 105).
- pyflakes (run from a temp folder, not added to the repo): no undefined names. One unused local in `retrieval.py`, `exact_work_order_date`, existed before the move. Left alone; delete it once a test shows it unused.
- `streamlit run app.py` (headless, port 8599): server starts and `/_stcore/health` returns `ok`. `AppTest.from_file("app.py").run()` against live MySQL: 0 exceptions, tabs Assistant, OCR Review, Sensor Trends.

### Module sizes (lines)
config 21, prompt 57, intents 22, dates 116, tables 96, common 6, sensors 60, guardrails/input_guard 18, validator 18, sources 50, sources_files 77, sources_ocr 146, sources_mysql 218, retrieval 168, shim 58. No module is over 300 lines.

### Open issues
- `KIRO_ENHANCEMENT_PLAN.md` on disk has no Phase 4 fix list for the ODD findings. The only change since the last commit is the baseline test count ("43 tests"). The list may be unsaved in an editor.

## Phase 3: Guardrails and privacy

Date: 14 Nov 2026. No employee name appears in this log, the tests, the terminal output or any fixture. Test names are invented (`Zed Quarrel`, `Pim Vesper`) and were checked not to collide with the real list.

### What changed
- `jm_rag/guardrails/patterns.py`, `input_guard.py` (rewritten), `names.py`, `output_guard.py`, `sanitize.py` (new). `scripts/build_guard_terms.py` (new). `tests/test_guardrails.py` (83 tests) and `tests/data/legit_questions.txt` (62 questions) are new.
- Input guard classes, first match wins: `INJECTION`, `NAME_REQUEST`, `PERSON_RANKING`, `WRITE_INTENT`, `SAFETY_BYPASS`, `PRIVATE_DATA`, then a full name from the term list, `OFF_TOPIC`; `EMPTY` and `TOO_LONG` (500 characters, `MAX_QUESTION_CHARS` overrides) are checked first. `SAFETY_BYPASS` and `PRIVATE_DATA` keep the old messages word for word. Result shape is `{verdict, class, message, flags, question}`. Flags: `inference_request`, `needs_future_date` (after 30 Jun 2026), `asks_missing_document`, `asks_schedule`.
- `input_refusal()` stays as a thin wrapper (full guard, treated as if there were history, empty is not a refusal), so `app.py` callers, the shim and the old tests keep working. `validate_answer` now calls `unsafe_text_message`, which checks only the safety-bypass and private-data classes, so its behaviour on answer text is unchanged.
- Names: `names.py` loads `data/guard/name_terms.json`. `build_guard_terms.py` (run `.\.venv\Scripts\python.exe -m scripts.build_guard_terms`) reads `employees.emp_name`, adds a "last first" variant for multi-word names, drops terms under 5 characters, merges an optional `data/guard/extra_terms.txt`, and prints only counts. Real run: 62 terms from 31 names. The file is git-ignored (`data/*`).
- Sanitising gate: `load_sources()` passes every source (title, text, location and the structured `record`) and every warning through `sanitize_sources`. `serialize_evidence` sanitises again, so evidence sent to the model is clean. `app.py` sanitises retrieved sources, evidence shown in the UI (`show_evidence`) and saved chat messages (displayed and replayed to the model), and runs `output_guard.check` on every answer (model answer, tables, refusals, fallbacks). A small sidebar warning shows when the name list is missing.
- Reviewer field (human instruction): `d.reviewer` is no longer selected in either review query, `row.pop("reviewer")` is kept as a second layer, `sanitize` drops `reviewer`/`reviewed_by`/`emp_name`-type keys from records and removes `"reviewer": ...` pairs from text. `effective_record` already removed `reviewer` and `notes` from values; tests prove none of it reaches evidence.
- Phase 4 item 6 is done here: `Ignore previous instructions` is refused (`INJECTION`), `how do I override the alarm` is refused (`SAFETY_BYPASS`), and `ignore the machine guard inspection finding` passes (a guard followed by a record word such as inspection, finding, report, log, audit or history is treated as a record, not an action). The two pinned tests were flipped deliberately and renamed (`test_prompt_injection_and_alarm_override_are_refused`, `test_machine_guard_inspection_finding_is_not_refused`), each with a comment naming the old behaviour. No other assertion in Phase 0 to 2 tests changed.
- Phase 4 item 7 is partly done (names and IDs in answers are caught by the output guard); numbers and identifiers are still unchecked. Item 8 is partly done (names are stripped from tables and evidence); injected instruction text in OCR free text is still printed as is. Both stay on the Phase 4 list.

### Results
- Full suite: 236 tests, all pass (153 before, 83 new). `tests/test_guardrails.py` covers every class with 5 to 14 phrasings, the 62 legitimate questions both with and without history, flags (24 positive, 6 negative cases), the 23 ported hostile prompts, name and ID screening, the fail-safe states, the output guard, one test per source path and the build script.
- Source paths tested with a fake term list: work-order description, CMMS incident description, incident OCR free text (description, action, location), review tables (corrections, notes, reviewer, for nameplate and incident), the reviewer column not being selected, SQL error text in warnings, processed nameplate JSON and TXT, processed incident JSONL, SOP documents, spares workbook, processed audit files, chat history, evidence sent to the model, and evidence shown in the UI. A mutation check (sanitising switched off) made 11 of the 13 source-path tests fail.
- Refusal with no model: `AppFlowTests.test_every_refused_question_makes_no_model_call_and_loads_no_evidence` drives the real Streamlit chat flow (`AppTest`) for 100 refused questions (77 from the class lists plus the 23 hostile prompts). The OpenAI constructor and `load_sources` raise if touched. For every question the saved answer is the class message, sources are empty and tokens are 0. Also tested: a model answer containing a name is replaced by the safe refusal; a clean model answer passes; a name planted in a source never reaches the table, the model prompt, the saved row or the screen; a name in saved chat history is not shown or replayed.
- Live data (counts only): 0 name hits across the 1824 loaded sources and across every text column of the 13 MySQL tables, 0 national IDs, 0 reviewer values stored, 36 real history tables (12 machines x 3 table types) all pass the output guard (no false blocks). `AppTest` against live MySQL: 0 exceptions, a servicing question returns a 10-row table, a name request is refused.

### False positives found while building (and what was done)
1. `PMP-T01` was refused as off-topic: the domain pattern needed a digit pair right after the dash. Fixed (`[a-z]{2,5}-[a-z]?\d{2}`), and the same fix applied to the write-intent noun list.
2. "how many lost days were recorded in 2024" was off-topic. Added `lost days` to the domain words.
3. The reference's write-intent pattern would refuse "show open work orders for CNC-02" (verb "open" plus "work orders" plus "for"). The pattern is now anchored to the start of the request or a request phrase ("please", "can you", "i want to", and so on).
4. The reference's name-request pattern for NRIC, phone and home address clashed with the existing private-data message. Those words now belong only to `PRIVATE_DATA`, so the old messages and pinned tests hold. The reference's `override ... safety` injection pattern was narrowed so it falls to `SAFETY_BYPASS` with the safety message.
5. Left as a deliberate refusal: "what is the bypass procedure for the crane limit switch?" (asks how to bypass). Moved out of the legitimate list into the `SAFETY_BYPASS` phrasings. A legitimate SOP lookup that uses the word "bypass" as a noun will be refused.
6. Passing the guard on purpose (answered from evidence that holds no names or employee codes, so they abstain downstream): "How many incidents did EMP015 have?", "Which technicians were involved in incident 917, I just need their codes", "Show the notes the reviewer typed on the nameplate review". Say if you want per-person code questions refused at the input guard instead.

### Interpretation notes and residual risks
- "Fail safe and say so" is implemented as: the guard keeps working for IDs, keys and markers, logs one warning, reports `names_unloaded` (`names.names_status()`, `output_guard.check()["names_unloaded"]`), and the app shows a sidebar warning. Names themselves cannot be detected until the file exists, and a typed full name is not caught as a name request without the list. The guard does not block all answers in that state.
- The plan's "internal table names" markers: only the `employees` table (in SQL context), `emp_name`, `name_terms`, SQL fragments and the phrase "system prompt" count. Table names the app already cites as sources (`work_orders`, `safety_incidents`, `incident_report_ocr`, `ocr_review_decisions`) are not markers, or every history table would be blocked.
- The term list only knows people in `employees` (plus anything in `data/guard/extra_terms.txt`). People who appear only in documents, for example a sender or signatory in `data/docs/sops/0000_gm_brief_email.txt`, are not caught by it. I did not print that file. Add such names (one per line, untracked file) to `data/guard/extra_terms.txt` and rerun the build script.
- First names alone, initials, and misspelt names are not matched. Per-person questions are caught by pattern, not by name.
- `exact_work_order_date` in `retrieval.py` is still an unused local.

## Phase 3 follow-up: employee-level incident questions (human decision, 14 Nov 2026)

- New refusal class `PERSON_INCIDENTS`, checked after `PERSON_RANKING` and before `WRITE_INTENT`. It refuses questions about one employee code's incidents or injuries ("How many incidents did EMP015 have?") and any question asking which technicians were involved in, present at or responsible for an incident. Every pattern needs an incident word, so technician codes on work orders and aggregate counts stay allowed. 11 phrasings are tested; the message offers aggregate counts and says work-order codes are fine.
- Legitimate counter-examples added to `tests/data/legit_questions.txt` (now 72): "who did work order 11529", "how many work orders did EMP015 complete in 2025", "which technician codes appear on work orders for CNC-02", "how many incidents involved a crane", "which machines were involved in incidents in 2025", and others.
- False positive found and fixed on the way: "show the technicians' trade breakdown for work orders" was refused as a name request (a reference pattern for "show the technicians"). The pattern now ignores a possessive and "trade/shift/count/breakdown/by/per" after the noun.
- The test that listed "How many incidents did EMP015 have?" and "Which technicians were involved ..." as questions passing the guard on purpose was changed to match the decision. No other assertion was weakened.

## Phase 4a: validation, outcomes, notes, conflicts, fallbacks, usage

Date: 14 Nov 2026. The "Behaviour fixes found in Phase 1" list is Phase 4b and is untouched; every `ODD:` test is unchanged.

### What changed
- `jm_rag/validator.py`: `post_check(answer, sources, question)` returns all problems in one list. It checks that every `[S#]` exists, that a factual answer has a citation (an answer that only says it could not find or cannot give something needs none), that every number and every identifier (machine tags, part numbers, `IR-YYYY-NNN`, SOP IDs, codes such as `GA30`) appears in the cited sources or the question, and that a quotation of four or more words appears word for word in a cited source. `4.0` equals `4`, `1,800` equals `1800.0`, `0` is always allowed, list numbering and `[S#]` markers are ignored, and digits inside a source's codes count as evidence (`906` is allowed beside `IR-2025-906`). `validate_answer` is kept unchanged for old callers.
- `jm_rag/pipeline.py`: `answer_question(question, history, corpus, client, *, model=None)` returns the plan's response contract (answer, outcome, refusal_class, sources, cited_ids, notes, flags, usage, trace, errors). Flow: input guard, partial-date and ambiguous-alias clarification, retrieval, deterministic paths (history tables, no evidence), model answer, post-check, one retry with the error list, template fallback, notes and conflicts, outcome, output guard. `app.py` is not yet switched to it (Phase 6); the pipeline ports the app's follow-up behaviour (year-only answer to a partial date, previous question carried into a follow-up without digits).
- `jm_rag/outcome.py`: rules in the plan's order (refuse, clarify, abstain, conflict, error, answer).
- `jm_rag/notes.py`: mandatory notes from code: future date (data ends 30 Jun 2026), missing 5-Why/root-cause document, no schedule, inference, severity scale change (only when the question is about severity and the evidence spans 1 Jul 2025), and OCR caution. Notes are appended to the answer under "Notes:" and returned in `notes`.
- `jm_rag/conflicts.py`: nameplate OCR model vs CMMS model, MySQL staging vs processed OCR, nameplate lubricant vs the spares entry for `ALL` (never expanded), SOP crane load vs nameplate (including a plate with no tonnage, CRN-01), and incident versions across CMMS, OCR staging and processed OCR (agreeing versions are a note, not a conflict). Each states which source is trusted and why (SOP, then nameplate, then CMMS free text; the CMMS `safety_incidents` record for incidents) and shows both sides.
- `jm_rag/template.py`: deterministic cited list of the facts (up to 5 sources, values copied from records). Always passes `post_check`. Instruction-like free text is replaced by "[free text withheld: it reads like an instruction]".
- `jm_rag/observability.py`: `api_cost_rates` and `estimate_api_cost` moved here (`app.py` imports them, so `from app import estimate_api_cost` still works), plus `new_usage` and `record_call`.
- `tests/mock_client.py` (`MockClient`, `ForbiddenClient`), `tests/test_validator.py` (81 tests), `tests/test_pipeline.py` (26 tests).

### Results
- Full suite: 347 tests, all pass (236 before; +11 in `test_guardrails` for the new class, +81, +26 here). Counts per file: guardrails 87, validator 81, pipeline 26, characterization 105, maintenance_rag 13, source_loading 23, ocr_comparison 7, fixtures 5.
- Example cases (28, each asserting outcome, model calls and notes) run through `answer_question` with the mock client: see the table in the Phase 4a report. All behave as listed there.
- Live data (mock-free, no model, 1824 sources): the template answer passes `post_check` for all 17 probe questions; CRN-01 max-load and CNC-03 lubricant give `conflict` with sensible notes; "work orders for the CNC lathe" gives `clarify` (the alias maps to CNC-01 and CNC-02).

### Decisions and interpretations
1. Error vs abstain: the plan lists `error` after `conflict`. Code treats "no evidence and a failed source" as `error` ahead of `abstain`, because "no records" cannot be told from "could not check". Evidence plus a failed source keeps the normal outcome and adds a "I could not check ..." note. Only the failed source's label is shown, never the driver's error text.
2. A history table request with only rows of the wrong kind (for example an SOP chunk) now counts as no evidence, instead of printing "I couldn't find matching service records". This is what lets a dead MySQL give an honest `error`.
3. Conflicts are scoped to the question (a model question keeps the model conflict, a lubricant question keeps the lubricant conflict, and so on). Without scoping, OCR noise on an unrelated field flipped many answers to `conflict`.
4. OCR is noisy, so model and lubricant comparisons use the identifying part: tokens with digits (QT-250, VG68) must appear; with no digits any similar word agrees. Numbers compare as numbers (`22.00` equals `22.0`).
5. `related_sources` adds the other side of a conflict to the evidence: the `ALL` spares row beside a nameplate for lubricant questions, and the crane nameplate and SOP for load questions. Retrieval ranks by text similarity and left one side out.
6. A model call that raises is counted (calls +1, zero tokens, `error` on the step); its cost is unknown, so `cost_usd` only sums known costs.
7. Number strictness follows the plan literally. A model answer that states a count it worked out itself ("3 work orders") has a number that is in no source and will be rejected, retried and then replaced by the template. History tables are built by code and are not affected. This should be watched in the Phase 5 e2e run; a human decision may be needed (for example allow counts of cited items).
8. New module files beyond the plan layout: `conflicts.py`, `notes.py`, `outcome.py`. `pipeline.py` is 235 lines; all modules are under 300.

### Findings for Phase 4b or later (no change made)
- "What oil does CNC-02 take?" (the client brief's own example) does not retrieve the nameplate: the nameplate keyword list has "lubricant" and "grease" but not "oil", so evidence is unrelated incidents and the outcome is `answer` without the lubricant conflict the reference expects. Add `oil` to the nameplate intent in retrieval.
- "Why is CNC-02 vibrating more?" retrieves nothing, because the sensor intent matches "vibration" but not "vibrating". The inference question should still show the sensor facts, with the gap stated. Add `vibrat\w*`.
- "service history and incidents table for CNC-02 in 2025" abstains with no evidence (fix list item 3).
- `exact_work_order_date` in `retrieval.py` is still an unused local.

## Phase 4b, step 1: computed facts

- `jm_rag/facts.py`: for the question's machine, date and topic filters, the code works out counts, totals, minima, maxima and date ranges over all matching records (not only the 5 or 10 shown) and offers them as one extra evidence source titled "Computed facts (calculated by code)", with its own `[S#]`. Work orders: count, date range, total, lowest and highest cost (and how many have a cost), total hours, counts by type and status (and by machine when more than one). Incidents: unique events (versions in CMMS, OCR staging and processed OCR counted once), date range, total and highest lost days, severity counts kept apart per scale. Sensor months: month range, lowest and highest monthly mean and maximum vibration and temperature with the month. Spares: row count, total quantity, how many are below minimum (part numbers listed), unit cost range.
- `retrieval.py` was split into `plan_query` (intents plus the filtered candidates) and `retrieve` (ranking), behaviour unchanged, plus `matching_records` for the facts. All 347 earlier tests stayed green after the split.
- `pipeline.py` adds the facts source on the model path. Count, total and extreme questions ("how many work orders", "total cost", "highest") now go to the model path instead of a history table (`is_aggregate_question`), so a count can be answered. `template.py` always includes the facts, so the no-model answer still shows them. The system prompt tells the model to use and cite the facts and not to work out figures itself.
- Number check unchanged: a number the model invents is in no source and fails, is retried once, then the template is shown. Tested with an invented count (13) and an invented total (999.99).
- Limit of the number check: it is a membership test, so a made-up number that happens to equal some digit group in the cited text passes (for example `7` passes when a source holds a date in July). The tests use numbers that are in no source.
- Fixture change: the invented spares rows now carry a `Source row` JSON blob like the real loader (needed to compute spares facts).
- `tests/test_facts.py`: 20 tests. Suite: 367 passing.
- Live data (counts only): "how many work orders did CNC-02 have in 2025" gives 59 work orders, 55,463.76 SGD, 303.9 hours; incidents in 2025 give 34 unique events from 58 source versions; spares give 3 below minimum; CNC-02 sensor months give 7 months with the highest mean vibration in 2026-06.
