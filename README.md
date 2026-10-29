# Jurong Marine Services — AI Engineering Capstone (team7_jurong_marine)

Your team is the forward-deployed engineering unit for **Jurong Marine Services**. Your job: build the
safety & maintenance agent described in [CLIENT_BRIEF.md](CLIENT_BRIEF.md) and survive a live demo with the
customer on **Sat 21 Nov 2026**.

## Quick start

```bash
git clone <this repo>
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
