# Eval results

Latest run: 14 Nov 2026, branch `enhance/rag-hardening`. Counts only. Commands from `evals/README.md`.

## Offline (`python -m evals.run --mode offline`)

Fixture corpus, scripted mock model, no MySQL, no network.

| Set | Passed |
|---|---|
| offline cases | 20/20 |
| main set, refusal cases only | 7/7 |
| manager set, refusal case only | 1/1 |
| legitimate questions (never refused) | 72/72 |
| hostile prompts (23 ported + 17 own) | 40/40 |
| refusal cases | 9/9, 0 model calls |

Mock usage: 10 model calls, 900 prompt + 180 completion tokens, no price configured for the mock.

## Retrieval (`python -m evals.run --mode retrieval`)

Live MySQL and files, no model; answers are the deterministic tables and template.

| Set | Passed | Tier 1 | Tier 2 | Tier 3 |
|---|---|---|---|---|
| main (69) | 68 | 29/29 | 27/27 | 12/13 |
| manager (20, held out) | 15 | 7/11 | 8/9 | n/a |
| legitimate questions (72) | 72 | | | |
| hostile prompts (40) | 40 | | | |
| refusal cases | 8/8, 0 model calls | | | |

Cost: 0 model calls, USD 0.

Eight main cases passed with at least one `must_include` value found only in the retrieved evidence or computed facts, not in the answer text (N4, V8, V9, P1, P2, P3, P4, P6). Without a model the template lists records rather than phrasing an answer; e2e checks the answer text itself.

### Failures

| Case | Set | Tier | Expected | Got | Note |
|---|---|---|---|---|---|
| X4 | main | 3 | answer with "30 Jun" | answer without it | "Which machines have open work orders but no sensor data?" goes to the work-order table, which carries no data-end date. Cross-source join not implemented. |
| Q3 | manager | 1 | conflict | answer | "Quick summary of CNC-02" does not retrieve the oil, so the `ALL` lubricant conflict is not raised. |
| Q6 | manager | 1 | BRG-6310, LS-CXT-11 | missing | "Do we need to order anything urgently?" is not read as a spares question. |
| Q8 | manager | 1 | 34 | missing | "last year" is not resolved to 2025 (plan assumption A14 is not implemented yet). |
| Q15 | manager | 2 | BLAST-01 | missing | The answer lists the machines with sensors but not the ones without. |
| Q20 | manager | 1 | abstain | clarify | False positive in the new "the <word>" machine clarification: "the crane sling" is read as an ambiguous crane (CRN-01 or CRN-02). |

The manager cases are held out and were not used to tune anything; these failures are reported, not fixed.

## End to end

Not run yet. Projected (no model called): all 89 main and manager cases, about 78 model calls, 266,444 prompt + 11,700 completion tokens, USD 0.047 at the configured 0.15 / 0.60 USD per 1M tokens. Tier 1 with `--repeat 2`: 74 calls, USD 0.046. Retries can add up to one call per case, so the worst case is about twice these figures.
