"""A month with no year in a work-order question: the app asks which year instead of listing the newest rows.

Reported with "List me the work order for month of Nov", which returned the ten newest work orders (all June 2026)
because only a month plus a year was read as a date. Nothing here needs MySQL, the network or an API key.
"""
import unittest
from datetime import date

from jm_rag.dates import parse_date_window, partial_month, resolve_partial_month
from jm_rag.guardrails import names
from jm_rag.pipeline import answer_question
from tests.fixtures import build_fixture_sources
from tests.mock_client import ForbiddenClient


class PartialMonthTests(unittest.TestCase):
    def test_bare_month_in_a_work_order_question(self):
        self.assertEqual(partial_month("List me the work order for month of Nov"), (11, "for month of Nov"))
        self.assertEqual(partial_month("work orders in November"), (11, "in November"))
        self.assertEqual(partial_month("service history for CNC-02 during Nov"), (11, "during Nov"))
        self.assertEqual(partial_month("work orders for the last November"), (11, "for the last November"))

    def test_month_with_a_year_is_not_partial(self):
        self.assertIsNone(partial_month("work orders in November 2025"))
        self.assertIsNone(partial_month("work orders for Nov 2024"))

    def test_day_and_month_is_left_to_the_day_rule(self):
        self.assertIsNone(partial_month("work orders on 26 July"))
        self.assertIsNone(partial_month("work orders for Nov 14"))

    def test_the_word_may_needs_a_preposition_to_be_a_month(self):
        self.assertIsNone(partial_month("May I see the work orders for CNC-02"))
        self.assertEqual(partial_month("work orders in May"), (5, "in May"))

    def test_only_work_order_questions_can_be_partial(self):
        self.assertIsNone(partial_month("incidents in November"))
        self.assertIsNone(partial_month("hello"))

    def test_resolve_adds_the_year(self):
        self.assertEqual(resolve_partial_month("List me the work order for month of Nov", 2025),
                         "List me the work order in November 2025")

    def test_resolve_leaves_other_questions_alone(self):
        self.assertEqual(resolve_partial_month("hello", 2025), "hello")
        self.assertEqual(resolve_partial_month("work orders in November 2024", 2025), "work orders in November 2024")

    def test_resolved_question_reads_as_that_month(self):
        resolved = resolve_partial_month("work orders for the month of Nov", 2025)
        self.assertEqual(parse_date_window(resolved), (date(2025, 11, 1), date(2025, 12, 1)))


class BareMonthPipelineTests(unittest.TestCase):
    def setUp(self):
        names.set_terms(["Zed Quarrel"])
        self.addCleanup(names.set_terms, None)

    def ask(self, question, history=()):
        return answer_question(question, list(history), (build_fixture_sources(), []), ForbiddenClient(), model="m")

    def test_bare_month_asks_for_the_year_before_querying(self):
        result = self.ask("list the work orders for month of August")
        self.assertEqual(result["outcome"], "clarify")
        self.assertIn("year is missing", result["answer"])
        self.assertIn("August", result["answer"])
        self.assertEqual(result["usage"]["calls"], 0)

    def test_a_year_reply_resolves_to_that_month_only(self):
        history = [{"role": "user", "content": "list the work orders for month of August"},
                   {"role": "assistant", "content": "Which year should I search?"}]
        result = self.ask("2025", history)
        self.assertEqual(result["outcome"], "answer")
        self.assertIn("| 9004 |", result["answer"])       # 20 Aug 2025
        self.assertNotIn("| 9003 |", result["answer"])    # 12 Jun 2025
        self.assertNotIn("| 9001 |", result["answer"])    # Jul 2024

    def test_a_month_with_a_year_is_answered_directly(self):
        result = self.ask("list the work orders for August 2025")
        self.assertEqual(result["outcome"], "answer")
        self.assertIn("| 9004 |", result["answer"])
        self.assertNotIn("| 9003 |", result["answer"])


if __name__ == "__main__":
    unittest.main()
