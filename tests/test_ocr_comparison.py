import csv
from pathlib import Path
import tempfile
import unittest

import numpy as np

from scripts.compare_ocr import canonical, compare_field, data_text, easy_data, load_gold, write_reports
from scripts.ingest_incident_reports import read_fields
from scripts.nameplate_ocr_import import ocr_image


class ComparisonTests(unittest.TestCase):
    def test_easy_boxes_form_lines(self):
        results = [([[80, 12], [140, 12], [140, 32], [80, 32]], "15 kW", 0.8),
                   ([[0, 10], [70, 10], [70, 30], [0, 30]], "POWER", 0.9),
                   ([[0, 50], [70, 50], [70, 70], [0, 70]], "WEIGHT", 0.7)]
        text, confidence = data_text(easy_data(results))
        self.assertEqual(text, "POWER 15 kW\nWEIGHT")
        self.assertAlmostEqual(confidence, 80)

    def test_incident_adapter_receives_all_fields(self):
        calls = []

        def runner(image, **kwargs):
            calls.append(kwargs)
            return "example", 80

        readings, confidence = read_fields(np.full((800, 800, 3), 255, dtype=np.uint8), ocr_runner=runner)
        self.assertEqual(len(calls), 11)
        self.assertEqual(readings["severity_raw"], "example")
        self.assertEqual(confidence["severity_label"], 80)

    def test_nameplate_adapter(self):
        def reader(image, **kwargs):
            return easy_data([([[0, 0], [100, 0], [100, 30], [0, 30]], "POWER 15 kW", 0.9)])

        raw, confidence, _, _ = ocr_image(np.full((100, 200, 3), 255, dtype=np.uint8), data_reader=reader)
        self.assertEqual(raw, "POWER 15 kW")
        self.assertEqual(confidence, 90)

    def test_numeric_equivalence(self):
        self.assertEqual(canonical("15.00", "power_kw"), canonical(15, "power_kw"))

    def test_agreement_is_not_accuracy(self):
        pair = {engine: {"values": {"plate_tag": "CNC-01"}, "error": ""} for engine in ("tesseract", "easyocr")}
        row = compare_field("nameplate", "photo.jpg", "plate_tag", pair, {})
        self.assertEqual(row["agreement"], "AGREE")
        self.assertEqual(row["tesseract_correct"], "")
        row = compare_field("nameplate", "photo.jpg", "plate_tag", pair,
                            {("nameplate", "photo.jpg", "plate_tag"): "CNC-02"})
        self.assertEqual(row["tesseract_correct"], 0)

    def test_reports_and_review_template(self):
        pair = {engine: {"values": {}, "confidence": 0, "seconds": 1, "error": "", "flags": []}
                for engine in ("tesseract", "easyocr")}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_reports([{"kind": "nameplate", "source_file": "photo.jpg", "engines": pair}],
                          output, {}, {"easyocr_initialization_seconds": 0})
            self.assertEqual(load_gold(output / "ground_truth_template.csv"), {})
            with (output / "engine_summary.csv").open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            self.assertEqual(rows[0]["accuracy_percent"], "")
            self.assertTrue((output / "field_comparison.csv").exists())

    def test_template_expands_without_losing_review(self):
        pair = {engine: {"values": {"power_kw": 15}, "confidence": 80, "seconds": 1,
                         "error": "", "flags": []} for engine in ("tesseract", "easyocr")}
        metadata = {"easyocr_initialization_seconds": 0}
        first = {"kind": "nameplate", "source_file": "first.jpg", "engines": pair}
        second = {"kind": "nameplate", "source_file": "second.jpg", "engines": pair}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            write_reports([first], output, {}, metadata)
            template = output / "ground_truth_template.csv"
            with template.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))
            reviewed = next(row for row in rows if row["field"] == "power_kw")
            reviewed.update(expected_value="15", reviewed="yes")
            with template.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            write_reports([first, second], output, load_gold(template), metadata)
            self.assertEqual(load_gold(template)[("nameplate", "first.jpg", "power_kw")], "15")
            with template.open(encoding="utf-8-sig", newline="") as handle:
                self.assertEqual(len(list(csv.DictReader(handle))), 26)


if __name__ == "__main__":
    unittest.main()