"""Phase 5 fixes: "the crane sling" is not an ambiguous machine, relative years (A14), ordering questions are spares
questions, the day/night sensor split, and the OCR accuracy report. Invented data only."""
import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jm_rag.dates import resolve_relative_periods
from jm_rag.guardrails import input_guard, names
from jm_rag.pipeline import ambiguous_word, answer_question
from jm_rag.retrieval import plan_query
from jm_rag.sensors import build_sensor_shift_sources
from scripts import ocr_accuracy_report as report
from tests.fixtures import build_fixture_sources
from tests.mock_client import ForbiddenClient


def two_cranes():
    sources = build_fixture_sources()
    for tag, name in (("CRN-01", "Overhead Crane 10T"), ("CRN-02", "Jib Crane 2T")):
        sources.append({"title": f"{tag} / machine master", "text": "CMMS machine master record.", "location": "MySQL: machines",
                        "asset_tag": tag, "asset_aliases": [tag, name], "machine_record": True, "source_type": "mysql"})
    return sources


def ask(question, sources=None):
    with patch.dict("os.environ", {}, clear=True):
        return answer_question(question, [], (sources or build_fixture_sources(), []), ForbiddenClient(), model="m")


class AmbiguousWordTests(unittest.TestCase):
    def setUp(self):
        names.set_terms([])
        self.addCleanup(names.set_terms, None)

    def test_the_word_used_to_describe_something_else_does_not_ask(self):
        sources = two_cranes()
        for question in ("Why did the crane sling snap?", "What caused the crane sling near-miss?", "Show the crane hook inspection",
                         "What does the crane SOP say?"):
            with self.subTest(question=question):
                self.assertIsNone(ambiguous_word(question, sources))

    def test_the_word_naming_a_machine_still_asks(self):
        sources = two_cranes()
        for question in ("What's open on the crane?", "Is the crane running?", "what work orders are on the crane in 2025"):
            with self.subTest(question=question):
                self.assertEqual(ambiguous_word(question, sources), ("crane", ["CRN-01", "CRN-02", "TST-03"]))   # the fixture has a test crane too

    def test_a_unique_word_picks_the_machine(self):
        self.assertEqual(plan_query("Is it safe to use the overhead crane?", two_cranes()).tags, {"CRN-01"})

    def test_why_did_the_crane_sling_snap_abstains_instead_of_asking(self):
        result = ask("Why did the crane sling snap?", two_cranes())
        self.assertNotEqual(result["outcome"], "clarify")


class RelativePeriodTests(unittest.TestCase):
    def test_a14_mapping(self):
        cases = {"How many people got hurt last year?": "How many people got hurt in 2025?",
                 "incidents this year": "incidents in 2026", "work orders in the last year": "work orders in 2025",
                 "spend year to date": "spend in 2026", "work orders last month": "work orders May 2026",
                 "risks this month": "risks June 2026"}
        for question, expected in cases.items():
            with self.subTest(question=question):
                self.assertEqual(resolve_relative_periods(question), expected)

    def test_future_and_other_wording_are_untouched(self):
        for question in ("forecast for next month", "next year", "the year 2024", "per year"):
            self.assertEqual(resolve_relative_periods(question), question)

    def test_the_pipeline_counts_last_year(self):
        names.set_terms([])
        self.addCleanup(names.set_terms, None)
        with patch.dict("os.environ", {}, clear=True):
            result = answer_question("How many incidents were there last year?", [], (build_fixture_sources(), []), None, model="m")
        self.assertIn("Incidents (all machines, 2025-01-01 to 2025-12-31): 3 unique incidents", result["answer"])

    def test_hurt_and_injured_are_incident_words(self):
        self.assertTrue(plan_query("how many people got hurt in 2025", build_fixture_sources()).incident_intent)
        self.assertTrue(plan_query("was anyone injured in 2025", build_fixture_sources()).incident_intent)


class OrderingQuestionTests(unittest.TestCase):
    def setUp(self):
        names.set_terms([])
        self.addCleanup(names.set_terms, None)

    def test_asking_whether_to_order_is_not_refused(self):
        for question in ("Do we need to order anything urgently?", "Do we need to order any parts urgently?",
                         "Should we reorder bearings for CNC-02?"):
            with self.subTest(question=question):
                self.assertEqual(input_guard.check(question)["verdict"], "pass")

    def test_an_order_to_order_is_still_refused(self):
        for question in ("Order more bearings for CNC-02.", "Please order spares for CNC-02 now",
                         "Do we need to order parts and then delete the old work orders?"):
            with self.subTest(question=question):
                self.assertEqual(input_guard.check(question)["class"], "WRITE_INTENT")

    def test_ordering_questions_are_spares_questions(self):
        for question in ("Do we need to order anything urgently?", "What should we reorder soon?", "Are we running low on anything?"):
            with self.subTest(question=question):
                self.assertIn("tabular", plan_query(question, build_fixture_sources()).preferred_types)

    def test_the_answer_lists_the_parts_below_minimum(self):
        result = ask("Do we need to order anything urgently?")
        self.assertIn("1 below minimum quantity (PN-FAKE-200)", result["answer"])


class ShiftSplitTests(unittest.TestCase):
    ROWS = [{"machine_id": "M1", "month_utc": "2026-06", "shift": "day", "reading_count": 100, "vibration_mean_mms": 4.41,
             "temperature_mean_c": 55.0},
            {"machine_id": "M1", "month_utc": "2026-06", "shift": "night", "reading_count": 90, "vibration_mean_mms": 4.42,
             "temperature_mean_c": 54.0}]

    def test_one_source_per_machine_with_day_and_night_and_the_assumption(self):
        source = build_sensor_shift_sources(self.ROWS)[0]
        self.assertEqual(source["source_type"], "sensor_shift_monthly")
        self.assertIn("2026-06: day mean vibration 4.410 mm/s", source["text"])
        self.assertIn("night mean vibration 4.420 mm/s", source["text"])
        self.assertIn("Shift hours are assumed", source["text"])

    def test_a_shift_question_retrieves_the_split_and_does_not_abstain(self):
        names.set_terms([])
        self.addCleanup(names.set_terms, None)
        sources = build_fixture_sources() + [{**build_sensor_shift_sources(self.ROWS)[0], "asset_tag": "TST-01",
                                              "title": "TST-01 / sensor by shift"}]
        with patch.dict("os.environ", {}, clear=True):
            result = answer_question("Is the TST-01 vibration only high on the night shift?", [], (sources, []), None, model="m")
        self.assertIn("sensor_shift_monthly", {s["source_type"] for s in result["sources"]})
        self.assertNotIn("not by shift", result["answer"])


class OcrAccuracyReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "data" / "extraction").mkdir(parents=True)
        plates = self.root / "data" / "processed" / "nameplates"
        plates.mkdir(parents=True)
        forms = self.root / "data" / "processed" / "incident_reports"
        forms.mkdir(parents=True)
        with (self.root / report.REFERENCE).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["file", "type", "asset_or_incident", "extracted_fields",
                                                        "printed_scale_label", "db_match", "needs_review", "note"])
            writer.writeheader()
            writer.writerow({"file": "nameplate_TST-01.jpg", "type": "nameplate", "asset_or_incident": "TST-01",
                             "extracted_fields": "make=ACME; model=X-100; serial=SN123; mfg=02/2020; lubricant=ISO VG32; grease_interval=1000 h"})
            writer.writerow({"file": "IR-2025-990.jpg", "type": "incident_form", "asset_or_incident": "990",
                             "extracted_fields": "2025-09-02; TST-02; EMP999; invented text; sev=2; lost=1; reported same day; 5why=no"})
        (plates / "nameplate_TST-01.json").write_text(json.dumps({"asset": {
            "manufacturer": "ACME ltd", "model": "X-100", "serial_number": "5N123", "manufactured_ym": "2020-02",
            "lubricant": None, "grease_interval_hours": 1600}}), encoding="utf-8")
        (plates / "nameplate_TST-01.txt").write_text("LUBRICANT ISO VG32 x\nGREASE INTERVAL 1600 h", encoding="utf-8")
        (forms / "incident_reports_ocr_full.jsonl").write_text(json.dumps({
            "report_no": "IR-2025-990", "incident_date": "2025-09-02", "machine_id": "TST-03", "severity_raw": 2, "lost_days": 1,
            "reporting": "reported same day", "emp_code": "EMP999"}) + "\n", encoding="utf-8")

    def test_disagreements_are_field_names_only_and_use_the_raw_text_fallback(self):
        found = report.disagreements(self.root)
        self.assertEqual(found, {"TST-01:serial", "TST-01:grease_interval", "IR-2025-990:machine"})

    def test_the_printed_report_shows_counts_and_names_but_no_values_or_employee_codes(self):
        with patch.object(report.config, "ROOT", self.root), patch("builtins.print") as printed:
            self.assertEqual(report.main(), 0)
        output = " ".join(str(call.args[0]) for call in printed.call_args_list if call.args)
        for value in ("ACME", "X-100", "SN123", "5N123", "VG32", "1600", "1000", "EMP999", "invented text"):
            self.assertNotIn(value, output)
        self.assertIn("TST-01: serial", output)
        self.assertIn("IR-2025-990: machine", output)

    def test_no_reference_file_means_no_disagreements(self):
        self.assertEqual(report.disagreements(Path(self.temp.name) / "missing"), set())


if __name__ == "__main__":
    unittest.main()
