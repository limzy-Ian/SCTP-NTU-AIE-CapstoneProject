import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

from openpyxl import Workbook
import mysql.connector

from scripts.maintenance_rag import (
    build_sensor_monthly_trend_sources, format_combined_history_table,
    format_work_order_table, is_history_table_request,
    is_work_order_table_request, load_processed_ocr_sources, load_sources,
    load_spares_sources, load_system_prompt, parse_date_window, parse_explicit_date,
    partial_work_order_date, resolve_partial_work_order_date, retrieve, serialize_evidence,
)


class SourceLoadingTests(unittest.TestCase):
    def test_spares_rows_have_machine_filter_and_row_citation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "critical_spares.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Spares"
            sheet.append(["Critical spares list"])
            sheet.append(["Part No", "Description", "For Machine", "Qty", "Min Qty"])
            sheet.append(["BRG-6205", "Bearing 6205 2RS", "CNC-02", 4, 2])
            workbook.save(path)

            sources = load_spares_sources(Path(directory))

        self.assertEqual(len(sources), 1)
        self.assertEqual(sources[0]["asset_tag"], "CNC-02")
        self.assertIn("row 3", sources[0]["location"])
        self.assertEqual(retrieve("CNC-02 bearing stock", sources)[0]["title"],
                         "critical_spares.xlsx / BRG-6205")

    def test_wrong_machine_spares_filtered_out(self):
        sources = [
            {"title": "CNC-01 belt", "asset_tag": "CNC-01", "text": "belt stock"},
            {"title": "CNC-02 bearing", "asset_tag": "CNC-02", "text": "bearing stock"},
        ]
        result = retrieve("CNC-02 belt", sources)
        self.assertEqual(result, [])

    def test_spares_question_prefers_workbook(self):
        sources = [
            {"title": "Work order 1", "asset_tag": "CNC-02", "source_type": "work_order",
             "text": "Bearing replacement maintenance"},
            {"title": "BRG-6205", "asset_tag": "CNC-02", "source_type": "tabular",
             "text": "Critical spare part inventory. Bearing. Quantity in stock 8"},
        ]
        result = retrieve("CNC-02 bearing spares quantity", sources)
        self.assertEqual([source["source_type"] for source in result], ["tabular"])

    def test_assistant_benefits_query_uses_capability_guide_only(self):
        sources = [
            {"title": "Assistant capability guide", "source_type": "app_capability",
             "text": "Cited work orders and source-linked SOP retrieval."},
            {"title": "Work order 11600 / CNC-02", "source_type": "work_order",
             "text": "CMMS maintenance row."},
        ]
        result = retrieve("write me 5 benefits for this Jurong Marine Maintenance Assistant in 50 words", sources)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source_type"], "app_capability")

    def test_recent_servicing_retrieves_newest_work_orders(self):
        sources = [
            {"title": "Work order 10 / CNC-02", "asset_tag": "CNC-02", "source_type": "work_order",
             "record_date": date(2025, 2, 1), "text": "CMMS work order PREVENTIVE routine service"},
            {"title": "Work order 20 / CNC-02", "asset_tag": "CNC-02", "source_type": "work_order",
             "record_date": date(2026, 3, 1), "text": "CMMS work order PREVENTIVE routine service"},
            {"title": "CNC-02 machine master", "asset_tag": "CNC-02", "source_type": "mysql",
             "text": "machine"},
        ]
        result = retrieve("show me recent servicing for CNC-02", sources, limit=2)
        self.assertEqual([source["title"] for source in result],
                         ["Work order 20 / CNC-02", "Work order 10 / CNC-02"])

    def test_service_history_year_filters_out_newer_years(self):
        sources = [
            {"title": "Work order 2024-01 / CNC-03", "asset_tag": "CNC-03",
             "source_type": "work_order", "record_date": date(2024, 12, 30),
             "text": "CMMS work order service preventive"},
            {"title": "Work order 2024-02 / CNC-03", "asset_tag": "CNC-03",
             "source_type": "work_order", "record_date": date(2024, 2, 3),
             "text": "CMMS work order service preventive"},
            {"title": "Work order 2026-01 / CNC-03", "asset_tag": "CNC-03",
             "source_type": "work_order", "record_date": date(2026, 6, 30),
             "text": "CMMS work order service preventive"},
        ]
        result = retrieve("Show me service record for CNC-03 in year 2024", sources, limit=10)
        self.assertEqual([source["title"] for source in result],
                         ["Work order 2024-01 / CNC-03", "Work order 2024-02 / CNC-03"])

    def test_service_history_month_filters_work_orders_not_incidents(self):
        sources = [
            {"title": "PMP-T01 July order", "asset_tag": "PMP-T01", "source_type": "work_order",
             "record_date": date(2024, 7, 26), "text": "CMMS work order service preventive"},
            {"title": "PMP-T01 August order", "asset_tag": "PMP-T01", "source_type": "work_order",
             "record_date": date(2024, 8, 1), "text": "CMMS work order service preventive"},
            {"title": "PMP-T01 incident", "asset_tag": "PMP-T01", "source_type": "incident",
             "incident_date": date(2024, 7, 11), "text": "incident"},
        ]
        result = retrieve("show me service record for PMP-T01 in July 2024", sources, limit=10)
        self.assertEqual([source["title"] for source in result], ["PMP-T01 July order"])

    def test_multi_month_and_multi_year_date_windows(self):
        self.assertEqual(parse_date_window("June-July 2025"),
                         (date(2025, 6, 1), date(2025, 8, 1)))
        self.assertEqual(parse_date_window("2024-2025"),
                         (date(2024, 1, 1), date(2026, 1, 1)))
        self.assertEqual(parse_date_window("June to August 2025"),
                         (date(2025, 6, 1), date(2025, 9, 1)))

    def test_combined_incident_and_service_query_keeps_both_source_types(self):
        sources = [
            {"title": "Work order 10 / CNC-02", "asset_tag": "CNC-02", "source_type": "work_order",
             "record_date": date(2025, 6, 20), "record": {"wo_id": 10, "machine_id": "CNC-02",
             "wo_type": "PREVENTIVE", "wo_date": date(2025, 6, 20), "description": "scheduled PM",
             "duration_hrs": 2, "cost_sgd": 100, "status": "CLOSED"},
             "text": "CMMS work order service maintenance"},
            {"title": "Incident 906 / CNC-02", "asset_tag": "CNC-02", "source_type": "incident",
             "incident_id": "906", "incident_date": date(2025, 7, 11),
             "record": {"incident_id": 906, "machine_id": "CNC-02", "incident_date": date(2025, 7, 11),
                        "description": "slip on oil", "severity_raw": 3, "severity_scale": "NEW_5_WORST",
                        "severity_5_worst": 3, "lost_days": 1}, "text": "CMMS incident severity"},
            {"title": "IR-2025-906 OCR", "asset_tag": "CNC-02", "source_type": "incident_ocr",
             "record_key": "IR-2025-906", "incident_date": date(2025, 7, 11),
             "record": {"record_key": "IR-2025-906", "machine_id": "CNC-02", "incident_date": date(2025, 7, 11),
                        "description": "slip on hydraulic oil", "severity_raw": None,
                        "severity_scale": "NEW_5_WORST", "lost_days": 1, "evidence_status": "UNVERIFIED OCR"},
             "text": "OCR incident report severity scale"},
        ]
        question = "show incident and servicing on June-July 2025 in table form for CNC-02"
        result = retrieve(question, sources, limit=20)
        self.assertEqual({source["source_type"] for source in result},
                         {"work_order", "incident", "incident_ocr"})
        self.assertTrue(is_history_table_request(question))
        table = format_combined_history_table(result)
        self.assertIn("### Incidents", table)
        self.assertIn("### Service / work orders", table)
        self.assertIn("CMMS severity", table)
        self.assertIn("OCR severity", table)
        self.assertIn("1 unique incident", table)

    def test_exact_work_order_day_differs_from_month_range(self):
        sources = [
            {"title": f"Work order {day} / PMP-T01", "asset_tag": "PMP-T01",
             "source_type": "work_order", "record_date": date(2024, 7, day),
             "text": "CMMS work order service corrective"}
            for day in (1, 19, 20, 23, 26)
        ]
        exact = retrieve("show me service record for PMP-T01 in 26 July 2024", sources, limit=10)
        month = retrieve("show me service record for PMP-T01 in July 2024", sources, limit=10)
        self.assertEqual([source["record_date"] for source in exact], [date(2024, 7, 26)])
        self.assertEqual(len(month), 5)
        self.assertEqual(parse_explicit_date("service records on 2024-07-26"), date(2024, 7, 26))
        self.assertEqual(parse_explicit_date("service records on July 26, 2024"), date(2024, 7, 26))
        self.assertEqual(parse_explicit_date("service records on 26-07-2024"), date(2024, 7, 26))
        self.assertEqual(parse_explicit_date("service records on 26/07/2024 at 14:30"), date(2024, 7, 26))
        compact_month = retrieve("show me service record for PMP-T01 in Jul2024", sources, limit=10)
        self.assertEqual(len(compact_month), 5)

    def test_partial_service_date_requires_year_clarification(self):
        self.assertEqual(partial_work_order_date("show me service record for PMP-T01 in 26/07"),
                         (26, 7, "26/07"))
        self.assertEqual(partial_work_order_date("service records for PMP-T01 on 26 July"),
                         (26, 7, "26 July"))
        self.assertIsNone(partial_work_order_date("service record for PMP-T01 on 26/07/2024"))

    def test_confirmed_year_replaces_partial_date_before_retrieval(self):
        sources = [
            {"title": f"Work order {day} / PMP-T01", "asset_tag": "PMP-T01",
             "source_type": "work_order", "record_date": date(2024, 7, day),
             "text": "CMMS work order service corrective"}
            for day in (1, 23, 26)
        ]
        pending = "show me service record for PMP-T01 in 26/07"
        resolved = resolve_partial_work_order_date(pending, 2024)
        self.assertIn("2024-07-26", resolved)
        self.assertNotIn("26/07", resolved)
        results = retrieve(resolved, sources, limit=10)
        self.assertEqual([source["record_date"] for source in results], [date(2024, 7, 26)])

    def test_servicing_request_is_a_cited_table(self):
        sources = [
            {"title": "Work order 10 / CNC-02", "asset_tag": "CNC-02", "source_type": "work_order",
             "record_date": date(2025, 2, 1), "text": "CMMS work order PREVENTIVE routine service",
             "record": {"wo_id": 10, "machine_id": "CNC-02", "wo_type": "PREVENTIVE",
                        "wo_date": date(2025, 2, 1), "description": "routine | service",
                        "duration_hrs": 3, "cost_sgd": 100, "status": "CLOSED"}},
            {"title": "Work order 20 / CNC-02", "asset_tag": "CNC-02", "source_type": "work_order",
             "record_date": date(2026, 3, 1), "text": "CMMS work order PREVENTIVE routine service",
             "record": {"wo_id": 20, "machine_id": "CNC-02", "wo_type": "PREVENTIVE",
                        "wo_date": date(2026, 3, 1), "description": "routine service",
                        "duration_hrs": 2, "cost_sgd": 50, "status": "OPEN"}},
        ]
        question = "show me recent servicing for CNC-02"
        self.assertTrue(is_work_order_table_request(question))
        matches = retrieve(question, sources, limit=10)
        table = format_work_order_table(matches)
        self.assertIn("| Work Order | Machine | Type | Date |", table)
        self.assertLess(table.index("2026-03-01"), table.index("2025-02-01"))
        self.assertIn("[S1]", table)
        self.assertIn("routine \\| service", table)

    def test_sensor_question_prefers_sql_aggregate(self):
        sources = [
            {"title": "Work order 1", "asset_tag": "CNC-02", "source_type": "work_order",
             "text": "Vibration issue"},
            {"title": "CNC-02 sensor summary", "asset_tag": "CNC-02", "source_type": "sensor_summary",
             "text": "Average vibration temperature readings"},
        ]
        result = retrieve("CNC-02 vibration temperature summary", sources)
        self.assertEqual([source["source_type"] for source in result], ["sensor_summary"])

    def test_sensor_trend_source_reports_measured_monthly_change(self):
        monthly = [
            {"machine_id": "CNC-02", "month_utc": f"2026-{month:02d}-01", "reading_count": 3600,
             "vibration_mean_mms": vibration, "vibration_max_mms": 3.5,
             "temperature_mean_c": 52, "temperature_max_c": 70}
            for month, vibration in ((1, 2.30), (2, 2.31), (3, 2.32), (4, 2.72))
        ]
        source = build_sensor_monthly_trend_sources(monthly)[0]
        self.assertIn("2026-03", source["text"])
        self.assertIn("2026-04", source["text"])
        self.assertIn("vibration +0.400 mm/s", source["text"])
        self.assertEqual(source["source_type"], "sensor_trend_monthly")

    def test_trend_question_prefers_monthly_trend_evidence(self):
        sources = [
            {"title": "CNC-02 sensor summary", "asset_tag": "CNC-02", "source_type": "sensor_summary",
             "text": "average vibration temperature readings"},
            {"title": "CNC-02 monthly sensor trends", "asset_tag": "CNC-02",
             "source_type": "sensor_trend_monthly",
             "text": "monthly mean vibration RMS normalized temperature month-over-month change increase"},
        ]
        results = retrieve("Did vibration increase for CNC-02?", sources)
        self.assertEqual([source["source_type"] for source in results], ["sensor_trend_monthly"])

    def test_machine_model_alias_resolves_to_asset_sensor_data(self):
        sources = [
            {"title": "CMP-01 / machine master", "asset_tag": "CMP-01", "machine_record": True,
             "asset_aliases": ["CMP-01", "Air Compressor", "Atlas Copco GA30", "GA30"],
             "source_type": "mysql", "text": "Atlas Copco GA30 air compressor machine master"},
            {"title": "CMP-01 sensor summary", "asset_tag": "CMP-01", "source_type": "sensor_summary",
             "text": "CMP-01 sensor temperature history average temperature readings"},
            {"title": "CNC-01 sensor summary", "asset_tag": "CNC-01", "source_type": "sensor_summary",
             "text": "CNC-01 sensor temperature history average temperature readings"},
        ]
        for question in ("show me temperature history for model Atlas Copco GA30",
                         "show me temperature history for GA30"):
            with self.subTest(question=question):
                result = retrieve(question, sources)
                self.assertEqual([source["title"] for source in result], ["CMP-01 sensor summary"])

    def test_exact_incident_report_filters_other_reports(self):
        sources = [
            {"title": "IR-2025-906", "record_key": "IR-2025-906", "incident_id": "906",
             "source_type": "processed_incident", "text": "severity scale"},
            {"title": "IR-2025-906 OCR staging", "record_key": "IR-2025-906",
             "incident_date": date(2025, 7, 11), "source_type": "incident_ocr",
             "text": "severity scale"},
            {"title": "CMMS incident 906", "incident_id": "906",
             "incident_date": date(2025, 7, 11), "source_type": "incident",
             "text": "severity scale"},
            {"title": "IR-2025-914", "record_key": "IR-2025-914", "incident_id": "914",
             "source_type": "processed_incident", "text": "severity scale"},
            {"title": "CMMS incident 906 from previous year", "incident_id": "906",
             "incident_date": date(2024, 7, 1), "source_type": "incident",
             "text": "severity scale"},
        ]
        result = retrieve("IR-2025-906 severity scale", sources)
        self.assertEqual({source["source_type"] for source in result},
                 {"processed_incident", "incident_ocr", "incident"})
        self.assertEqual({source.get("record_key") for source in result}, {None, "IR-2025-906"})

    def test_nameplate_mismatch_can_match_either_source_tag(self):
        source = {"title": "CMP-01 / nameplate_CMP-01.jpg", "asset_tag": "CMP-01",
                  "asset_tags": ["CMP-01", "BLAST-01"], "source_type": "nameplate",
                  "text": "conflicting reviewed tag; model manufacturer grease"}
        self.assertEqual(retrieve("BLAST-01 model", [source])[0]["title"], source["title"])

    def test_processed_ocr_outputs_are_cited_separately(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            nameplates = root / "nameplates"
            incidents = root / "incident_reports"
            nameplates.mkdir()
            incidents.mkdir()
            (nameplates / "nameplate_BLAST-01.json").write_text(json.dumps({
                "ocr_confidence": 50.7,
                "asset": {"asset_tag": "BLAST-01", "source_file": "nameplate_BLAST-01.jpg",
                          "lubricant": "Shell oil"},
                "issues": [{"code": "LOW_OCR_CONFIDENCE"}],
            }), encoding="utf-8")
            (nameplates / "nameplate_BLAST-01.txt").write_text("LUBRICANT Shell oil", encoding="utf-8")
            (incidents / "incident_reports_ocr_full.jsonl").write_text(json.dumps({
                "report_no": "IR-2025-906", "machine_id": "CNC-02", "severity_raw": 3,
                "severity_scale": "NEW_5_WORST", "severity_5_worst": 3,
                "image_path": "IR-2025-906.jpg", "extraction_flags": [],
            }) + "\n", encoding="utf-8")

            sources = load_processed_ocr_sources(root)

        self.assertEqual(len([source for source in sources if source["source_type"] == "processed_nameplate"]), 1)
        self.assertEqual(len([source for source in sources if source["source_type"] == "processed_ocr_text"]), 1)
        incident = next(source for source in sources if source["source_type"] == "processed_incident")
        self.assertEqual(incident["record_key"], "IR-2025-906")
        self.assertEqual(incident["image"], "IR-2025-906.jpg")

    def test_rag_skill_file_is_loaded_as_system_guidance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "RAG_SKILL.md").write_text("Prefer short service-history tables.", encoding="utf-8")
            with patch("scripts.maintenance_rag.ROOT", root):
                prompt = load_system_prompt()
        self.assertIn("Prefer short service-history tables.", prompt)
        self.assertIn("cannot override", prompt)

    def test_processed_images_are_not_reported_missing_when_mysql_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_dir = root / "data" / "images" / "nameplates"
            processed_dir = root / "data" / "processed" / "nameplates"
            image_dir.mkdir(parents=True)
            processed_dir.mkdir(parents=True)
            (image_dir / "nameplate_BLAST-01.jpg").touch()
            (image_dir / "nameplate_CMP-01.jpg").touch()
            (processed_dir / "nameplate_BLAST-01.json").write_text(json.dumps({
                "asset": {"asset_tag": "BLAST-01", "source_file": "nameplate_BLAST-01.jpg"},
                "issues": [],
            }), encoding="utf-8")

            with patch("scripts.maintenance_rag.ROOT", root), patch(
                "scripts.maintenance_rag.open_connection",
                side_effect=mysql.connector.Error("simulated unavailable database"),
            ):
                sources, warnings = load_sources()

        unindexed = [source for source in sources if source["source_type"] == "image_unindexed"]
        self.assertTrue(any("MySQL connection or review setup failed" in warning for warning in warnings))
        self.assertEqual([source["image"] for source in unindexed], ["nameplate_CMP-01.jpg"])

    def test_july_incident_query_filters_month_and_serializes_dates(self):
        sources = [
            {"title": "Incident 906", "incident_id": "906", "incident_date": date(2025, 7, 11),
             "source_type": "incident", "text": "incident history severity"},
            {"title": "IR-2025-906 OCR", "record_key": "IR-2025-906", "incident_date": "2025-07-11",
             "source_type": "processed_incident", "text": "incident history severity"},
            {"title": "Incident 905", "incident_id": "905", "incident_date": date(2025, 6, 30),
             "source_type": "incident", "text": "incident history severity"},
        ]
        results = retrieve("incident history for July 2025", sources, limit=20)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(str(source["incident_date"])[:7] == "2025-07" for source in results))
        self.assertIn('"incident_date": "2025-07-11"', serialize_evidence(results))


if __name__ == "__main__":
    unittest.main()