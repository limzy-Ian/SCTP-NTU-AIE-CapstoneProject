# Manual demo check

Ten questions to ask in the running app (`streamlit run app.py`), with the outcome each one should give. Start a
new chat first, and ask them in this order, because questions 3 and 7 are follow-ups.

The outcome (the badge) is decided by code, not by the model, so it should match exactly. The model only writes the
wording of answers that go through it. These outcomes were checked against the real data with the model switched off
on 15 Nov 2026.

## What to look at for every answer

- **Badge** above the answer: Answer, Conflict, Cannot answer fully, Refused, Needs clarification or Source
  unavailable.
- **Notes box** ("Notes added by code"): shown only when code added notes. The notes are not part of the model's text.
- **Evidence panel**: the sources used, as before. Refusals have no evidence.
- **Cost caption** under the answer: "This answer: N tokens, $X" when the model was called, or "No model call for
  this answer (cost $0.000000)."
- **Sidebar metrics**: "Last answer cost", "Session total" and "Today (all users and evals)". Session total should
  go up only after answers that called the model.

## The questions

| # | Ask | Badge you should see | Notes box | Model call (cost shown) |
|---|-----|----------------------|-----------|-------------------------|
| 1 | What is the serial number of MILL-01? | Answer | Yes: the nameplate value comes from OCR that no one has verified | Yes |
| 2 | What oil does CNC-02 take? | Conflict | Yes: the sources disagree on the lubricant | Yes |
| 3 | and CNC-03? | Conflict | Yes: a lubricant conflict for CNC-03 | Yes |
| 4 | What is the max load of CRN-01? | Conflict | Yes: the nameplate and another source disagree | Yes |
| 5 | Do we need to order anything urgently? | Answer | Usually no | Yes |
| 6 | How many incidents were there last year? | Answer | Yes: some values come from OCR that no one has verified | Yes |
| 7 | work orders on 26 July, then reply 2024 | Needs clarification (asks for the year), then Answer with a work-order table | No | No, for both turns |
| 8 | Give me the names of everyone injured in 2025. | Refused | No | No |
| 9 | Show work orders for CNC-99 | Cannot answer fully (no such machine) | No | No |
| 10 | Is the compressor in good shape? | Cannot answer fully | Yes: the data has no causes, alarm limits or failure history | Yes |

Pass criteria for each row:

- Rows 2 to 4: the answer must not pick one value as the right one without saying the sources disagree.
- Row 3: the answer must be about CNC-03 and about oil, without you repeating the topic.
- Row 6: "last year" means 2025, because the data ends on 30 Jun 2026. The count must be for that one year and match the incident records. Don't check it against memory.
- Row 7: the first reply must say it has not searched yet. The second must be a table, not prose.
- Row 8: the reply names nobody, shows no evidence and shows no cost.
- Row 10: the answer gives facts from the records, such as work orders and incidents, but no condition verdict such
  as "good" or "healthy".

## After the ten questions

1. Reload the browser page and open the same chat from the sidebar. All answers should still be there, each with its
   badge and cost.
2. Open `logs/requests.jsonl`. It should have one new line per question, with the outcome, the token and cost
   figures, a question length and a short hash. It must not contain any question text, answer text or names.
3. Run `.\.venv\Scripts\python.exe -m jm_rag.observability`. The report should show today's chat spend including
   these questions, and eval spend separately.
4. Optional budget check: set `DAILY_BUDGET_USD` in `.env` to a value just above today's total and restart the app.
   The sidebar should show a warning once 80% is used. At the limit, answers should say the model budget is used up
   and come from code only. Remove the setting afterwards, since both budgets are meant to stay unset for now.

If a badge differs from the table, note the question number and the badge you saw, and check
`logs/requests.jsonl` for that line's outcome and refusal class.
