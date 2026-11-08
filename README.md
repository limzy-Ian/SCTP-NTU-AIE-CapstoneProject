# Jurong Marine Services — AI Engineering Capstone (team7_jurong_marine)

Your team is the forward-deployed engineering unit for **Jurong Marine Services**. Your job: build the
safety & maintenance agent described in [CLIENT_BRIEF.md](CLIENT_BRIEF.md) and survive a live demo with the
customer on **Sat 21 Nov 2026**.

## Quick start

```bash
git clone https://github.com/fde-sctp-aieng-PT-Cohort1/team7_jurong_marine.git
cd team7_jurong_marine
python3 -m venv .venv && source .venv/bin/activate
cp .env.example .env          # paste in your team API key (handed out at the briefing)
# download your team zip from NTULearn and unzip into data/  (see data/README.md)
docker compose up -d          # local MySQL — or use MySQL Workbench directly
docker compose exec -T mysql mysql -uroot -pcapstone < data/sql/<dump>.sql
```

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

## Maintenance chatbot prototype (Windows)

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-chatbot.txt
# Set MYSQL_* and your supplied OPENAI endpoint/model in .env; see .env.example.
.\.venv\Scripts\python.exe scripts/nameplate_ocr_import.py --limit 12
.\.venv\Scripts\python.exe -m unittest discover -s tests
.\.venv\Scripts\python.exe -m streamlit run app.py
```

`--dry-run` generates local evidence only. Without it the importer upserts raw
OCR and parsed records into MySQL staging; it never changes the CMMS machines.
Review image evidence before trusting any OCR specification. Reimporting replaces
the staging extraction, not human-approved production data.

The read-only chatbot retrieves live MySQL nameplate records joined to machines,
and local SOP text using TF-IDF (no paid embedding service). Each response includes
retrieved evidence and source citations. With no API key it displays evidence only.
Use the classroom endpoint via `OPENAI_BASE_URL` and its supported `OPENAI_MODEL`;
do not provision another paid service. Only selected evidence is sent to that endpoint.

This is a nameplate/SOP prototype, not the full grading harness: sensor and incident
analytics, spreadsheet ingestion, persisted conversations, durable traces/cost
accounting and comprehensive guardrail/evaluation coverage remain to be implemented.
Citation validation checks source IDs, not factual entailment. Conversation state
and token counts last only for the current Streamlit session. All real-world actions
are out of scope; the app neither approves work nor modifies equipment records.

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
