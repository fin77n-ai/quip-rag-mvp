import unittest
from unittest.mock import patch

from backend.api import analytics


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeConn:
    def execute(self, query: str):
        if "PRAGMA table_info('chunks')" in query:
            return _FakeCursor([
                (0, "chunk_id", "TEXT", False, None, False),
                (1, "sprint", "TEXT", False, None, False),
                (2, "sheet", "TEXT", False, None, False),
                (3, "title", "TEXT", False, None, False),
            ])
        if "FROM chunks" in query and "COUNT(*) as issue_count" in query:
            return _FakeCursor([
                ("MS12", "PTBR", 3),
                ("MS12", "JAJP", 2),
                ("Backlog", "ENGB", 99),
            ])
        raise AssertionError(f"Unexpected query: {query}")


class AnalyticsApiTest(unittest.TestCase):
    def test_vendor_profiles_use_summary_categories_without_grammar(self):
        rws = analytics.get_deterministic_splits("overall_RWS", 100)
        bal = analytics.get_deterministic_splits("overall_BAL", 100)

        self.assertEqual(next(item["value"] for item in rws["categories"] if item["name"] == "Animation"), 0)
        self.assertEqual(next(item["value"] for item in bal["categories"] if item["name"] == "Translation"), 0)
        self.assertGreater(next(item["value"] for item in bal["categories"] if item["name"] == "Animation"), 0)
        self.assertNotIn("Grammar", {item["name"] for item in rws["sub_categories"]})
        self.assertIn("Validation", {item["name"] for item in rws["sub_categories"]})
        self.assertIn("Post Editing", {item["name"] for item in bal["sub_categories"]})

    def test_dashboard_overall_handles_chunks_without_language_column(self):
        with patch.object(analytics.vector_store, "duck", return_value=_FakeConn(), create=True):
            result = analytics.get_dashboard_overall()

        self.assertEqual(len(result["trends"]), 1)
        self.assertEqual(result["trends"][0]["sprint"], "MS12")
        self.assertEqual(result["trends"][0]["total_issues"], 5)
        self.assertEqual(result["trends"][0]["languages"], {"PTBR": 3, "JAJP": 2})


if __name__ == "__main__":
    unittest.main()
