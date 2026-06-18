import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from backend.services import duck_lance_store


class DuckLanceStoreTest(unittest.TestCase):
    def test_get_chunks_exposes_legacy_tag_fields_from_taxonomy_columns(self):
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
                is_noise TEXT,
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
        conn.execute(
            """
            INSERT INTO chunks (
                chunk_id, doc_id, title, category, code, sprint, sheet, row_index, row_key, tags,
                is_issue, issue_summary, issue_type, owner, status, is_noise,
                taxonomy_category, taxonomy_subcategory, taxonomy_tags, taxonomy_confidence, taxonomy_rationale,
                retake_explicit, retake_terms, issue_key, text, word_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc-1::0", "doc-1", "Video", "VSD", "VSD0231", "MS26", "JAJP", 3, "JAJP::3", "Translation",
                "", "", "", "", "", "no",
                "Translation", "Workflow", "status update", 0.91, "Human reviewed",
                "", "", "issue-key", "example text", 2,
            ),
        )

        with (
            patch.object(duck_lance_store, "duck", return_value=conn),
            patch.object(duck_lance_store, "is_enabled", return_value=True),
        ):
            chunks = duck_lance_store.get_chunks("doc-1")

        self.assertEqual(len(chunks), 1)
        meta = chunks[0]["metadata"]
        self.assertEqual(meta["category_tag"], "Translation")
        self.assertEqual(meta["detail_tags"], "status update")
        self.assertEqual(meta["confidence"], 0.91)
        self.assertEqual(meta["rationale"], "Human reviewed")
        self.assertIsNone(meta["processed_at"])

    def test_list_docs_returns_latest_processed_time(self):
        conn = duckdb.connect(":memory:")
        conn.execute("""
            CREATE TABLE chunks (
                doc_id TEXT,
                code TEXT,
                title TEXT,
                category TEXT,
                sprint TEXT,
                is_noise TEXT,
                processed_at TEXT
            )
        """)
        conn.executemany(
            "INSERT INTO chunks VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                ("doc-1", "MS01", "Video", "MS", "MS01", "no", "2026-06-16T08:00:00+00:00"),
                ("doc-1", "MS01", "Video", "MS", "MS01", "no", "2026-06-17T09:30:00+00:00"),
            ],
        )

        with (
            patch.object(duck_lance_store, "duck", return_value=conn),
            patch.object(duck_lance_store, "is_enabled", return_value=True),
        ):
            docs = duck_lance_store.list_docs()

        self.assertEqual(docs[0]["last_processed_at"], "2026-06-17T09:30:00+00:00")

    def test_memory_from_current_row_does_not_append_an_extra_column(self):
        row = tuple(f"value-{index}" for index in range(len(duck_lance_store.CHUNK_SELECT_COLUMNS)))

        memory = duck_lance_store._memory_from_row(row)

        self.assertEqual(memory["chunk_id"], "value-0")
        self.assertEqual(memory["metadata"]["processed_at"], "value-29")


if __name__ == "__main__":
    unittest.main()
