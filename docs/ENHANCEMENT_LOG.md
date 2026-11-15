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

## Phase 4b, step 2: retrieval gaps

- Lubricant words: `oil`, `oils`, `lube`, `lubes`, `lubricant`, `lubricat*`, `grease`, `greasing`, `viscosity` and `VG<n>` now set the nameplate intent. Matching the intent was not enough on its own: the nameplate JSON has the word "lubricant" but not "oil", so TF-IDF scored the plate zero and the preferred types were ignored. A lubricant question now adds "lubricant grease oil" to the search text, and any sensor question adds "sensor vibration temperature readings".
- Sensor words match by stem: `sensors?`, `vibrat*` (vibrating, vibrates, vibrated), `temperatures?`, `trend*`. The trend intent also takes `more`, `less`, `higher`, `lower`, `worse`, `increas*`, `ris*`, `decreas*`, `chang*`, `climb*`, `drift*` (only checked when a sensor word is present).
- "Why is CNC-02 vibrating more?" now retrieves the monthly sensor trend plus the computed facts (7 months, lowest and highest monthly means and maxima), gives outcome `abstain`, and adds two notes: a new cause note ("The records show what changed, not why. The cause is not in the data, so I cannot give one.") for questions with "why" or "cause", and the inference note. The system prompt now also says not to offer causes, predictions or safety judgements the evidence does not state.
- "What oil does CNC-02 take?" now retrieves the CNC-02 nameplate (raw OCR text, processed OCR and MySQL staging) and the `ALL` spares row, and gives outcome `conflict`. In this data CNC-02's plate reads VG32, the same grade as the `ALL` hydraulic oil entry (VG32), so there is no direct mismatch for CNC-02. The conflict is that the `ALL` entry cannot be a per-machine fact because another machine's plate (CNC-03) reads VG68. The note says so, lists the machines that differ, and says `ALL` is left unresolved and not expanded. A machine whose own plate differs (CNC-03) gets the direct mismatch conflict. Grades are compared by the number after VG/G (OCR garbles other text); plates with no readable grade (for example CNC-01, "v632") are not counted as disagreeing.
- `tests/test_retrieval_gaps.py`: 15 tests. Suite: 382 passing.

## Phase 4b, step 3: the Phase 1 fix list (items 1, 2, 3, 4, 5, 8, 9)

Items 6 and 7 were done earlier. Each fix flipped its pinned `ODD:` test deliberately (renamed, with a comment naming the old behaviour); no other assertion was weakened. One existing validator test needed incident dates added to its fixture records, because incident grouping now needs a date (see item 9).

1. **Unreadable dates ask, they do not guess.** `dates.date_clarification` returns a clarifying question for a day that does not exist ("31 Feb 2024", "29 Feb 2025", "2024-13-01") and for a month glued to a year range ("July 2024 to 2025", "2024 to July 2025"). `parse_date_window` returns no window for those, `retrieve` returns nothing, and the pipeline answers with outcome `clarify`, no model call, no search. Flipped: `test_impossible_day_gives_no_window_and_a_clarifying_question`, `test_month_then_year_range_gives_no_window_and_a_clarifying_question`. Not handled (not on the list): a full month-to-month range with two years ("July 2024 to August 2025") still reads only the first month.
2. **Machine tags come from the data.** New `jm_rag/tags.py`. A tag-shaped word (`CNC-02`, `PMP-T01`, `TST-99`) is a tag when its prefix belongs to a loaded machine or to the old list of machine types. It is valid if a loaded source carries it, otherwise unknown. Part numbers and report IDs are not tags (a word inside a longer hyphenated code is ignored; all 10 real part numbers were checked). An unknown tag gives outcome `abstain` with "I could not find a machine with the ID TST-99. Known machines: ...", and never other machines' records. A mix of valid and unknown tags answers for the valid ones and adds the not-found sentence. Flipped: `test_unknown_tag_with_a_prefix_of_loaded_machines_returns_nothing`. Limit: a part number whose prefix equals a machine prefix (for example a spares code `CMP-12`) would be read as an unknown machine tag; a machine type with a prefix no loaded source has is not recognised as a tag.
3. **"Service history" is a work-order intent.** Retrieval treats `service history` as a work-order intent, so the date window applies, and the pipeline's combined-history test now accepts the plural "incidents" (it only matched "incident", so "service history and incidents table in 2025" returned work orders only). The question now returns both tables for the year, with no model call. Flipped: `test_service_history_is_a_work_order_intent_with_a_date_window`.
4. **Unmatched report IDs abstain.** A report ID that matches nothing returns nothing (a CMMS incident matches `IR-YYYY-N` by number and by the year of its date). The pipeline says "I could not find report IR-2025-101 in the CMMS incidents, OCR staging or processed OCR." If one of several IDs is found, the answer covers it and notes the missing one. Flipped: `test_unknown_report_id_returns_nothing`.
5. **No sensor data means abstain.** The set of machines with sensor data is read from the loaded sensor sources (today CMP-01, CNC-01, CNC-02, CNC-03, PMP-T01), not hard-coded. A question with a strict sensor word (sensor, vibrat*, temperature, reading, time series) about a machine outside the set returns nothing and the pipeline says "I have no sensor data for MILL-01. Sensor readings exist only for ...". The words "trend" and "gaps" alone do not trigger it, so "incident trend for TST-02" still works, and a question that also asks for work orders, incidents or lubricant is answered with a note. Flipped: `test_sensor_question_for_machine_without_sensors_returns_nothing`.
8. **Free text in tables is data.** `tables.free_text`: names are stripped, and OCR text and any text that reads like an instruction to the assistant (the injection phrasings) are shown only in quotes, cut at 100 characters (60 for instruction-like text) with a label ("OCR text, unverified", "shown as data, not an instruction"). Plain CMMS text is unchanged. Applied to incident and work-order descriptions. Flipped: `test_ocr_free_text_in_the_incident_table_is_quoted_truncated_and_labelled`. The old assertion still passed by accident (the phrase sits inside the first 60 characters), so the new one asserts the exact quoted, truncated, labelled cell and that the rest of the sentence is gone.
9. **Incident grouping.** New `jm_rag/incidents.py` is the one place that decides which sources are one event, used by tables, conflicts, facts and the combined history selection. A report and a CMMS incident are one event when the report number equals the CMMS ID, the report year equals the year of the CMMS date, and the dates agree where both exist. A different machine does not split them (it is reported as a disagreement). Two CMMS records, two different report keys, or a machine and day alone never merge. Decision: machine plus date alone does not link records, because two incidents can share a machine and a day; on real data this makes no difference (all 30 OCR reports match their CMMS record by number, year and date; 3 differ on machine and are now reported as a disagreement). Tables no longer collapse two events that share a trailing number. New tests: 14 grouping cases including the ones that do not match.

### Results
- Full suite: 437 tests, all pass. By file: guardrails 87, validator 81, pipeline 26, facts 20, retrieval gaps 15, fixes 4b 55, characterization 105, maintenance_rag 13, source_loading 23, ocr_comparison 7, fixtures 5.
- Live data, no model: "What oil does CNC-02 take?" gives `conflict` with the `ALL` note; "Why is CNC-02 vibrating more?" gives `abstain` with the sensor months, facts, cause note and inference note; "work orders on 31 Feb 2024" and "incidents in July 2024 to 2025" give `clarify`; "work orders for CNC-99" abstains and lists the known machines; "show IR-2025-101" abstains; "vibration for MILL-01" abstains and names the five machines with sensors; "service history and incidents table for CNC-02 in 2025" returns 18 rows across both tables. The 72 legitimate questions: 64 answer, 4 conflict (nameplate model, lubricant and crane load questions that really disagree), 3 abstain (risk, feels off, an "and CNC-03?" follow-up with no history carry-over, which is Phase 6), 1 clarify (the partial date, as designed).
- New false positives: none found in the legitimate list. Two things to watch: the part-number prefix limit in item 2 and the OCR text label, which makes every OCR description in an incident table appear in quotes.
- `retrieval.py` still has two unused locals (`exact_work_order_date`, `work_order_intent`). `conflicts.py` is 307 lines and `pipeline.py` 270.
- `app.py` still uses its own older flow, so none of these fixes reach the Streamlit app until Phase 6 wires `answer_question` in.

## Phase 4b follow-up: month-to-month ranges across a year boundary

- `dates.parse_date_window` now reads a month and year on both ends ("July 2024 to August 2025", "Jul 2024 - Mar 2025", "jul2024 - mar2025", also en and em dashes, "through", "until"). The window runs from the first day of the first month to the end of the last month. The pipeline, the retrieval filter and the computed facts all use it, so "work orders July 2024 to August 2025" is answered, not asked about.
- A range that ends before it starts ("August 2025 to July 2024") gives no window and a clarifying question. The mixed forms from fix 1 ("July 2024 to 2025", "2024 to July 2025") still ask; the check for them no longer misreads the year inside a full range as a stray year. An impossible day next to a full range still asks about the day.
- `tests/test_cross_year_ranges.py`: 11 tests. This also closes the gap listed under fix 1 in the Phase 4b step 3 entry.

## Phase 5: Eval suite (offline and retrieval only; e2e not run)

Human decisions (Section 10), 14 Nov 2026: commit the eval cases with only machine IDs, part numbers, counts and similar values (no names, no incident-form free text); stay on unittest; cap for one model-backed eval run is USD 1, print the projection first and ask before any run above it. Do not run e2e yet.

### What was added
- `evals/`: `cases.yaml` (69: 29/27/13 by tier, 7 `no_llm` refusals), `manager_cases.yaml` (20, held out), `legit_regression.yaml` (72, generated from `tests/data/legit_questions.txt`), `offline_cases.yaml` (20 fixture cases with scripted model replies), `hostile.py` (23 ported + 17 own, including an employee-code incident count, an initials request, and two benign questions about the fixture record that carries an injected instruction), `checks.py`, `run.py` (modes `offline`, `retrieval`, `e2e`; `--tier`, `--id`, `--set`, `--file`, `--repeat`, `--show`, `--cap`, `--yes`, `--project-only`), `README.md`.
- Cost: per-case calls, tokens and cost, totals, JSON output; e2e calls go to `logs/spend.jsonl` tagged `source: eval`; projection before e2e from the real prompt sizes; a run projected above the cap stops unless `--yes`. `--project-only` never creates a model client (tested).
- `docs/eval_rebaseline.md` (every case that differs from the reference), `docs/EVAL_RESULTS.md` (latest counts and failures).
- `tests/test_evals.py` (17 tests: checks, hostile judge, case-file counts and privacy, cost guard, offline mode end to end).

### Pipeline changes found by the main set (main set only; the manager set was not used)
1. Spares rows listed for "CNC-01/02/03" or "WELD-01/02" now carry each machine as a tag. `ALL` is never expanded. A "what spares do we hold for X" question keeps the `ALL` rows and raises a "listed for ALL, unresolved" conflict.
2. Words of a machine's name and model ("compressor", "milling", "overhead") pick that machine when no tag is given. "the lathe" (three machines) asks which one. SOP questions are excluded from this.
3. Sensor words: "running off", "drifting", "abnormal". "breakdowns" is a work-order word and filters by work-order type. Spares searches add spare-part words; a part number in the question (BRG-6310) makes it a spares question.
4. Ranked results are interleaved across the topics a question asks about, so one topic cannot fill every slot.
5. Computed facts extended: incidents by year, by machine (with the most), by how reported, with a scanned form, near misses with lost days, severity normalised to one scale (5 = worst) with the worst-case IDs and the misleading raw counts; work orders not closed (with IDs when few), most expensive and cheapest; spares parts listed, out of stock, "no currency stated, SGD assumed"; sensor months where vibration rose more than 10% (with month names); lubricant by machine grouped by grade; every facts source ends with "The data ends on 30 Jun 2026."
6. Conflicts: the spares `ALL` lubricant rule now also fires when no plate in the evidence confirms it and the plant's plates read more than one grade; near miss with lost days; CMMS severity not on the scanned form (only for severity or reliability questions); an SOP that mentions a dated incident the records do not hold (only for crane, sling, lift, load or incident questions). `conflicts_records.py` was split out of `conflicts.py`.
7. Gaps (outcome `abstain`): a nameplate field that the OCR did not read or flagged as implausible (WELD-01 capacity), unless the raw OCR text has the value next to its label, in which case that reading is reported as unverified; an SOP asked for on a topic no SOP covers (hot work); a sensor question about shifts (the evidence is monthly); whether two employee codes are one person.
8. New source "Employee data quality (codes only)": groups of employee codes that share a full name. The name is used inside the SQL to group and is never selected.
9. Follow-ups: "and in 2026?" and "and CNC-03?" rewrite the previous question's year or machine.
10. Count, total, "most", "per" and "each" questions go to the facts path; a question that also asks for a procedure or oil is not turned into a work-order table.
11. Bug: "TST-01 July 2024" was read as the day 1 July 2024 (the tag's digits). Dates now need the day not to follow a word character or dash. Test added.
12. Money values such as "$48" are parsed as numbers.

### Tests changed deliberately
- `test_facts.test_a_question_about_something_else_has_no_facts` asserted that a lubricant question had no facts. Lubricant questions now get lubricant facts, so it became `test_a_lubricant_question_gets_lubricant_facts_only` (asserts the lubricant facts and no work-order or incident facts), plus a new no-facts test using a serial-number question.
- `test_retrieval_gaps.test_a_machine_whose_plate_matches_all_still_gets_the_all_conflict` now expects the computed facts source beside the nameplate and spares row.
- No characterization test was changed.

### Results
- Unit tests: 467, all pass.
- Offline: offline 20/20, refusals 9/9 with 0 model calls, legitimate 72/72, hostile 40/40. Exit 0.
- Retrieval: main 68/69 (tier 1 29/29, tier 2 27/27, tier 3 12/13), manager 15/20 (tier 1 7/11, tier 2 8/9), legitimate 72/72, hostile 40/40, refusals 8/8 with 0 model calls. Exit 0. Failures: X4 (tier 3) and manager Q3, Q6, Q8, Q15, Q20, listed in `docs/EVAL_RESULTS.md`.
- Projected e2e cost (no model called): all 89 cases USD 0.047; tier 1 with `--repeat 2` USD 0.046. Worst case with retries about twice that. Well under the USD 1 cap. Waiting for approval.

### Open issues
- Privacy: while checking the spares currency I printed the workbook's first rows to the terminal. The title row holds a storeman's first name, so one first name appeared in the terminal output. It is not in any loaded source (the loader starts at the header row) and nothing was written to a file. It is a single word, so the guard's term list (full names only) does not screen it. Adding it to `data/guard/extra_terms.txt` would screen it; that needs a decision because a one-word term can block unrelated text.
- Q20 shows a false positive in the new "the <word>" clarification ("the crane sling"). Not fixed because the manager set is held out; it should be fixed with a main-set or unit case first.
- Modules over 300 lines: `conflicts.py` 334, `facts.py` 314, `pipeline.py` 309, `evals/run.py` 305. Each holds one concern; splitting further would scatter related rules.
- `retrieval.py` has two unused locals (`exact_work_order_date`, `work_order_intent` in `retrieve`).
- The `.env` points at the public OpenAI endpoint (`OPENAI_BASE_URL` empty, `gpt-4o-mini`), not a classroom endpoint; the projection uses the configured 0.15 / 0.60 rates.

## Phase 5 corrections (human review, 14 Nov 2026)

1. **No re-baselining to OCR errors.** The team's checked readings are at `data/extraction/06_images_extraction.csv` (git-ignored client data; never committed, copied into docs or tests, or printed with employee codes). N4, N6 and N10 are back to the reference values; V2 is back to the reference too. Every other nameplate and incident case was re-checked against the CSV and agrees with the reference. Cases now carry `ocr_fields`; when such a case fails and the OCR accuracy report finds one of its fields wrong, the runner labels it "OCR data error, fix via OCR Review". `docs/eval_rebaseline.md` was rewritten.
2. **`scripts/ocr_accuracy_report.py`** compares the processed nameplate OCR (structured fields, and the raw OCR text next to the lubricant and grease labels) and the processed incident-form OCR (date, machine, severity, lost days, how reported) with the CSV. Employee codes and descriptions are never read out of the CSV rows. It prints counts by field and the machine or report IDs with the field names that disagree, never values. Its output is not committed. Tests use an invented reference file and check that no value or employee code is printed.
3. **Fixes, each with new main-set cases in `evals/added_cases.yaml` (A1–A8) and unit tests in `tests/test_phase5_fixes.py`:**
   - "the crane sling": a machine word shared by several machines asks which machine only when it stands as the noun ("the crane?", "the crane is ..."), not when it describes something else ("the crane sling", "the crane hook").
   - Relative periods (A14): "last year" is 2025, "this year" and "year to date" 2026, "last month" May 2026, "this month" June 2026. "hurt", "injured" and "accident" are incident words.
   - Ordering: "do we need to order anything urgently", "reorder", "running low", "below minimum" are spares questions. The input guard no longer refuses a question that asks whether to order ("Do we need to order any parts urgently?" was refused as a write); an instruction to order is still refused.
   - Day/night split for V2: a new MySQL source per machine with monthly day and night means. Shift hours are assumed (day 07:00–18:59, night 19:00–06:59, Singapore time) and the source says so.
   - Manager set: its honest pre-fix retrieval score was 15/20. Three manager failures (Q6, Q8, Q20) led to these fixes, so the manager set is no longer fully held out. After the fixes it scores 18/20 in retrieval mode; the manager cases were not edited.
4. The spares workbook was not printed again; only headers and counts.

Results before e2e: unit tests 484, all pass. Offline: all sets pass, refusals 9/9 with no model call. Retrieval: main 66/69 (tier 1 29/29, tier 2 25/27, tier 3 12/13), added 8/8, manager 18/20, legitimate 72/72, hostile 40/40, refusals 8/8 with no model call. Failures: N4 and N10 (OCR data errors), X4, Q3, Q15.

Known weakness: in retrieval mode N6 passes although the OCR misses CNC-01 and CRN-02, because those IDs appear elsewhere in the computed lubricant facts ("unreadable text", "no lubricant read"). `must_include` is a plain substring check; e2e checks the model's wording.

## Phase 5 e2e runs (approved, cap USD 1)

- **First attempt failed without spending.** Every model call raised `APIConnectionError` (cause `UnsupportedProtocol`). `.env` has `OPENAI_BASE_URL=` (empty). The runner passed `base_url=None`, so the OpenAI SDK fell back to the environment variable and got an empty URL. No request reached the API; 86 calls were logged with zero tokens and no cost. The runner also counted those template answers as passes, which was wrong.
- **Fixes:** `evals/run.py` and `app.py` now pass the default endpoint when `OPENAI_BASE_URL` is empty. `app.py` had the same bug, so the Streamlit app could not reach the model with this `.env` either; it showed "The AI endpoint is unavailable" and the template. In e2e mode a case whose model call failed now fails ("model call failed"), instead of passing on the template.
- One 11-token check call confirmed the connection.
- **Tier 1, `--repeat 2`:** projected USD 0.055, actual USD 0.0697. Main 26/29, added 4/5, manager 9/11, refusals 4/4 with no model call. Failures I1, I3, W1, A4, Q1, Q3, the same in both runs.
- **Full main, added and manager sets, once:** projected USD 0.053, actual USD 0.0640. Main 56/69 (tier 1 25/29, tier 2 21/27, tier 3 10/13), added 7/8, manager 16/20, refusals 8/8 with no model call. Gating failures: I1, I2, I3, W1, A4, and tier 2 below 90%. OCR data errors: N4, N6, N10.
- **Total eval spend:** USD 0.1337.
- **Main finding:** the model often drops counts, IDs and caveats that are in the computed facts. The retrieval-mode template carries them. Not fixed in this phase (stop-and-report).
- Projections were about 20% low because retries are not projected.

## Phase 5b: keep the computed figures

### What changed
- `jm_rag/key_figures.py`: for each kind of question, the figures in the computed facts that answer it are marked as required (counts, totals, most-expensive ID and cost, not-closed counts and IDs, counts per type or year, worst-case count and IDs, level counts, near misses with lost days, parts below minimum or out of stock, the month a vibration rise starts, machines per lubricant grade, Fahrenheit conversions) plus caveats written in the facts (unconfirmed scale mapping, assumed currency, data stored in Celsius, data ends 30 Jun 2026). Values are read out of the code-written facts text, so they always pass the number check.
- `jm_rag/drafting.py` (model path moved out of `pipeline.py`): after the draft, code checks every required value is stated. On a miss the single retry lists what is missing (with the value and its [S#]). If the retry still misses values but passes every other check, the model's answer is kept and code appends "Key figures (computed by code): label: value [S#]; ...". The template is used only when the retry breaks another check. An SOP the answer cites but does not name is named by code in a "Source:" line, without a retry.
- `jm_rag/facts.py`: a Fahrenheit question gets code-converted values ("stored in Celsius; converted by code to Fahrenheit").
- Prompt: state every figure from the computed facts that answers the question, with its [S#], including the caveats; name the SOP ID; never say whether a machine is in good shape, healthy or safe, not even in the negative.
- Template: shows only the facts that answer the question (each group's header, clauses holding a required value, clauses on a topic the question names) and, for SOP, audit and monthly sensor sources, the lines matching the question (a procedure question gets the whole short SOP).
- Runner: `must_include` is checked against the answer text only, in every mode (retrieval mode no longer accepts a value found only in the evidence). Projections include 1.3x for retries. The summary also prints the main set without the OCR data-error cases.
- Tests: `tests/test_key_figures.py` (18): required values per question kind, `stated()` number boundaries, the appended line passing the number check, the three paths with a mock model that drops values (complete first answer: 1 call; retry restores: 2 calls; still missing: 2 calls and the appended line; usage and cost for each), unknown price, template still used for other problems, invented number still fails, SOP naming without a retry, and the template showing only relevant facts. One pipeline example case was changed deliberately: "answer: severity scale note" now expects 2 calls and the Key figures line, because its reply leaves out the worst-case count.

### Wording failures (item 5)
- V9 (Fahrenheit): in Phase 5 the model computed Fahrenheit values itself, the number check rejected them twice, and the template (which says `temperature_avg_c`, not "Celsius") answered. General fix: code converts to Fahrenheit and says the data is stored in Celsius. Still failing after the fix, see below.
- Q1 ("Is the compressor in good shape?"): the model wrote "cannot be concluded that the compressor is in good shape" and speculated on the cause. The case's `must_not_include` is a substring check, so a negated phrase also fails it. General fix: the prompt now forbids any condition judgement, even negated. The case was not edited. Still failing, see below.
- Q18 ("Summarise the lockout steps"): the model cited SOP-LOTO-01 but never named it. General fix: code names a cited SOP. Q18 passes now.

### Results
- Unit tests: 502, all pass. Offline: all pass. Retrieval: main 64/69 (tier 1 29/29, tier 2 24/27, tier 3 11/13), added 8/8, manager 18/20, legitimate 72/72, hostile 40/40. The stricter answer-only check exposed N6 as an OCR data error (it had passed on an unrelated substring).
- E2e tier 1 (once): projected USD 0.0366, actual USD 0.0413. Main 29/29, added 5/5, manager 10/11 (Q3), refusals 4/4 with no model call.
- E2e full set (once): projected USD 0.0705, actual USD 0.0720. With the OCR data-error cases: main 62/69 (tier 1 28/29, tier 2 23/27 = 85%, tier 3 11/13). Without N4, N6, N10: main 62/66 (tier 1 28/29, tier 2 23/24 = 96%, tier 3 11/13). Added 8/8, manager 17/20, refusals 8/8 with no model call.
- Phase 5b spend USD 0.1133; total eval spend USD 0.2470.

### Remaining failures and causes
- W1 (tier 1) and V6: the answer gives the data end as `2026-06-30`; the case looks for "30 Jun". `stated()` accepts the ISO form, so code did not append it. Content is right, format differs. A general fix would be a prompt rule to write dates as "30 Jun 2026" and making that the only accepted form for the data-end caveat.
- V9: the answer wrote "°C", which `stated()` accepts for the Celsius caveat, so the word "Celsius" was not added. Fix: accept only "Celsius".
- Q1: the model still writes "does not support a conclusion that the compressor is in good shape" despite the prompt rule. The case's substring check fails on a negated sentence.
- Q3, Q15, X4: pipeline gaps (summary has no oil conflict; machines without sensors not listed; cross-source question).
- N4, N6, N10: OCR data errors (fix via OCR Review).
These were found after the approved reruns and are not changed yet, so the results above match the committed code.

## Phase 5c: date format, Celsius, condition judgements

- Prompt: write dates as "30 Jun 2026", never "2026-06-30". The data-end caveat now accepts only "30 Jun 2026"; the Celsius caveat accepts only the word "Celsius" (not "°C").
- `validator.CONDITION_JUDGEMENTS` (one list): "in good shape", "good condition", "healthy", "safe to run", "safe to use", "no problems", "working fine" and similar. For a question flagged `inference_request`, a draft using any of them, even in a negated sentence, fails the post-check; the retry gets the phrases and the reason; if the retry uses one again, the template answers. Other questions are not checked ("no problems recorded in its nameplate fields" is fine there). "safe working load" and "condition" alone are not judgements.
- Tests: `tests/test_condition_check.py` (9): every listed phrase, negated sentences, legitimate sentences that pass, retry-then-keep, negated twice then template, not applied to other questions, the date rule in the prompt, the data-end and Celsius options.
- No case edited. Unit tests 511, all pass. Offline and retrieval unchanged from 5b (retrieval main 64/69, tier 1 29/29; 64/66 without N4, N6, N10).
- E2e tier 1, once: projected USD 0.0368, actual USD 0.0399. Main 29/29, added 5/5, manager 10/11 (Q3), refusals 4/4 with no model call. W1 and Q1 now pass. V3 passed on the template answer. Total eval spend USD 0.2870.
## Phase 6: app on the pipeline, cost monitoring, request log, multi-turn
### What changed
- `app.py`: the Assistant tab calls `jm_rag.pipeline.answer_question`. The input guard runs first; a refusal passes an empty corpus, so no evidence is loaded. The OpenAI client is created only on the first model call (`LazyClient`), so table, refusal and not-found answers create no client. An empty `OPENAI_BASE_URL` falls back to the OpenAI default. Each answer shows an outcome badge (Answer, Conflict, Cannot answer fully, Refused, Needs clarification, Source unavailable), the answer, the code-added notes in a separate info box, the evidence panel as before, and a cost caption. The sidebar shows "Last answer cost", "Session total" and "Today (all users and evals)", plus a warning at 80% of a budget and an error at the limit. OCR Review and Sensor Trends are unchanged except imports.
- `jm_rag/observability.py`: per-call tokens and cost (retries included); `log_request` writes `logs/requests.jsonl` (time, request ID, chat ID, source, outcome, refusal class, calls, tokens, cost, latency, question length and a 16-character sha256; no question text, no answer text, no names); `log_spend` writes `logs/spend.jsonl` for evals and non-chat calls; `spend_summary()` combines chat spend from MySQL with `spend.jsonl`; `budget_status()` reads optional `DAILY_BUDGET_USD` and `TOTAL_BUDGET_USD` (both unset); `python -m jm_rag.observability` prints the spend report. A missing price is stored as unknown, never as 0.
- `scripts/chat_history.py`: `chat_messages` gains `cost_usd DECIMAL(14,8) NULL` and `outcome VARCHAR(16) NULL` through an idempotent migration (checks information_schema before each ALTER). Run twice against the live database; the second run changed nothing.
- `jm_rag/pipeline.py`: `budget_blocked=True` answers without the model and says so. A resolved follow-up ("and CNC-03?" after "What oil does CNC-02 take?") now uses the rewritten question for conflict detection, mandatory notes and topic detection, not only for retrieval. Before, the follow-up retrieved the right sources but got outcome "answer" with no lubricant conflict, while the full question got "conflict". Found while checking the demo questions; a test shows it.
- `evals/run.py`: eval spend goes through `observability.log_spend`.
### Tests
- `tests/test_observability.py` (18): cost arithmetic with a mock usage object, unknown price, retries counted, request-log fields with no question or answer text, spend summary from fake chat rows and `spend.jsonl`, budget warning and limit, the migration run twice, multi-turn (machine switch, year switch, follow-up outcome and notes equal to the full question), and a restart test: two separate processes share one chat ID through the live MySQL chat tables (skipped when MySQL is unreachable; the test chat is deleted).
- `tests/test_app_phase6.py` (7 AppTests with fakes): badges, notes box and cost caption; a refusal with no model call and no cost; one request line without text per question; the budget warning at 80%; code-only answers at the limit; no budget message when no limit is set.
- Deliberate edits to existing tests: in `tests/test_guardrails.py` the fake `append_chat_turn` accepts `cost_usd` and `outcome`; "what lubricant does TST-01 take" became "what is the serial number of TST-01" in 4 places, because lubricant questions now carry required values and notes that those tests do not check; the clean-answer test asserts the answer starts with "Oil-A [S1]" and the outcome is "answer".
- Carry-over for the machine and the year already existed in `jm_rag/followup.py`; only the conflict and notes step was missing (see above).
### Results
- Unit tests: 536, all pass.
- Offline eval: offline 20/20, refusals 9/9 with 0 model calls, legitimate 72/72, hostile 40/40.
- Retrieval eval: main 64/69 (tier 1 29/29), 64/66 without N4, N6, N10; added 8/8; manager 18/20; legitimate 72/72; hostile 40/40; refusals 8/8. Failures as before: N4, N6, N10 (OCR data errors), V8, X4, Q3, Q15.
- Live AppTest (real MySQL, real model for one question): "What is the serial number of MILL-01?" got Answer and the caption "This answer: 2310 tokens, $0.000358", with the sidebar metrics filled; the names-of-injured question got Refused with no model call; "Show work orders for CNC-99" got Cannot answer fully with no model call. No exceptions; three request-log lines with the right outcomes. The test chat was deleted afterwards.
- No e2e run in this phase. Phase 6 model spend: USD 0.000358 (the one live AppTest answer).
- `docs/MANUAL_DEMO_CHECK.md`: ten questions for a manual check in the running app, with the expected badge, notes and cost for each. The expected outcomes were checked against the real data with the model switched off.
## Phase 7: documentation and evidence
- New: `docs/ASSUMPTIONS.md`, `docs/QUESTION_CATALOGUE.md`, `docs/ARCHITECTURE.md` (2 Mermaid diagrams), `docs/DATA_QUALITY.md`, `docs/POSTMORTEM_DRAFT.md`. Rewritten: `docs/EVAL_RESULTS.md`. `README.md`: new Windows quick start (clean clone to running app), and sections on tests, evals, the name screening list, logs and the spend report, environment and budget variables, OCR import and review, and known limits. The old prototype section was replaced, because it said persisted chats and cost accounting were still to be done.
- `docs/ASSUMPTIONS.md` is adapted from the reference register. Kept, in adapted form: A1 to A10, A11 (rewritten for this repo's model access), A14 and A15. Dropped: A12 (folded into A3), A13 and A16 (vision-model readings). Added: A17 (TF-IDF retrieval), A18 (Tesseract OCR and its measured accuracy), A19 (OCR review tables), A20 (name screening list), A21 (prices).
- Checked against the code while writing. These differ from the reference or the plan:
  - The shift hours in code are 07:00 to 18:59, not 07:00 to 19:00.
  - "Recently" is not mapped to a date window; it means newest first.
  - The order of trust is written into each conflict note, not into the prompt.
  - `ocr_review_decisions` holds no decisions yet.
  - The `DATA_END` comment in `jm_rag/config.py` says it is unused, but it is used. The comment was not changed.
- `docs/QUESTION_CATALOGUE.md` is generated from the three case files (97 cases). Lubricant grades and brands, part numbers and employee codes in question wording are replaced by placeholders.
- OCR accuracy, from `python -m scripts.ocr_accuracy_report` (counts only): 66 of 113 structured nameplate fields, 17 of 24 raw-text readings and 121 of 150 incident-form fields match.
- No code changed and no case edited. Unit tests 536, all pass. Offline: all pass. Retrieval: main 64/69 (tier 1 29/29), 64/66 without N4, N6, N10; added 8/8; manager 18/20; legitimate 72/72; hostile 40/40; refusals 8/8. No e2e run; no model spend in this phase.
