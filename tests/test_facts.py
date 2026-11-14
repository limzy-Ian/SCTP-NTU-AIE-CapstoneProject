"""Computed facts: counts, totals, minima, maxima and date ranges worked out by code and cited by the model.

Invented data only. No MySQL, network or API key.
"""
import json
import unittest
from datetime import date
from unittest.mock import patch

from jm_rag import facts, validator
from jm_rag.guardrails import names
from jm_rag.pipeline import answer_question
from tests.fixtures import build_fixture_sources
from tests.mock_client import MockClient


def work_order(number, machine, when, cost, hours, kind="PM", status="Closed"):
    record = {"wo_id": number, "machine_id": machine, "wo_type": kind, "description": "x", "wo_date": when,
              "duration_hrs": hours, "cost_sgd": cost, "status": status}
    return {"title": f"Work order {number} / {machine}", "text": "CMMS work order. " + json.dumps(record, default=str),
            "location": "MySQL: work_orders", "asset_tag": machine, "record_date": when, "record": record,
            "source_type": "work_order"}


def many_work_orders(count=12):
    return [work_order(100 + i, "CNC-01", date(2025, 1 + i % 12, 5), 100.0 + i, 1.5) for i in range(count)]


def text_of(question, sources):
    found = facts.facts_source(question, sources)
    return found["text"] if found else None


class WorkOrderFactTests(unittest.TestCase):
    def test_count_dates_cost_hours_type_and_status(self):
        text = text_of("show work orders for TST-01", build_fixture_sources())
        for fragment in ("Work orders (TST-01, any date): 2 in total", "dated 2024-07-03 to 2024-07-26",
                         "total cost 570.50 SGD (lowest 150.00, highest 420.50; cost recorded for 2 of 2)",
                         "total duration 6.5 hours", "by type: CM 1, PM 1", "by status: Closed 2"):
            self.assertIn(fragment, text)

    def test_window_filters_the_set(self):
        text = text_of("how many work orders for TST-02 in 2025", build_fixture_sources())
        self.assertIn("Work orders (TST-02, 2025-01-01 to 2025-12-31): 2 in total", text)
        self.assertIn("total cost 1,860.00 SGD", text)
        self.assertIn("highest 1,800.00", text)

    def test_counts_all_matching_records_not_only_the_retrieved_few(self):
        sources = many_work_orders(12)
        text = text_of("how many work orders for CNC-01", sources)
        self.assertIn("12 in total", text)
        self.assertEqual(len(__import__("jm_rag.retrieval", fromlist=["retrieve"]).retrieve("work orders for CNC-01", sources)), 5)

    def test_machine_breakdown_only_when_more_than_one_machine(self):
        sources = [work_order(1, "CNC-01", date(2025, 1, 1), 1.0, 1), work_order(2, "CNC-02", date(2025, 1, 2), 2.0, 1)]
        self.assertIn("by machine: CNC-01 1, CNC-02 1", text_of("work orders in 2025", sources))
        self.assertNotIn("by machine", text_of("work orders for CNC-01", sources))

    def test_missing_costs_are_counted_honestly(self):
        sources = [work_order(1, "CNC-01", date(2025, 1, 1), 10.0, 1), work_order(2, "CNC-01", date(2025, 1, 2), None, 2)]
        text = text_of("how many work orders for CNC-01", sources)
        self.assertIn("2 in total", text)
        self.assertIn("total cost 10.00 SGD", text)
        self.assertIn("cost recorded for 1 of 2", text)

    def test_no_matching_records_gives_no_facts_source(self):
        self.assertIsNone(text_of("how many work orders for TST-01 in 2019", build_fixture_sources()))


class IncidentFactTests(unittest.TestCase):
    def test_unique_events_lost_days_and_scales_kept_apart(self):
        text = text_of("severity of incidents in 2025", build_fixture_sources())
        self.assertIn("3 unique incidents from 3 source versions", text)
        self.assertIn("dated 2025-03-14 to 2025-09-02", text)
        self.assertIn("total lost days 2 (highest single incident 1)", text)
        self.assertIn("OLD_1_WORST scale (before 1 Jul 2025, 1 is worst): severity 1: 1 incident(s)", text)
        self.assertIn("NEW_5_WORST scale (from 1 Jul 2025, 5 is worst): severity 2: 2 incident(s)", text)
        self.assertIn("not comparable across the two scales", text)

    def test_versions_of_one_event_are_counted_once(self):
        cmms = {"incident_id": "917", "incident_date": date(2024, 5, 1), "machine_id": "CNC-02", "lost_days": 3,
                "severity_raw": 2, "severity_scale": "OLD_1_WORST"}
        ocr = {**cmms, "incident_date": "2024-05-01"}
        sources = [{"title": "Incident 917", "text": "x", "location": "l", "asset_tag": "CNC-02", "incident_id": "917",
                    "incident_date": date(2024, 5, 1), "record": cmms, "source_type": "incident"},
                   {"title": "IR-2024-917", "text": "x", "location": "l", "asset_tag": "CNC-02", "record_key": "IR-2024-917",
                    "incident_date": "2024-05-01", "record": ocr, "source_type": "incident_ocr"}]
        text = text_of("incidents for CNC-02", sources)
        self.assertIn("1 unique incidents from 2 source versions", text)
        self.assertIn("total lost days 3", text)


class SensorAndSparesFactTests(unittest.TestCase):
    def test_sensor_months_minimum_and_maximum(self):
        text = text_of("vibration trend for TST-01", build_fixture_sources())
        self.assertIn("Sensor months for TST-01: 2 months, 2026-01 to 2026-02", text)
        self.assertIn("mean vibration lowest 2 mm/s (2026-01), highest 2.1 mm/s (2026-02)", text)

    def test_sensor_facts_from_the_real_trend_text_format(self):
        trend = {"title": "CNC-02 / monthly sensor trends", "location": "l", "asset_tag": "CNC-02",
                 "source_type": "sensor_trend_monthly", "text": (
                     "Monthly sensor trend for machine CNC-02.\n"
                     "2026-03: 3720 observed readings (100.0% of expected 12-minute readings); mean vibration 2.100 mm/s, "
                     "maximum vibration 3.000 mm/s; mean temperature 40.00 C, maximum temperature 55.50 C.\n"
                     "2026-04: 3600 observed readings (100.0% of expected 12-minute readings); mean vibration 3.400 mm/s, "
                     "maximum vibration 5.250 mm/s; mean temperature 44.00 C, maximum temperature 61.00 C.")}
        text = text_of("vibration trend for CNC-02", [trend])
        for fragment in ("2 months, 2026-03 to 2026-04", "mean vibration lowest 2.1 mm/s (2026-03), highest 3.4 mm/s (2026-04)",
                         "maximum vibration lowest 3 mm/s (2026-03), highest 5.25 mm/s (2026-04)",
                         "mean temperature lowest 40 C (2026-03), highest 44 C (2026-04)",
                         "maximum temperature lowest 55.5 C (2026-03), highest 61 C (2026-04)"):
            self.assertIn(fragment, text)

    def test_spares_total_below_minimum_and_cost_range(self):
        text = text_of("spare parts lead time", build_fixture_sources())
        self.assertIn("2 rows", text)
        self.assertIn("total quantity in stock 16", text)
        self.assertIn("1 below minimum quantity (PN-FAKE-200)", text)
        self.assertIn("unit cost from 8.00 to 35.50", text)

    def test_a_question_about_something_else_has_no_facts(self):
        self.assertIsNone(text_of("what lubricant does TST-01 take", build_fixture_sources()))


class FactsInThePipelineTests(unittest.TestCase):
    QUESTION = "how many work orders did TST-01 have and what did they cost"

    def setUp(self):
        names.set_terms([])
        self.addCleanup(names.set_terms, None)

    def reply(self, text):
        def respond(kwargs):
            for message in reversed(kwargs["messages"]):
                if "Retrieved evidence:\n" in message["content"]:
                    for source in json.loads(message["content"].split("Retrieved evidence:\n", 1)[1]):
                        if source["title"].startswith("Computed facts"):
                            return f"{text} [{source['id']}]"
            raise AssertionError("no computed facts source in the prompt")
        return respond

    def ask(self, client):
        with patch.dict("os.environ", {}, clear=True):
            return answer_question(self.QUESTION, [], (build_fixture_sources(), []), client, model="m")

    def test_count_questions_go_to_the_model_with_a_facts_source(self):
        client = MockClient([self.reply("TST-01 has 2 work orders with a total cost of 570.50 SGD")])
        result = self.ask(client)
        titles = [source["title"] for source in result["sources"]]
        self.assertTrue(any(title.startswith("Computed facts") for title in titles))
        self.assertEqual(len(client.calls), 1)
        self.assertEqual(result["errors"], [])
        self.assertIn("2 work orders with a total cost of 570.50 SGD", result["answer"])

    def test_the_facts_source_has_its_own_id_and_is_cited(self):
        result = self.ask(MockClient([self.reply("TST-01 has 2 work orders")]))
        facts_id = next(source["id"] for source in result["sources"] if source["title"].startswith("Computed facts"))
        self.assertIn(facts_id, result["cited_ids"])

    def test_the_prompt_tells_the_model_to_use_the_facts(self):
        client = MockClient([self.reply("TST-01 has 2 work orders")])
        self.ask(client)
        self.assertIn("Computed facts", client.calls[0]["messages"][0]["content"])

    def test_an_invented_number_still_fails_and_is_retried(self):
        client = MockClient([self.reply("TST-01 has 13 work orders"), self.reply("TST-01 has 2 work orders")])
        result = self.ask(client)
        self.assertEqual(len(client.calls), 2)
        self.assertIn("The number 13 is not in the cited sources", json.dumps(client.calls[1]["messages"]))
        self.assertIn("2 work orders", result["answer"])
        self.assertNotIn("13 work orders", result["answer"])

    def test_an_invented_total_twice_gives_the_template_with_the_computed_facts(self):
        client = MockClient([self.reply("Total cost 999.99 SGD"), self.reply("Total cost 999.99 SGD")])
        result = self.ask(client)
        self.assertNotIn("999.99", result["answer"])
        self.assertIn("total cost 570.50 SGD", result["answer"])
        self.assertEqual(result["usage"]["calls"], 2)

    def test_no_client_still_shows_the_computed_facts(self):
        result = self.ask(None)
        self.assertIn("2 in total", result["answer"])
        self.assertIn("total cost 570.50 SGD", result["answer"])
        sources = result["sources"]
        self.assertEqual(validator.post_check(result["answer"].split("\n\nNotes:")[0], sources, self.QUESTION), [])

    def test_a_plain_history_request_is_still_a_table_without_the_model(self):
        with patch.dict("os.environ", {}, clear=True):
            result = answer_question("show work orders for TST-01", [], (build_fixture_sources(), []), None, model="m")
        self.assertIn("| 9001 |", result["answer"])
        self.assertFalse(any(source["title"].startswith("Computed facts") for source in result["sources"]))

    def test_facts_text_is_free_of_names(self):
        names.set_terms(["Zed Quarrel"])
        sources = build_fixture_sources()
        for source in sources:
            if source["source_type"] == "work_order":
                source["record"] = {**source["record"], "status": "Closed by Zed Quarrel"}
        with patch.dict("os.environ", {}, clear=True):
            result = answer_question(self.QUESTION, [], (sources, []), MockClient([self.reply("TST-01 has 2 work orders")]), model="m")
        self.assertNotIn("Zed", json.dumps(result, default=str))


if __name__ == "__main__":
    unittest.main()
