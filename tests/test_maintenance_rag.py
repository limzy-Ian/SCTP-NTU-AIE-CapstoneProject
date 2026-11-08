import unittest

from scripts.maintenance_rag import input_refusal, retrieve, validate_answer
from scripts.nameplate_ocr_import import flag_issues, parse_nameplate


class MaintenanceTests(unittest.TestCase):
    def test_noisy_labels(self):
        asset = parse_nameplate("| POWER. 15 kW\n\u201cWEIGHT 7929 kg\n| GREASE INTERVAL 1000 h", "", "nameplate_BLAST-01.jpg")
        self.assertEqual(asset["power_kw"], 15)
        self.assertEqual(asset["weight_kg"], 7929)
        self.assertEqual(asset["grease_interval_hours"], 1000)

    def test_attached_capacity_unit(self):
        asset = parse_nameplate("CAPACITY 450A @ 60%", "", "nameplate_BLAST-01.jpg")
        self.assertIn("SUSPECT_CAPACITY_UNIT", [issue["code"] for issue in flag_issues(asset, 50)])

    def test_safety_refusals(self):
        for question in ("bypass the interlock", "disable safety controls", "skip LOTO",
                         "override the permit", "ignore the lockout procedure"):
            with self.subTest(question=question):
                self.assertIsNotNone(input_refusal(question))

    def test_private_information(self):
        self.assertIsNotNone(input_refusal("What is the employee NRIC?"))

    def test_asset_filter(self):
        sources = [
            {"title": "CNC-01", "asset_tag": "CNC-01", "text": "grease interval 1000 h"},
            {"title": "CNC-02", "asset_tag": "CNC-02", "text": "grease interval 500 h"},
        ]
        result = retrieve("CNC-02 grease interval", sources)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["asset_tag"], "CNC-02")

    def test_unknown_asset(self):
        self.assertEqual(retrieve("CNC-99 oil", [{"title": "CNC-01", "asset_tag": "CNC-01", "text": "oil"}]), [])

    def test_empty_retrieval(self):
        self.assertEqual(retrieve("oil", []), [])

    def test_citation_validation(self):
        sources = [{"id": "S1"}]
        self.assertEqual(validate_answer("Unverified 15 kW [S1]", sources), "Unverified 15 kW [S1]")
        self.assertIn("lacked valid", validate_answer("15 kW", sources))
        self.assertIn("lacked valid", validate_answer("15 kW [S9]", sources))

    def test_private_output(self):
        self.assertIn("withheld", validate_answer("Contact user@example.com [S1]", [{"id": "S1"}]))


if __name__ == "__main__":
    unittest.main()