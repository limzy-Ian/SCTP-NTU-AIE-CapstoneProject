"""Phase 5b: required values from the computed facts must be stated in the answer.

A mock model that drops required values is used for the three paths: the first answer is complete (1 call), the retry
restores the values (2 calls), and the retry still drops them, so code appends a cited "Key figures" line (2 calls).
Usage and cost are checked for each path. Invented data only.
"""
import json
import unittest
from unittest.mock import patch

from jm_rag import key_figures, validator
from jm_rag.guardrails import names
from jm_rag.pipeline import answer_question
from jm_rag.template import build_template_answer
from tests.fixtures import build_fixture_sources
from tests.mock_client import MockClient

PRICE_ENV = {"OPENAI_INPUT_COST_PER_1M_USD": "1.00", "OPENAI_OUTPUT_COST_PER_1M_USD": "2.00"}
QUESTION = "How many work orders did TST-01 have and what did they cost?"


def facts_reply(text):
    """A reply that cites the computed facts source."""
    def reply(kwargs):
        for message in reversed(kwargs["messages"]):
            if "Retrieved evidence:\n" in message["content"]:
                for source in json.loads(message["content"].split("Retrieved evidence:\n", 1)[1]):
                    if source["title"].startswith("Computed facts"):
                        return text.replace("[F]", f"[{source['id']}]")
        raise AssertionError("no facts source in the prompt")
    return reply


def ask(client, question=QUESTION, env=PRICE_ENV):
    with patch.dict("os.environ", env, clear=True):
        return answer_question(question, [], (build_fixture_sources(), []), client, model="m")


class RequiredValueTests(unittest.TestCase):
    def facts(self, question):
        from jm_rag.facts import facts_source
        source = facts_source(question, build_fixture_sources())
        return {**source, "id": "S9"}

    def labels(self, question):
        return [(item["label"], item["options"][0]) for item in key_figures.required_from_facts(question, self.facts(question))]

    def test_count_and_cost_questions_require_the_count_and_the_total(self):
        self.assertEqual(self.labels(QUESTION), [("work orders", "2"), ("total work-order cost (SGD)", "570.50")])

    def test_most_expensive_requires_the_id_and_the_cost(self):
        self.assertEqual(self.labels("What was the most expensive work order for TST-02?"),
                         [("most expensive work order", "9004"), ("its cost (SGD)", "1,800.00")])

    def test_open_questions_require_the_not_closed_count_and_the_data_end(self):
        labels = self.labels("How many work orders are still open?")
        self.assertIn(("work orders not closed", "1"), labels)
        self.assertIn(("the data ends on 30 Jun 2026", "30 Jun 2026"), labels)

    def test_worst_case_questions_require_the_count_ids_and_the_caveat(self):
        labels = self.labels("How many worst-case incidents have we had?")
        self.assertIn(("worst-case incidents (5 = worst on one scale)", "2"), labels)
        self.assertIn(("worst-case incident 9101", "9101"), labels)
        self.assertIn(("the old-to-new scale mapping is not confirmed", "not confirmed"), labels)

    def test_spares_below_minimum_require_each_part(self):
        self.assertIn(("below minimum: PN-FAKE-200", "PN-FAKE-200"), self.labels("Do we need to order anything urgently?"))

    def test_a_question_the_facts_do_not_answer_requires_nothing(self):
        self.assertEqual(self.labels("show the work orders for TST-01"), [])

    def test_no_facts_source_requires_nothing(self):
        self.assertEqual(key_figures.required_from_facts(QUESTION, None), [])

    def test_stated_ignores_commas_and_does_not_match_inside_a_longer_number(self):
        self.assertTrue(key_figures.stated("cost was 1800.00 SGD", ["1,800.00"]))
        self.assertFalse(key_figures.stated("we had 12 of them", ["2"]))
        self.assertTrue(key_figures.stated("we had 2 of them", ["2"]))
        self.assertFalse(key_figures.stated("version 2.5", ["2"]))

    def test_the_key_figures_line_passes_the_number_check(self):
        facts = self.facts(QUESTION)
        line = key_figures.key_figures_line(key_figures.required_from_facts(QUESTION, facts))
        self.assertEqual(line, "Key figures (computed by code): work orders: 2 [S9]; total work-order cost (SGD): 570.50 [S9].")
        self.assertEqual(validator.post_check(line, [facts], QUESTION), [])


class PathTests(unittest.TestCase):
    def setUp(self):
        names.set_terms([])
        self.addCleanup(names.set_terms, None)

    def test_a_complete_first_answer_makes_one_call(self):
        client = MockClient([facts_reply("TST-01 had 2 work orders costing 570.50 SGD in total [F].")],
                            prompt_tokens=1000, completion_tokens=500)
        result = ask(client)
        self.assertEqual(len(client.calls), 1)
        self.assertNotIn("Key figures", result["answer"])
        usage = result["usage"]
        self.assertEqual((usage["calls"], usage["prompt"], usage["completion"]), (1, 1000, 500))
        self.assertAlmostEqual(usage["cost_usd"], 0.002)

    def test_a_dropped_value_is_retried_with_the_list_and_the_retry_restores_it(self):
        client = MockClient([facts_reply("TST-01 had 2 work orders [F]."),
                             facts_reply("TST-01 had 2 work orders costing 570.50 SGD in total [F].")],
                            prompt_tokens=1000, completion_tokens=500)
        result = ask(client)
        self.assertEqual(len(client.calls), 2)
        retry_prompt = client.calls[1]["messages"][-1]["content"]
        self.assertIn("leaves out figures", retry_prompt)
        self.assertIn("total work-order cost (SGD) (570.50)", retry_prompt)
        self.assertNotIn("Key figures", result["answer"])
        self.assertIn("570.50", result["answer"])
        usage = result["usage"]
        self.assertEqual([step["step"] for step in usage["steps"]], ["answer", "retry"])
        self.assertEqual((usage["calls"], usage["prompt"], usage["completion"]), (2, 2000, 1000))
        self.assertAlmostEqual(usage["cost_usd"], 0.004)

    def test_a_value_still_missing_after_the_retry_is_appended_by_code(self):
        client = MockClient([facts_reply("TST-01 had 2 work orders [F].")] * 2, prompt_tokens=1000, completion_tokens=500)
        result = ask(client)
        self.assertEqual(len(client.calls), 2)
        self.assertTrue(result["answer"].startswith("TST-01 had 2 work orders ["))
        self.assertIn("Key figures (computed by code): total work-order cost (SGD): 570.50 [", result["answer"])
        self.assertNotIn("Key figures (computed by code): work orders:", result["answer"])   # the count was stated
        self.assertNotIn("no AI wording was generated", result["answer"])
        self.assertEqual(result["errors"], [])
        self.assertIn({"step": "key_figures_appended", "values": 1}, result["trace"])
        usage = result["usage"]
        self.assertEqual((usage["calls"], usage["prompt"], usage["completion"]), (2, 2000, 1000))
        self.assertAlmostEqual(usage["cost_usd"], 0.004)

    def test_appending_costs_nothing_extra_and_unknown_prices_stay_unknown(self):
        client = MockClient([facts_reply("TST-01 had 2 work orders [F].")] * 2)
        usage = ask(client, env={})["usage"]
        self.assertEqual(usage["calls"], 2)
        self.assertIsNone(usage["cost_usd"])

    def test_other_problems_on_the_retry_still_give_the_template(self):
        client = MockClient([facts_reply("TST-01 had 2 work orders [F]."), facts_reply("TST-01 had 77 work orders [F].")])
        result = ask(client)
        self.assertIn("no AI wording was generated", result["answer"])
        self.assertIn("total cost 570.50 SGD", result["answer"])

    def test_an_invented_number_still_fails(self):
        client = MockClient([facts_reply("TST-01 had 13 work orders costing 570.50 SGD [F].")] * 2)
        result = ask(client)
        self.assertNotIn("13 work orders", result["answer"])

    def test_an_sop_that_is_cited_but_not_named_is_named_by_code_without_a_retry(self):
        sources = build_fixture_sources()
        sources[-5]["title"] = "SOP-FAKE-01.txt"

        def reply(kwargs):
            evidence = json.loads(kwargs["messages"][-1]["content"].split("Retrieved evidence:\n", 1)[1])
            sop = next(item["id"] for item in evidence if item["title"].startswith("SOP-"))
            return f"Inspect slings before every lift [{sop}]."
        client = MockClient([reply])
        with patch.dict("os.environ", {}, clear=True):
            result = answer_question("what does the SOP say about slings", [], (sources, []), client, model="m")
        self.assertEqual(len(client.calls), 1)
        self.assertIn("Source: SOP-FAKE-01 [", result["answer"])


class TemplateTests(unittest.TestCase):
    def test_the_template_shows_only_the_facts_that_answer_the_question(self):
        from jm_rag.facts import facts_source
        sources = [{**facts_source("Which machines use ISO VG32?", build_fixture_sources() + [
            {"title": "TST-03 / nameplate", "text": 'UNVERIFIED OCR; {"lubricant": "ISO VG32"}', "location": "l",
             "asset_tag": "TST-03", "source_type": "nameplate"}]), "id": "S1"}]
        required = key_figures.required_from_facts("Which machines use ISO VG32?", sources[0])
        text = build_template_answer(sources, "Which machines use ISO VG32?", required)
        self.assertIn("ISO VG32: TST-03", text)
        self.assertNotIn("unreadable text: TST-01", text)   # an unrelated group must not satisfy a check

    def test_the_template_picks_the_sop_lines_that_match_the_question(self):
        sop = {"id": "S1", "title": "SOP-X.txt", "source_type": "document", "location": "l",
               "text": "Title line\n- Wear gloves.\n- Gas test the chamber before entry.\n- Keep an attendant outside.\n- Other rule."}
        text = build_template_answer([sop], "What do I need before entering the chamber? gas test attendant")
        self.assertIn("Gas test the chamber before entry", text)
        self.assertIn("Keep an attendant outside", text)


if __name__ == "__main__":
    unittest.main()
