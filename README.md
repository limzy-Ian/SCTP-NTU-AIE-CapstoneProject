# Jurong Marine Services — AI Engineering Capstone (team7_jurong_marine)

Your team is the forward-deployed engineering unit for **Jurong Marine Services**. Your job: build the
safety & maintenance agent described in [CLIENT_BRIEF.md](CLIENT_BRIEF.md) and survive a live demo with the
customer on **Sat 21 Nov 2026**.

## Quick start

Windows PowerShell, from a clean clone to a running app. Each step is explained in [docs/setup-windows.md](docs/setup-windows.md); on Mac or Linux use `python3 -m venv .venv`, `source .venv/bin/activate`, `cp` and `<` instead.

Prerequisites: Python 3, Docker Desktop, and [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki) (default path `C:\Program Files\Tesseract-OCR\tesseract.exe`, or set `TESSERACT_CMD` in `.env`).

```powershell
git clone https://github.com/fde-sctp-aieng-PT-Cohort1/team7_jurong_marine.git
cd team7_jurong_marine
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-chatbot.txt -r requirements-eval.txt
Copy-Item .env.example .env        # add the team API key; prices and budgets are optional (see below)
# Unzip the team package from NTULearn into data\ (docs, images, logs, sql, tabular). See data\README.md.

# 1. Database
docker compose up -d
cmd /c "docker compose exec -T mysql mysql -uroot -pcapstone < data\sql\jurongmarine_cmms.sql"

# 2. Derived data: OCR staging, processed OCR and sensor tables (local only, git-ignored)
python scripts/nameplate_ocr_import.py
python scripts/ingest_incident_reports.py --images-dir data/images/incident_reports --commit
python scripts/sensor_csv_to_mysql.py --input data/logs/vibration_temp_2026H1.csv --load-mysql

# 3. Name screening list (read-only query on employees; prints counts only)
python -m scripts.build_guard_terms

# 4. Check and run
python -m unittest discover -s tests
python -m evals.run --mode offline
python -m streamlit run app.py
```

The app opens at http://localhost:8501 with three tabs: Assistant, OCR Review and Sensor Trends. Without an API key it still answers from code (tables and evidence lists) and says the AI endpoint is not configured.

## Rules of engagement

1. **No client data in git.** `data/` is git-ignored; keep it that way. Same for `.env` and your API key.
2. **Five-way contribution.** Team-process marks are graded from commit history — every member commits real work. Pair-programming is fine; say so in commit messages (`Co-authored-by:`).
3. **Budget.** Your API key has a hard budget. Watch your spend; a burned key is not replaced.
4. **Cite everything.** Answers your app gives must say where the fact came from. See [HARNESS_CHECKLIST.md](HARNESS_CHECKLIST.md) — it is the grading rubric in checklist form.

## Deliverables

- Working application (live demo; a judging panel plays your customer and asks unscripted questions)
- Architecture documentation with **at least two Mermaid diagrams** (in `docs/`)
- Data quality report: every trap you found and how you handled it
- 5-minute pitch
- Honest post-mortem (what you'd do differently)

## Timeline

Briefing Sat 31 Oct · Week-1 checkpoint Thu 5 Nov · Week-2 checkpoint Sat 14 Nov · Final sprint Fri 20 Nov · **Demo Sat 21 Nov** (per-team slots to be scheduled). Details: [CHECKPOINTS.md](CHECKPOINTS.md).

Updated docker-compose.yml and shared instruction for "6. Load the database" and check with DBearver.

## Maintenance assistant

All commands below run from the repo root with the virtual environment (`.\.venv\Scripts\python.exe` or an activated `python`).

The Assistant tab sends each question through `jm_rag.pipeline.answer_question`. Code decides what is refused, which caveats are shown, whether the model's draft is acceptable, and the outcome badge (Answer, Conflict, Cannot answer fully, Refused, Needs clarification, Source unavailable). The model only phrases answers from evidence that code retrieved (TF-IDF, no embeddings) and then checks. Work-order and incident tables are built by code without a model call. The assistant is read-only: it never writes to the CMMS tables. OCR corrections are made by a person in the OCR Review tab and stored separately in `ocr_review_decisions`; raw OCR and the CMMS tables are not changed. How it works: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

Documentation:

| File | Contents |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Request pipeline and component diagrams; guardrails, validator, computed facts, fallbacks, cost monitoring, logs |
| [docs/ASSUMPTIONS.md](docs/ASSUMPTIONS.md) | Assumptions register and open questions for the client |
| [docs/DATA_QUALITY.md](docs/DATA_QUALITY.md) | Every data trap found and how the app handles it |
| [docs/QUESTION_CATALOGUE.md](docs/QUESTION_CATALOGUE.md) | The eval questions with expected outcome and tier |
| [docs/EVAL_RESULTS.md](docs/EVAL_RESULTS.md) | Latest eval results and spend |
| [docs/MANUAL_DEMO_CHECK.md](docs/MANUAL_DEMO_CHECK.md) | Ten questions to check in the running app |
| [docs/ENHANCEMENT_LOG.md](docs/ENHANCEMENT_LOG.md) | What changed in each phase, and why |
| [docs/POSTMORTEM_DRAFT.md](docs/POSTMORTEM_DRAFT.md) | Post-mortem outline |

### Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests
```

No model and no network. Most tests use the invented fixture corpus in `tests/fixtures/`. A few use the local MySQL (the chat restart test) and are skipped when it is not reachable.

### Evals

```powershell
.\.venv\Scripts\python.exe -m evals.run --mode offline                 # fixture corpus and a scripted mock model; no MySQL, no cost
.\.venv\Scripts\python.exe -m evals.run --mode retrieval               # live MySQL and files, no model, no cost
.\.venv\Scripts\python.exe -m evals.run --mode e2e --project-only      # prints the projected e2e cost; calls no model
.\.venv\Scripts\python.exe -m evals.run --mode e2e --tier 1 --repeat 2 # live data and the model (costs money)
```

`retrieval` and `e2e` need the name screening list (next section). An e2e run prints its projected cost first and stops if the projection is above `--cap` (default USD 1) unless `--yes` is given. Options, case format and gating rules: [evals/README.md](evals/README.md). Results are written to `evals/out/` (git-ignored).

### Name screening list

```powershell
.\.venv\Scripts\python.exe -m scripts.build_guard_terms
```

It reads employee names from MySQL (read-only) and writes `data/guard/name_terms.json` (git-ignored). It prints counts only. To screen a name of someone who is not in the `employees` table, add it on its own line to `data/guard/extra_terms.txt` (git-ignored; lines starting with `#` are ignored) and run the command again. Without the list the app still runs, but the sidebar warns that names cannot be screened.

### Logs and the spend report

- `logs/requests.jsonl`: one JSON line per question asked in the app, with the request and chat IDs, outcome, refusal class, source IDs and types, model calls, tokens, cost, timings and error count. It stores only the question's length and a short hash, never the question or answer text.
- `logs/spend.jsonl`: one JSON line per eval case (or other non-chat use) that called the model, with mode, case ID, model, calls, tokens and cost.
- Chat costs are stored with each answer in the MySQL `chat_messages` table.
- `logs/` is git-ignored. The field lists are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#logs).

```powershell
.\.venv\Scripts\python.exe -m jm_rag.observability
```

This prints spend for today, the last 7 days and all time, split into chat, eval and other, plus the budget status and the five most expensive requests. The app shows the same figures in the Assistant sidebar ("Last answer cost", "Session total", "Today (all users and evals)") and the cost under each answer.

### Environment variables

| Variable | Needed | Meaning |
|---|---|---|
| `OPENAI_API_KEY` | for model answers | Without it the app answers from code only. |
| `OPENAI_BASE_URL` | no | Empty means the OpenAI default URL. |
| `OPENAI_MODEL` | no | Default `gpt-4o-mini`. |
| `OPENAI_INPUT_COST_PER_1M_USD`, `OPENAI_OUTPUT_COST_PER_1M_USD` | for costs | Token prices in USD per 1M tokens. Without them, costs show as unknown, except for `gpt-4o-mini` on the default URL. |
| `DAILY_BUDGET_USD` | no | Spend limit for the current UTC day, chat and evals together. |
| `TOTAL_BUDGET_USD` | no | Spend limit for all time. |
| `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_DATABASE`, `MYSQL_USER`, `MYSQL_PASSWORD` | yes | Local MySQL (defaults in `.env.example`). |
| `TESSERACT_CMD` | if Tesseract is not on the default path | Path to `tesseract.exe` for the OCR import scripts. |
| `MAX_QUESTION_CHARS` | no | Longest question accepted (default 500). |
| `OCR_REVIEWER` | no | Default reviewer initials in the OCR Review tab. |

Budgets: leave both unset for no limit (the current setting). When one is set, the sidebar warns at 80% of it. At the limit the app stops calling the model and answers from code, with a note saying the model budget is used up. The limits apply to the app; eval runs use `--cap` instead.

### OCR import and review

`scripts/nameplate_ocr_import.py` (`--dry-run` writes local files only) and `scripts/ingest_incident_reports.py` (`--commit` writes to MySQL) read the images with Tesseract and write raw OCR and parsed records to the MySQL staging tables. They never change the CMMS tables. In the **OCR Review** tab a person compares each extraction with its image, approves, rejects or corrects it, and gives their initials. Only approved values are marked HUMAN-VERIFIED in the assistant's evidence; everything else is shown as unverified OCR. `python -m scripts.ocr_accuracy_report` compares the processed OCR with the team's checked reference readings (`data/extraction/`, git-ignored) and prints counts only.

### Known limits

- No user login. Saved chats are shared by everyone using the same MySQL database.
- Retrieval is keyword-based (TF-IDF); a paraphrase with no shared words can miss evidence.
- OCR values are often wrong until reviewed; see [docs/DATA_QUALITY.md](docs/DATA_QUALITY.md).
- The sensor charts and summaries are descriptive. No alert thresholds are configured, and the app does not diagnose faults.

## Compare EasyOCR and Tesseract

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ocr-comparison.txt
.\.venv\Scripts\python.exe scripts/compare_ocr.py --limit 1
.\.venv\Scripts\python.exe scripts/compare_ocr.py
```

The comparison is offline and never calls the MySQL upload functions. EasyOCR
downloads English model weights on first use; images remain local. CPU is the
default (`--gpu` is optional). `--limit` applies separately to each image category.
Both engines share the existing nameplate preprocessing and incident field crops,
then use the same parsers. Normal import commands still use Tesseract.

Results are under `data/processed/ocr_comparison/` (git-ignored):

- `nameplate_comparison.csv` and `incident_comparison.csv`: one image per row,
	side-by-side parsed values, native confidence, review flags and processing time.
- `field_comparison.csv`: one field per row, highlighting agreement or missing values.
- `engine_summary.csv` and `comparison.md`: completeness, timings and reviewed accuracy.
- `raw_results.jsonl`: original OCR evidence and extraction results for both engines.
- `ground_truth_template.csv`: fill expected values from the images and set `reviewed=yes`.
	Repeated runs preserve existing template entries and add missing ones.

After reviewing the template, score saved results without repeating model inference:

```powershell
.\.venv\Scripts\python.exe scripts/compare_ocr.py --score-only --ground-truth data/processed/ocr_comparison/ground_truth_template.csv
```

Confidence scales are not comparable and agreement is not proof of correctness.
Accuracy remains blank until ground truth is reviewed. Matching ignores case and
whitespace; numeric fields use decimal equivalence. OCR tags/report numbers are
compared without filename fallback. Severity scale and scale source are separate
fields. Shared confidence review thresholds are not calibrated for EasyOCR.
Timing excludes model initialization/download, includes image decoding and parsing,
and uses fixed engine order; repeat runs before drawing speed conclusions.
