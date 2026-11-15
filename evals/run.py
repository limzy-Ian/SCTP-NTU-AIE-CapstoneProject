"""Run the eval cases. One command per mode (see evals/README.md).

  python -m evals.run --mode offline                      fixture corpus, scripted mock model, no MySQL, no cost
  python -m evals.run --mode retrieval                    live MySQL and files, no model, no cost
  python -m evals.run --mode e2e --project-only           projected e2e cost only; no model is called
  python -m evals.run --mode e2e --tier 1 --repeat 2      live MySQL and the classroom model (costs money)

Writes evals/out/<timestamp>-<mode>.json and exits non-zero when a gating check fails. Every model call is also
appended to logs/spend.jsonl with source "eval". An e2e run prints its projected cost first and stops when the
projection is above the cap (default USD 1) unless --yes is given.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evals import hostile  # noqa: E402
from evals.checks import check_case  # noqa: E402
from jm_rag import observability  # noqa: E402
from jm_rag.guardrails import names  # noqa: E402
from jm_rag.pipeline import answer_question  # noqa: E402

EVALS = Path(__file__).parent
OUT = EVALS / "out"
SETS = {"main": "cases.yaml", "added": "added_cases.yaml", "manager": "manager_cases.yaml", "legit": "legit_regression.yaml",
        "offline": "offline_cases.yaml"}
MODE_SETS = {"offline": ["offline", "main", "added", "manager", "legit", "hostile"],
             "retrieval": ["main", "added", "manager", "legit", "hostile"], "e2e": ["main", "added", "manager"]}
OCR_LABEL = "OCR data error, fix via OCR Review"
DEFAULT_CAP_USD = 1.0
DEFAULT_BASE_URL = "https://api.openai.com/v1"
ASSUMED_RATES = (0.15, 0.60)          # USD per 1M tokens, only used to project a cost when none is configured
ASSUMED_COMPLETION_TOKENS = 150
RETRY_FACTOR = 1.3   # the Phase 5 runs cost about 1.2x the one-call projection because of retries
FAKE_NAMES = ["Zed Quarrel", "Pim Vesper"]


def load_set(name: str) -> list[dict]:
    if name == "hostile":
        return [{"id": f"H{i}", "tier": 1, "question": prompt, "expect_any": True, "set": "hostile"}
                for i, prompt in enumerate(hostile.PORTED + hostile.OWN, 1)]
    cases = yaml.safe_load((EVALS / SETS[name]).read_text(encoding="utf-8")) or []
    for case in cases:
        case["set"] = name
    return cases


def offline_reply(text: str):
    """Scripted model reply: ``[[fragment]]`` becomes the [S#] of the retrieved source whose title has the fragment."""
    def reply(kwargs):
        evidence = []
        for message in reversed(kwargs["messages"]):
            if "Retrieved evidence:\n" in message["content"]:
                evidence = json.loads(message["content"].split("Retrieved evidence:\n", 1)[1])
                break

        def cite(match):
            for source in evidence:
                if match.group(1).lower() in source["title"].lower():
                    return f"[{source['id']}]"
            raise AssertionError(f"no source with {match.group(1)!r} in the prompt")
        return re.sub(r"\[\[(.+?)\]\]", cite, text)
    return reply


def make_client(mode: str, case: dict, e2e_client):
    if mode == "e2e":
        return e2e_client
    if mode == "offline" and case.get("reply") is not None:
        from tests.mock_client import MockClient
        replies = case["reply"] if isinstance(case["reply"], list) else [case["reply"]]
        return MockClient([RuntimeError("scripted model failure") if r == "!error" else offline_reply(r) for r in replies])
    return None


def run_case(case: dict, corpus, mode: str, e2e_client, model: str | None) -> dict:
    turns = case.get("turns") or [case["question"]]
    history, result, started = [], None, time.perf_counter()
    calls = prompt = completion = 0
    cost, known = 0.0, True
    for question in turns:
        result = answer_question(question, history, corpus, make_client(mode, case, e2e_client), model=model)
        usage = result["usage"]
        calls, prompt, completion = calls + usage["calls"], prompt + usage["prompt"], completion + usage["completion"]
        if usage["calls"] and usage["cost_usd"] is None:
            known = False
        cost += usage["cost_usd"] or 0.0
        history += [{"role": "user", "content": question}, {"role": "assistant", "content": result["answer"]}]
    result["usage_total"] = {"calls": calls, "prompt": prompt, "completion": completion,
                             "cost_usd": cost if (known and calls) else (0.0 if not calls else None)}
    result["ms"] = int((time.perf_counter() - started) * 1000)
    return result


def judge(case: dict, result: dict, mode: str) -> list[str]:
    if case["set"] == "hostile":
        return hostile.judge(case["question"], result)
    if case["set"] == "legit":
        return [] if result["outcome"] != "refuse" else [f"refused ({result['refusal_class']})"]
    shaped = {**result, "usage": result["usage_total"]}
    model_errors = [error for error in result.get("errors", []) if error.startswith("model unavailable")]
    if mode == "e2e" and model_errors:     # a template answer is not an end-to-end pass
        return [f"model call failed: {model_errors[0]}"]
    # must_include is checked against the answer only, also without a model: the template answer shows just the facts
    # that answer the question, so a value that sits in some unrelated part of the evidence cannot satisfy a check.
    fails = check_case(case, shaped, evidence_in_text=False, llm_allowed=mode == "e2e")
    # how many must_include entries were found only in the evidence, not in the answer text (lenient without a model)
    from evals.checks import has
    result["evidence_only"] = [spec for spec in case.get("must_include", []) if not has(result["answer"], spec)
                               and not any(spec in item for item in fails)]
    return fails


def log_spend(case: dict, mode: str, model: str, usage: dict) -> None:
    """Eval model spend goes to logs/spend.jsonl with source "eval" (jm_rag.observability), beside non-chat spend."""
    observability.log_spend(source="eval", usage=usage, model=model, ref=case["id"], mode=mode)


class DryClient:
    """Records the size of every prompt and raises, so the pipeline falls back to the template. Used to project cost."""

    def __init__(self):
        self.chars = []
        from types import SimpleNamespace
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.chars.append(sum(len(message["content"]) for message in kwargs["messages"]))
        raise RuntimeError("dry run")


def project_cost(cases: list[dict], corpus, model: str, repeat: int) -> dict:
    dry = DryClient()
    for case in cases:
        run_case(case, corpus, "e2e", dry, model)
    prompt = int(sum(chars // 4 for chars in dry.chars) * repeat * RETRY_FACTOR)
    completion = int(ASSUMED_COMPLETION_TOKENS * len(dry.chars) * repeat * RETRY_FACTOR)
    rates, assumed = observability.api_cost_rates(model), False
    if rates is None:
        rates, assumed = ASSUMED_RATES, True
    return {"cases": len(cases), "model_calls": round(len(dry.chars) * repeat * RETRY_FACTOR), "prompt_tokens": prompt, "completion_tokens": completion,
            "cost_usd": (prompt * rates[0] + completion * rates[1]) / 1_000_000, "rates": rates, "assumed_rates": assumed}


def build_e2e_client():
    import os
    from dotenv import load_dotenv
    from openai import OpenAI
    load_dotenv(ROOT / ".env", override=True)
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is not set; e2e needs the classroom endpoint.")
    # An empty OPENAI_BASE_URL in .env must not reach the client: the SDK reads the variable itself and fails with
    # "UnsupportedProtocol" on an empty URL, so the default endpoint is passed explicitly.
    return OpenAI(api_key=os.environ["OPENAI_API_KEY"], base_url=os.getenv("OPENAI_BASE_URL") or DEFAULT_BASE_URL,
                  timeout=30, max_retries=1)


def select(args) -> list[dict]:
    chosen = args.set.split(",") if args.set else MODE_SETS[args.mode]
    cases = []
    for name in chosen:
        for case in load_set(name):
            if args.mode == "offline" and name in ("main", "added", "manager") and not case.get("no_llm"):
                continue        # data-dependent cases need the live corpus; offline keeps the refusals
            cases.append(case)
    if args.file:
        cases = [{**case, "set": "main"} for case in yaml.safe_load(Path(args.file).read_text(encoding="utf-8"))]
    if args.tier:
        tiers = {int(tier) for tier in args.tier.split(",")}
        cases = [case for case in cases if case.get("tier", 1) in tiers]
    if args.id:
        ids = {item.strip().upper() for item in args.id.split(",")}
        cases = [case for case in cases if case["id"].upper() in ids]
    return cases


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["offline", "retrieval", "e2e"], required=True)
    parser.add_argument("--set", help="comma list of main, manager, legit, offline, hostile (default depends on mode)")
    parser.add_argument("--file", help="run one case file instead of the default sets")
    parser.add_argument("--tier", help="comma list, for example 1 or 1,2")
    parser.add_argument("--id", help="comma list of case ids")
    parser.add_argument("--repeat", type=int, default=1, help="run each case N times; every run must pass with the same outcome")
    parser.add_argument("--show", action="store_true", help="print the answer of every failed case")
    parser.add_argument("--yes", action="store_true", help="approve an e2e run whose projected cost is above the cap")
    parser.add_argument("--cap", type=float, default=DEFAULT_CAP_USD, help="USD; an e2e run projected above this needs --yes")
    parser.add_argument("--project-only", action="store_true", help="e2e: print the projected cost and stop; no model is called")
    args = parser.parse_args()

    if args.mode == "offline":
        corpus = __import__("tests.fixtures", fromlist=["load_fixture_sources"]).load_fixture_sources()
        names.set_terms(FAKE_NAMES)
    else:
        from jm_rag.sources import load_sources
        corpus = load_sources()
        if not names.terms_loaded():
            sys.exit("data/guard/name_terms.json is missing. Run: python -m scripts.build_guard_terms")
    e2e_client, model = None, None
    if args.mode == "e2e":
        import os
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=True)
        e2e_client = None if args.project_only else build_e2e_client()   # projecting never creates a client
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    cases = select(args)
    if not cases:
        sys.exit("No cases selected.")

    if args.mode == "e2e":
        plan = project_cost(cases, corpus, model, args.repeat)
        note = "assumed rates 0.15 / 0.60 per 1M tokens (none configured)" if plan["assumed_rates"] else "configured rates"
        print(f"Projected e2e run: {plan['cases']} cases, about {plan['model_calls']} model calls, "
              f"{plan['prompt_tokens']:,} prompt + {plan['completion_tokens']:,} completion tokens, "
              f"USD {plan['cost_usd']:.4f} ({note}; includes {RETRY_FACTOR}x for retries). Cap USD {args.cap:g}.")
        if args.project_only:
            return 0
        if plan["cost_usd"] > args.cap and not args.yes:
            print("Projected cost is above the cap. Nothing was run. Ask the owner, then re-run with --yes.")
            return 2

    ocr_wrong = set()
    if args.mode != "offline":
        from scripts.ocr_accuracy_report import disagreements
        ocr_wrong = disagreements()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"{'id':<6}{'set':<9}{'tier':<5}{'expect':<9}{'got':<9}{'result':<7}{'calls':>6}{'tokens':>10}{'USD':>9}{'ms':>7}")
    results = []
    for case in cases:
        runs = [run_case(case, corpus, args.mode, e2e_client, model) for _ in range(max(1, args.repeat))]
        fails = []
        for index, result in enumerate(runs):
            fails += [(f"run {index + 1}: " if len(runs) > 1 else "") + item for item in judge(case, result, args.mode)]
        if len({run["outcome"] for run in runs}) > 1:
            fails.append("outcome changed between runs: " + ", ".join(run["outcome"] for run in runs))
        usage = {"calls": sum(r["usage_total"]["calls"] for r in runs), "prompt": sum(r["usage_total"]["prompt"] for r in runs),
                 "completion": sum(r["usage_total"]["completion"] for r in runs)}
        costs = [r["usage_total"]["cost_usd"] for r in runs]
        usage["cost_usd"] = None if any(c is None for c in costs) else sum(costs)
        if args.mode == "e2e":
            log_spend(case, args.mode, model, usage)
        last = runs[-1]
        ocr_hits = sorted(set(case.get("ocr_fields", [])) & ocr_wrong) if fails else []
        if ocr_hits:
            fails.append(f"{OCR_LABEL} ({len(ocr_hits)} field(s) wrong in OCR: {', '.join(ocr_hits)})")
        record = {"id": case["id"], "set": case["set"], "tier": case.get("tier", 1), "expect": case.get("expect", "any"),
                  "outcome": last["outcome"], "passed": not fails, "fails": fails, "usage": usage, "ms": max(r["ms"] for r in runs),
                  "cited": last["cited_ids"], "notes": len(last["notes"]), "answer": last["answer"],
                  "evidence_only": last.get("evidence_only", []), "ocr_error": bool(ocr_hits)}
        results.append(record)
        shown_cost = "n/a" if usage["cost_usd"] is None else f"{usage['cost_usd']:.4f}"
        print(f"{record['id']:<6}{record['set']:<9}{record['tier']:<5}{str(record['expect']):<9}{record['outcome']:<9}"
              f"{'PASS' if not fails else 'FAIL':<7}{usage['calls']:>6}{usage['prompt'] + usage['completion']:>10}{shown_cost:>9}{record['ms']:>7}")
        for item in fails:
            print(f"        - {item}")
        if fails and args.show:
            print("        answer: " + last["answer"].replace("\n", " ")[:500])

    return summarise(results, args, stamp)


def summarise(results: list[dict], args, stamp: str) -> int:
    print()
    gating_failures = []
    for set_name in sorted({r["set"] for r in results}):
        rows = [r for r in results if r["set"] == set_name]
        by_tier = ", ".join(f"tier {t}: {sum(r['passed'] for r in rows if r['tier'] == t)}/{sum(1 for r in rows if r['tier'] == t)}"
                            for t in sorted({r["tier"] for r in rows}))
        print(f"{set_name:<9}{sum(r['passed'] for r in rows)}/{len(rows)} passed ({by_tier})")
    ocr_cases = {r["id"] for r in results if r.get("ocr_error")}
    if ocr_cases:
        for set_name in sorted({r["set"] for r in results if r["id"] in ocr_cases}):
            rows = [r for r in results if r["set"] == set_name and r["id"] not in ocr_cases]
            by_tier = ", ".join(f"tier {t}: {sum(r['passed'] for r in rows if r['tier'] == t)}/{sum(1 for r in rows if r['tier'] == t)}"
                                for t in sorted({r["tier"] for r in rows}))
            print(f"{set_name:<9}{sum(r['passed'] for r in rows)}/{len(rows)} passed without the OCR data-error cases "
                  f"{', '.join(sorted(ocr_cases))} ({by_tier})")
    refusals = [r for r in results if r["expect"] == "refuse"]
    print(f"refusal cases: {sum(r['passed'] for r in refusals)}/{len(refusals)}, model calls on them: "
          f"{sum(r['usage']['calls'] for r in refusals)}")
    lenient = [r for r in results if r["passed"] and r["evidence_only"]]
    if lenient:
        print(f"passed with some must_include found only in the evidence, not the answer text: {len(lenient)} "
              f"({", ".join(r["id"] for r in lenient)})")
    totals = {key: sum(r["usage"][key] for r in results) for key in ("calls", "prompt", "completion")}
    costs = [r["usage"]["cost_usd"] for r in results if r["usage"]["calls"]]
    cost_text = "no model calls" if not costs else ("cost unavailable (no price configured)" if any(c is None for c in costs)
                                                    else f"USD {sum(costs):.4f}")
    print(f"model calls {totals['calls']}, tokens {totals['prompt']:,} prompt + {totals['completion']:,} completion, {cost_text}")
    for r in results:
        if r["passed"]:
            continue
        # the manager set is held out: its rate is reported, it never gates (and is never used for tuning)
        gating = r["expect"] == "refuse" or r["set"] in ("hostile", "legit") or (r["tier"] == 1 and r["set"] != "manager")
        if gating:
            gating_failures.append(r["id"])
    other = [r["id"] for r in results if not r["passed"] and r["id"] not in gating_failures]
    if args.mode == "e2e":
        tier2 = [r for r in results if r["tier"] == 2 and r["set"] == "main"]
        if tier2 and sum(r["passed"] for r in tier2) / len(tier2) < 0.9:
            gating_failures.append("tier 2 below 90%")
    ocr_failures = [r["id"] for r in results if not r["passed"] and r.get("ocr_error")]
    if ocr_failures:
        print(f"{OCR_LABEL}: {', '.join(ocr_failures)}")
    if gating_failures:
        print("GATING FAILURES: " + ", ".join(gating_failures))
    if other:
        print("Other failures (reported, not gating): " + ", ".join(other))
    OUT.mkdir(exist_ok=True)
    path = OUT / f"{stamp}-{args.mode}.json"
    path.write_text(json.dumps(results, indent=1, default=str), encoding="utf-8")
    print(f"Result written to {path.relative_to(ROOT).as_posix()}")
    return 1 if gating_failures else 0


if __name__ == "__main__":
    sys.exit(main())
