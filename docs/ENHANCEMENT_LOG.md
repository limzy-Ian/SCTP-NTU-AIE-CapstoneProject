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
