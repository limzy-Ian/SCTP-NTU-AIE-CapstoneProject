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
