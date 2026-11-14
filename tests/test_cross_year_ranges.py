"""Month-to-month ranges that cross a year boundary ("July 2024 to August 2025")."""
import unittest
from datetime import date
from unittest.mock import patch

from jm_rag.dates import date_clarification, parse_date_window
from jm_rag.guardrails import names
from jm_rag.pipeline import answer_question
from jm_rag.retrieval import retrieve
from tests.fixtures import build_fixture_sources
from tests.mock_client import ForbiddenClient


class CrossYearWindowTests(unittest.TestCase):
    def test_range_with_a_year_on_both_ends(self):
        cases = {
            "July 2024 to August 2025": (date(2024, 7, 1), date(2025, 9, 1)),
            "Jul 2024 - Mar 2025": (date(2024, 7, 1), date(2025, 4, 1)),
            "jul2024 - mar2025": (date(2024, 7, 1), date(2025, 4, 1)),
            "Nov 2024 through Feb 2026": (date(2024, 11, 1), date(2026, 3, 1)),
            "December 2024 to January 2025": (date(2024, 12, 1), date(2025, 2, 1)),
            "September 2024 until December 2025": (date(2024, 9, 1), date(2026, 1, 1)),
            "work orders for CNC-02 from March 2024 to March 2025": (date(2024, 3, 1), date(2025, 4, 1)),
        }
        for question, window in cases.items():
            with self.subTest(question=question):
                self.assertEqual(parse_date_window(question), window)
                self.assertIsNone(date_clarification(question))

    def test_en_dash_and_em_dash_work_too(self):
        self.assertEqual(parse_date_window("Jul 2024 \u2013 Mar 2025"), (date(2024, 7, 1), date(2025, 4, 1)))
        self.assertEqual(parse_date_window("Jul 2024 \u2014 Mar 2025"), (date(2024, 7, 1), date(2025, 4, 1)))

    def test_one_month_to_the_same_month_is_that_month(self):
        self.assertEqual(parse_date_window("July 2024 to July 2024"), (date(2024, 7, 1), date(2024, 8, 1)))

    def test_a_range_that_ends_before_it_starts_is_asked_about(self):
        self.assertIsNone(parse_date_window("August 2025 to July 2024"))
        self.assertIn("ends before it starts", date_clarification("August 2025 to July 2024"))

    def test_the_older_range_forms_are_unchanged(self):
        self.assertEqual(parse_date_window("June-August 2025"), (date(2025, 6, 1), date(2025, 9, 1)))
        self.assertEqual(parse_date_window("2024-2025"), (date(2024, 1, 1), date(2026, 1, 1)))
        self.assertEqual(parse_date_window("July 2024"), (date(2024, 7, 1), date(2024, 8, 1)))

    def test_the_mixed_forms_still_ask(self):
        self.assertIn("mixes a month with a range of years", date_clarification("July 2024 to 2025"))
        self.assertIn("mixes a year with a month", date_clarification("2024 to July 2025"))

    def test_a_full_range_next_to_a_bad_day_still_asks_about_the_bad_day(self):
        self.assertIn("that day does not exist", date_clarification("31 Feb 2024 and July 2024 to August 2025"))


class CrossYearRetrievalTests(unittest.TestCase):
    def setUp(self):
        names.set_terms([])
        self.addCleanup(names.set_terms, None)

    def test_work_orders_in_the_range_are_returned_and_others_are_not(self):
        sources = build_fixture_sources()
        found = {result["title"] for result in retrieve("work orders July 2024 to August 2025", sources, limit=50)}
        self.assertEqual(found, {"Work order 9001 / TST-01", "Work order 9002 / TST-01",
                                 "Work order 9003 / TST-02", "Work order 9004 / TST-02"})
        found = {result["title"] for result in retrieve("work orders Jul 2024 - Mar 2025", sources, limit=50)}
        self.assertEqual(found, {"Work order 9001 / TST-01", "Work order 9002 / TST-01"})

    def test_incidents_in_the_range(self):
        found = {result["title"] for result in retrieve("incidents Jan 2025 to Dec 2025", build_fixture_sources(), limit=50)}
        self.assertEqual(found, {"Incident 9101 / TST-01", "Incident 9102 / TST-02", "IR-2025-990 / incident report image"})

    def test_the_pipeline_answers_with_a_table_and_does_not_ask(self):
        with patch.dict("os.environ", {}, clear=True):
            result = answer_question("show work orders for TST-02 from Jan 2025 to Dec 2025", [],
                                     (build_fixture_sources(), []), ForbiddenClient(), model="m")
        self.assertEqual(result["outcome"], "answer")
        self.assertIn("| 9003 |", result["answer"])
        self.assertIn("| 9004 |", result["answer"])

    def test_the_computed_facts_use_the_range(self):
        from jm_rag.facts import facts_source
        text = facts_source("how many work orders July 2024 to August 2025", build_fixture_sources())["text"]
        self.assertIn("2024-07-01 to 2025-08-31", text)
        self.assertIn("4 in total", text)


if __name__ == "__main__":
    unittest.main()
