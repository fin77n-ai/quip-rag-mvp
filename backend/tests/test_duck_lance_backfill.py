import unittest
from unittest.mock import patch

import duckdb

from backend.services import duck_lance_store


class DuckLanceBackfillTest(unittest.TestCase):
    def _make_conn(self):
        conn = duckdb.connect(":memory:")
        conn.execute("""
            CREATE TABLE chunks (
                chunk_id TEXT PRIMARY KEY,
                doc_id TEXT,
                title TEXT,
                category TEXT,
                code TEXT,
                sprint TEXT,
                sheet TEXT,
                row_index INTEGER,
                row_key TEXT,
                tags TEXT,
                is_issue TEXT,
                issue_summary TEXT,
                issue_type TEXT,
                owner TEXT,
                status TEXT,
                taxonomy_category TEXT,
                taxonomy_subcategory TEXT,
                taxonomy_tags TEXT,
                taxonomy_confidence DOUBLE,
                taxonomy_rationale TEXT,
                retake_explicit TEXT,
                retake_terms TEXT,
                issue_key TEXT,
                text TEXT,
                word_count INTEGER
            )
        """)
        return conn

    def test_backfill_retake_fields_updates_existing_chunks(self):
        conn = self._make_conn()
        conn.execute(
            """
            INSERT INTO chunks (
                chunk_id, doc_id, title, category, code, sprint, sheet, row_index, row_key, tags,
                is_issue, issue_summary, issue_type, owner, status,
                taxonomy_category, taxonomy_subcategory, taxonomy_tags, taxonomy_confidence, taxonomy_rationale,
                retake_explicit, retake_terms, issue_key, text, word_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc-1::0", "doc-1", "Video One", "MS", "MS0001", "MS19", "FRFR", 2, "FRFR::2", "Source",
                "", "", "", "", "",
                "", "", "", 0.0, "",
                "", "", "", "Description/ Comment: VO needs retake and should be re-recorded.", 9,
            ),
        )

        with (
            patch.object(duck_lance_store, "duck", return_value=conn),
            patch.object(duck_lance_store, "_lance_table", return_value=None),
            patch.object(duck_lance_store, "is_enabled", return_value=True),
        ):
            result = duck_lance_store.backfill_retake_fields()

        row = conn.execute("SELECT retake_explicit, retake_terms FROM chunks WHERE chunk_id = ?", ["doc-1::0"]).fetchone()
        self.assertEqual(result, {"updated": 1, "scanned": 1})
        self.assertEqual(row[0], "yes")
        self.assertIn("retake", row[1])


if __name__ == "__main__":
    unittest.main()
