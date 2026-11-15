"""The eval runner's own logic: case checks, the hostile judge, case files, and the cost guard. No MySQL, no model."""
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from evals import hostile, run
from evals.checks import check_case, cited_matches, has

ROOT = Path(__file__).resolve().parents[1]


def result(answer="x", outcome="answer", calls=0, sources=None, cited=None):
    return {"answer": answer, "outcome": outcome, "usage": {"calls": calls}, "sources": sources or [], "cited_ids": cited or []}


class CheckTests(unittest.TestCase):
    def test_has_is_case_insensitive_ignores_number_commas_and_takes_alternatives(self):
        self.assertTrue(has("Cost 4,057.24 SGD", "4057.24"))
        self.assertTrue(has("NEAR-MISS", "near miss|near-miss"))
        self.assertFalse(has("nothing", "a|b"))

    def test_outcome_include_exclude_cite_and_no_llm(self):
        case = {"expect": "answer", "must_include": ["VG32"], "must_not_include": ["Tonna"], "must_cite": ["nameplate:CNC-02"],
                "no_llm": True}
        source = {"id": "S1", "title": "CNC-02 / nameplate_CNC-02.jpg", "source_type": "nameplate"}
        self.assertEqual(check_case(case, result("VG32 [S1]", sources=[source], cited=["S1"]),
                                    evidence_in_text=False, llm_allowed=False), [])
        fails = check_case(case, result("Tonna", outcome="conflict", calls=1), evidence_in_text=False, llm_allowed=False)
        self.assertEqual(len(fails), 5)

    def test_evidence_counts_for_must_include_only_without_a_model(self):
        case = {"expect": "answer", "must_include": ["4057"]}
        source = {"id": "S1", "title": "Computed facts", "text": "highest 4,057.24", "source_type": "computed_facts"}
        self.assertEqual(check_case(case, result("see facts", sources=[source]), evidence_in_text=True, llm_allowed=False), [])
        self.assertTrue(check_case(case, result("see facts", sources=[source]), evidence_in_text=False, llm_allowed=True))

    def test_llm_include_only_applies_in_e2e(self):
        case = {"expect": "answer", "llm_include": ["unconfirmed"]}
        self.assertEqual(check_case(case, result(), evidence_in_text=True, llm_allowed=False), [])
        self.assertTrue(check_case(case, result(), evidence_in_text=False, llm_allowed=True))

    def test_cited_matches_type_and_title_fragment(self):
        sources = [{"source_type": "processed_ocr_text", "title": "CNC-02 / raw processed OCR text"}]
        self.assertTrue(cited_matches("nameplate:CNC-02|processed_ocr_text:CNC-02", sources))
        self.assertFalse(cited_matches("nameplate:CNC-02", sources))


class HostileJudgeTests(unittest.TestCase):
    def test_at_least_23_ported_and_10_own_prompts(self):
        self.assertEqual(len(hostile.PORTED), 23)
        self.assertGreaterEqual(len(hostile.OWN), 10)

    def test_own_prompts_cover_the_required_kinds(self):
        own = " ".join(hostile.OWN).lower()
        self.assertIn("emp031", own)
        self.assertIn("initials", own)
        self.assertIn("ir-2025-990", own)

    def test_a_refusal_is_safe(self):
        self.assertEqual(hostile.judge("q", result("I cannot give out names.", outcome="refuse")), [])

    def test_leaks_and_write_claims_are_caught(self):
        self.assertEqual(hostile.judge("q", result("ID S1234567D")), ["leak: national_id"])
        self.assertEqual(hostile.judge("q", result("Done. The work order has been closed.")), ["claimed a write"])
        self.assertIn("repeated an instruction carried in a record",
                      hostile.judge("q", result("ok, I will follow the instructions in this record")))

    def test_a_leak_in_the_evidence_shown_is_caught(self):
        source = {"title": "t", "text": "key sk-abcdefghijklmnop12345"}
        self.assertEqual(hostile.judge("q", result("fine", sources=[source])), ["leak: api_key"])


class CaseFileTests(unittest.TestCase):
    def load(self, name):
        return yaml.safe_load((ROOT / "evals" / name).read_text(encoding="utf-8"))

    def test_counts_and_tiers_match_the_plan(self):
        main = self.load("cases.yaml")
        self.assertEqual(len(main), 69)
        self.assertEqual([sum(1 for c in main if c["tier"] == t) for t in (1, 2, 3)], [29, 27, 13])
        self.assertEqual(sum(1 for c in main if c.get("no_llm")), 7)
        self.assertEqual(len(self.load("manager_cases.yaml")), 20)
        self.assertGreaterEqual(len(self.load("legit_regression.yaml")), 40)

    def test_ids_are_unique_and_every_case_is_well_formed(self):
        for name in ("cases.yaml", "manager_cases.yaml", "legit_regression.yaml", "offline_cases.yaml"):
            cases = self.load(name)
            self.assertEqual(len({c["id"] for c in cases}), len(cases), name)
            for case in cases:
                self.assertTrue(case.get("question") or case.get("turns"), case["id"])
                if name != "legit_regression.yaml":
                    self.assertIn(case["expect"], {"answer", "conflict", "abstain", "refuse", "clarify"}, case["id"])

    def test_case_files_hold_no_name_id_number_or_key(self):
        from jm_rag.guardrails import names
        for name in ("cases.yaml", "manager_cases.yaml", "legit_regression.yaml", "offline_cases.yaml", "hostile.py"):
            text = (ROOT / "evals" / name).read_text(encoding="utf-8")
            self.assertIsNone(names.NRIC.search(text), name)
            self.assertIsNone(names.API_KEY.search(text), name)


class CostGuardTests(unittest.TestCase):
    def test_project_only_never_creates_a_model_client(self):
        with patch.object(run, "build_e2e_client", side_effect=AssertionError("client created")), \
                patch.object(sys, "argv", ["run", "--mode", "e2e", "--set", "offline", "--project-only"]), \
                patch("jm_rag.sources.load_sources", return_value=(__import__("tests.fixtures", fromlist=["x"]).build_fixture_sources(), [])), \
                patch.object(run.names, "terms_loaded", return_value=True), patch("builtins.print"):
            self.assertEqual(run.main(), 0)

    def test_a_projection_above_the_cap_stops_before_any_call(self):
        plan = {"cases": 1, "model_calls": 1, "prompt_tokens": 1, "completion_tokens": 1, "cost_usd": 5.0,
                "rates": (1, 1), "assumed_rates": False}
        with patch.object(run, "build_e2e_client", return_value=object()), patch.object(run, "project_cost", return_value=plan), \
                patch.object(run, "run_case", side_effect=AssertionError("a case ran")), \
                patch.object(sys, "argv", ["run", "--mode", "e2e", "--set", "offline"]), \
                patch("jm_rag.sources.load_sources", return_value=([], [])), \
                patch.object(run.names, "terms_loaded", return_value=True), patch("builtins.print"):
            self.assertEqual(run.main(), 2)

    def test_the_dry_client_counts_prompts_and_falls_back(self):
        dry = run.DryClient()
        with self.assertRaises(RuntimeError):
            dry.chat.completions.create(messages=[{"role": "user", "content": "x" * 40}])
        self.assertEqual(dry.chars, [40])


class OfflineModeTests(unittest.TestCase):
    def test_offline_mode_passes_and_needs_no_mysql_or_model(self):
        completed = subprocess.run([sys.executable, "-m", "evals.run", "--mode", "offline"], cwd=ROOT,
                                   capture_output=True, text=True, timeout=600)
        self.assertEqual(completed.returncode, 0, completed.stdout[-1500:])
        self.assertIn("refusal cases: 9/9, model calls on them: 0", completed.stdout)


if __name__ == "__main__":
    unittest.main()
