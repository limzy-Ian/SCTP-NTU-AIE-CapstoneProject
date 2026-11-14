import unittest

from scripts.maintenance_rag import retrieve
from tests.fixtures import build_fixture_sources, load_fixture_sources

REQUIRED_KEYS = {"title", "text", "location", "source_type"}


class FixtureCorpusTests(unittest.TestCase):
    def test_loader_returns_sources_and_warnings(self):
        sources, warnings = load_fixture_sources()
        self.assertGreaterEqual(len(sources), 18)
        self.assertEqual(warnings, [])

    def test_every_source_has_required_keys(self):
        for source in build_fixture_sources():
            self.assertTrue(REQUIRED_KEYS.issubset(source), source.get("title"))

    def test_covers_each_source_type(self):
        types = {source["source_type"] for source in build_fixture_sources()}
        for expected in ("mysql", "nameplate", "work_order", "incident", "incident_ocr",
                         "document", "tabular", "sensor_summary", "sensor_trend_monthly"):
            self.assertIn(expected, types)

    def test_loader_returns_fresh_copies(self):
        first = build_fixture_sources()
        first[0]["title"] = "changed"
        self.assertNotEqual(build_fixture_sources()[0]["title"], "changed")

    def test_retrieve_accepts_fixture_corpus(self):
        results = retrieve("work orders for TST-01", build_fixture_sources())
        self.assertTrue(results)
        self.assertTrue(all(result["id"].startswith("S") for result in results))


if __name__ == "__main__":
    unittest.main()
