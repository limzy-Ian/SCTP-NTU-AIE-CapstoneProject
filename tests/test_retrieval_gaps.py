"""Phase 4b step 2: lubricant words and sensor word stems in retrieval, and the "why is it vibrating" abstain.

Invented data only.
"""
import json
import unittest
from unittest.mock import patch

from jm_rag import notes
from jm_rag.guardrails import names
from jm_rag.pipeline import answer_question
from jm_rag.retrieval import retrieve
from tests.fixtures import build_fixture_sources
from tests.mock_client import MockClient


def types(results):
    return [result["source_type"] for result in results]


def plate(tag, lubricant):
    return {"title": f"{tag} / nameplate_{tag}.jpg", "location": "MySQL", "asset_tag": tag, "asset_tags": [tag],
            "source_type": "nameplate",
            "text": "UNVERIFIED OCR; " + json.dumps({"asset_tag": tag, "model": "M", "cmms_model": "M", "lubricant": lubricant,
                                                       "grease_interval_hours": 500})}


def machine(tag):
    return {"title": f"{tag} / machine master", "text": "CMMS machine master record.", "location": "MySQL: machines",
            "asset_tag": tag, "asset_aliases": [tag], "machine_record": True, "source_type": "mysql"}


def grade_corpus():
    spare = {"title": "critical_spares.xlsx / HYD-1", "location": "spares row 4", "asset_tag": "ALL", "source_type": "tabular",
             "text": "Workbook row. Part number: HYD-1. Description: Hydraulic oil ISO VG32 (20L). Machine: ALL. Source row: "
                     + json.dumps({"Part No": "HYD-1", "Description": "Hydraulic oil ISO VG32 (20L)", "For Machine": "ALL", "Qty": 4})}
    return ([machine("CNC-01"), machine("CNC-02"), machine("CNC-03"), plate("CNC-01", "Is0 v632 Nesags oS"),
             plate("CNC-02", "ISO. VG32 aig Ae)"), plate("CNC-03", "TSO VG68 a"), spare], [])


class LubricantWordTests(unittest.TestCase):
    def setUp(self):
        self.sources = build_fixture_sources()

    def test_oil_lube_grease_and_viscosity_retrieve_the_nameplate(self):
        for question in ("what oil does TST-01 take", "what lube does TST-01 use", "which grease for TST-01",
                         "TST-01 oil viscosity", "what lubrication does TST-01 need", "which oils does TST-01 use"):
            with self.subTest(question=question):
                self.assertEqual(types(retrieve(question, self.sources))[0], "nameplate")

    def test_oil_for_a_machine_does_not_return_incidents_or_work_orders(self):
        results = retrieve("what oil does TST-01 take", self.sources)
        self.assertEqual(set(types(results)), {"nameplate"})

    def test_oil_in_stock_still_prefers_the_spares_rows(self):
        self.assertIn("tabular", types(retrieve("do we have grease in stock", self.sources)))


class SensorStemTests(unittest.TestCase):
    def setUp(self):
        self.sources = build_fixture_sources()

    def test_vibrating_vibrates_and_vibrated_are_sensor_words(self):
        for question in ("is TST-01 vibrating", "TST-01 vibrates a lot at night", "TST-01 vibrated yesterday",
                         "TST-01 temperatures at night"):
            with self.subTest(question=question):
                self.assertTrue(set(types(retrieve(question, self.sources))) & {"sensor_summary", "sensor_trend_monthly"})

    def test_more_higher_and_worse_ask_for_the_monthly_trend(self):
        for question in ("is TST-01 vibrating more", "has TST-01 vibration got worse", "is TST-01 temperature higher"):
            with self.subTest(question=question):
                self.assertEqual(types(retrieve(question, self.sources)), ["sensor_trend_monthly"])

    def test_trend_stems(self):
        self.assertEqual(types(retrieve("TST-01 vibration trends", self.sources)), ["sensor_trend_monthly"])
        self.assertEqual(types(retrieve("is the vibration increasing on TST-01", self.sources)), ["sensor_trend_monthly"])

    def test_plain_sensor_summary_is_unchanged(self):
        self.assertEqual([result["title"] for result in retrieve("sensor summary for TST-01", self.sources)],
                         ["TST-01 / sensor summary"])


class WhyIsItVibratingTests(unittest.TestCase):
    QUESTION = "Why is TST-01 vibrating more?"

    def setUp(self):
        names.set_terms([])
        self.addCleanup(names.set_terms, None)

    def ask(self, client):
        with patch.dict("os.environ", {}, clear=True):
            return answer_question(self.QUESTION, [], (build_fixture_sources(), []), client, model="m")

    def test_shows_the_sensor_facts_and_abstains_on_cause(self):
        result = self.ask(None)
        self.assertEqual(result["outcome"], "abstain")
        self.assertEqual([source["source_type"] for source in result["sources"]], ["sensor_trend_monthly", "computed_facts"])
        self.assertIn("mean vibration lowest 2 mm/s (2026-01), highest 2.1 mm/s (2026-02)", result["answer"])
        self.assertIn(notes.CAUSE_NOTE, result["answer"])
        self.assertIn(notes.INFERENCE_NOTE, result["answer"])

    def test_a_model_answer_is_kept_and_the_notes_are_added(self):
        def reply(kwargs):
            evidence = json.loads(kwargs["messages"][-1]["content"].split("Retrieved evidence:\n", 1)[1])
            facts = next(item["id"] for item in evidence if item["title"].startswith("Computed facts"))
            return f"Mean vibration rose from 2 to 2.1 mm/s between 2026-01 and 2026-02 [{facts}]."
        result = self.ask(MockClient([reply]))
        self.assertEqual(result["outcome"], "abstain")
        self.assertIn("Mean vibration rose from 2 to 2.1 mm/s", result["answer"])
        self.assertIn(notes.CAUSE_NOTE, result["notes"])
        self.assertEqual(result["errors"], [])

    def test_the_cause_note_only_appears_for_why_questions(self):
        self.assertNotIn(notes.CAUSE_NOTE, notes.mandatory_notes({"inference_request": True}, "is TST-01 in good shape", []))
        self.assertIn(notes.CAUSE_NOTE, notes.mandatory_notes({"inference_request": True}, "what caused the failure", []))

    def test_the_prompt_says_not_to_offer_causes(self):
        client = MockClient(["Vibration is 2.1 mm/s [S1]."])
        self.ask(client)
        self.assertIn("Do not offer causes", client.calls[0]["messages"][0]["content"])


class SparesAllConflictTests(unittest.TestCase):
    def ask(self, question):
        with patch.dict("os.environ", {}, clear=True):
            return answer_question(question, [], grade_corpus(), None, model="m")

    def test_a_machine_whose_plate_matches_all_still_gets_the_all_conflict(self):
        result = self.ask("What oil does CNC-02 take?")
        self.assertEqual(result["outcome"], "conflict")
        text = " ".join(result["notes"])
        self.assertIn("one entry for `ALL` machines (Hydraulic oil ISO VG32 (20L))", text)
        self.assertIn("It matches this nameplate", text)
        self.assertIn("nameplates of CNC-03 read a different viscosity grade", text)
        self.assertIn("not expanded to machines", text)
        self.assertEqual({source["source_type"] for source in result["sources"]}, {"nameplate", "tabular"})

    def test_a_machine_whose_plate_differs_from_all_gets_the_direct_conflict(self):
        result = self.ask("What oil does CNC-03 take?")
        self.assertEqual(result["outcome"], "conflict")
        self.assertIn("do not match the spares list entry for `ALL` machines", " ".join(result["notes"]))

    def test_unreadable_ocr_grades_are_not_counted_as_a_disagreement(self):
        text = " ".join(self.ask("What oil does CNC-02 take?")["notes"])
        self.assertNotIn("CNC-01", text)

    def test_no_conflict_when_every_plate_reads_the_same_grade(self):
        sources, warnings = grade_corpus()
        sources = [source for source in sources if source.get("asset_tag") != "CNC-03"]
        with patch.dict("os.environ", {}, clear=True):
            result = answer_question("What oil does CNC-02 take?", [], (sources, warnings), None, model="m")
        self.assertEqual(result["outcome"], "answer")
        self.assertNotIn("Conflict on lubricant", " ".join(result["notes"]))


if __name__ == "__main__":
    unittest.main()
