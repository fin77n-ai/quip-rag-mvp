import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import duckdb

from backend.models.taxonomy import TaxonomyFeedbackApplySimilarRequest, TaxonomyFeedbackRequest, TaxonomyStore
from backend.models.tags import DocTags, RowTag
from backend.services import duck_lance_store, tags_store, taxonomy_store


class TaxonomyStoreTest(unittest.TestCase):
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
                issue_key TEXT,
                text TEXT,
                word_count INTEGER
            )
        """)
        conn.execute("""
            CREATE TABLE taxonomy_predictions (
                row_id TEXT PRIMARY KEY,
                predicted_category TEXT,
                predicted_subcategory TEXT,
                predicted_tags TEXT,
                confidence DOUBLE,
                rationale TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.execute("""
            CREATE TABLE taxonomy_feedback (
                row_id TEXT,
                predicted_category TEXT,
                predicted_subcategory TEXT,
                predicted_tags TEXT,
                final_category TEXT,
                final_subcategory TEXT,
                final_tags TEXT,
                action TEXT,
                reviewer TEXT,
                review_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                rationale TEXT,
                UNIQUE(row_id)
            )
        """)
        return conn

    def test_canonical_category_maps_to_fixed_top_level(self):
        self.assertEqual(
            taxonomy_store.canonical_category_for_text(
                "Audio and Video Sync",
                "Animation and Voiceover Timing",
                ["animation-timing"],
                dept_tags=["Motion"],
            ),
            "Animation",
        )
        self.assertEqual(
            taxonomy_store.canonical_category_for_text(
                "Localized Asset Content",
                "Title Translation Consistency",
                ["translation"],
                dept_tags=["Copy"],
            ),
            "Translation",
        )
        self.assertEqual(
            taxonomy_store.canonical_category_for_text(
                "Voiceover Recording",
                "Voiceover Pacing and Pauses",
                ["voiceover", "pacing"],
            ),
            "Voice Over",
        )

    def test_standard_subcategory_maps_to_bucket(self):
        self.assertEqual(
            taxonomy_store.standard_subcategory_for_text(
                "Animation",
                "Frozen Frames or Stuttering",
                ["choppy", "playback"],
            ),
            "Glitchy or Choppy Playback",
        )
        self.assertEqual(
            taxonomy_store.standard_subcategory_for_text(
                "Translation",
                "Thumbnail Title Alignment",
                ["title-translation"],
            ),
            "Title / Heading Translation",
        )
        self.assertEqual(
            taxonomy_store.standard_subcategory_for_text(
                "Voice Over",
                "Voiceover Pacing and Pauses",
                ["pause"],
            ),
            "Pacing / Pauses",
        )

    def test_rewrite_all_row_tags_applies_mappings(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            row_dir = tmp_path / "row_tags"
            row_dir.mkdir()
            tax_path = tmp_path / "taxonomy.json"
            tax_path.write_text(
                TaxonomyStore(
                    mappings={
                        "Login Issue > Password Reset": "Account Access > Password Reset"
                    }
                ).model_dump_json(),
                encoding="utf-8",
            )
            (row_dir / "doc-1.json").write_text(
                DocTags(
                    doc_id="doc-1",
                    rows={
                        "ZHCN::3": RowTag(
                            taxonomy_category="Login Issue",
                            taxonomy_subcategory="Password Reset",
                            taxonomy_tags=["password"],
                        )
                    },
                ).model_dump_json(),
                encoding="utf-8",
            )

            with (
                patch.object(taxonomy_store, "_PATH", tax_path),
                patch.object(taxonomy_store, "_ROW_TAG_DIR", row_dir),
            ):
                updates = taxonomy_store.rewrite_all_row_tags()

            self.assertEqual(updates, [{"doc_id": "doc-1", "rows": ["ZHCN::3"]}])
            updated = DocTags.model_validate_json((row_dir / "doc-1.json").read_text(encoding="utf-8"))
            self.assertEqual(updated.rows["ZHCN::3"].taxonomy_category, "Account Access")
            self.assertEqual(updated.rows["ZHCN::3"].taxonomy_subcategory, "Password Reset")

    def test_save_feedback_updates_chunk_and_row_tags_for_doc_scoped_row_id(self):
        conn = self._make_conn()
        conn.execute(
            """
            INSERT INTO chunks (
                chunk_id, doc_id, title, category, code, sprint, sheet, row_index, row_key, tags,
                taxonomy_category, taxonomy_subcategory, taxonomy_tags, taxonomy_confidence, text, word_count
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "doc-1::0", "doc-1", "Video One", "MS", "MS0001", "MS19", "ZHCN", 3, "ZHCN::3", "Copy",
                "Translation", "UI Text Accuracy", "copy", 0.42, "example text", 2,
            ),
        )

        with tempfile.TemporaryDirectory() as tmp:
            row_dir = Path(tmp)
            with (
                patch.object(taxonomy_store, "duck", return_value=conn),
                patch.object(tags_store, "_DIR", row_dir),
                patch.object(duck_lance_store, "duck", return_value=conn),
                patch.object(duck_lance_store, "_lance_table", return_value=None),
                patch.object(duck_lance_store, "is_enabled", return_value=True),
            ):
                tags_store.save(DocTags(
                    doc_id="doc-1",
                    rows={"ZHCN::3": RowTag(tags=["Copy"], taxonomy_category="Translation", taxonomy_subcategory="UI Text Accuracy")},
                ))
                taxonomy_store.save_feedback(TaxonomyFeedbackRequest(
                    row_id="doc-1::ZHCN::3",
                    predicted_category="Translation",
                    predicted_subcategory="UI Text Accuracy",
                    final_category="Animation",
                    final_subcategory="Layout / Position Alignment",
                    final_tags=["layout-alignment"],
                    action="edit",
                    reviewer="test",
                    rationale="human corrected",
                ))

                chunk = conn.execute(
                    "SELECT taxonomy_category, taxonomy_subcategory, taxonomy_tags, taxonomy_confidence FROM chunks WHERE doc_id = ? AND row_key = ?",
                    ("doc-1", "ZHCN::3"),
                ).fetchone()
                saved = tags_store.load("doc-1")

        self.assertEqual(chunk[0], "Animation")
        self.assertEqual(chunk[1], "Layout / Position Alignment")
        self.assertEqual(chunk[2], "layout-alignment")
        self.assertEqual(chunk[3], 1.0)
        self.assertEqual(saved.rows["ZHCN::3"].taxonomy_category, "Animation")
        self.assertEqual(saved.rows["ZHCN::3"].taxonomy_subcategory, "Layout / Position Alignment")
        self.assertEqual(saved.rows["ZHCN::3"].taxonomy_tags, ["layout-alignment"])

    def test_apply_feedback_to_similar_only_updates_matching_rows_not_seed_row(self):
        conn = self._make_conn()
        rows = [
            ("doc-1::0", "doc-1", "ZHCN::3", "Translation", "UI Text Accuracy", 0.40),
            ("doc-2::0", "doc-2", "FRCA::5", "Translation", "UI Text Accuracy", 0.35),
            ("doc-3::0", "doc-3", "JAJP::7", "Translation", "UI Text Accuracy", 0.95),
            ("doc-4::0", "doc-4", "DEDE::2", "Animation", "Layout / Position Alignment", 0.20),
        ]
        for chunk_id, doc_id, row_key, cat, sub, conf in rows:
            conn.execute(
                """
                INSERT INTO chunks (
                    chunk_id, doc_id, title, category, code, sprint, sheet, row_index, row_key, tags,
                    taxonomy_category, taxonomy_subcategory, taxonomy_tags, taxonomy_confidence, text, word_count
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    chunk_id, doc_id, "Video", "MS", "MS0001", "MS19", row_key.split("::", 1)[0], 1, row_key, "Copy",
                    cat, sub, "", conf, "example", 1,
                ),
            )
        conn.execute(
            """
            INSERT INTO taxonomy_predictions (row_id, predicted_category, predicted_subcategory, predicted_tags, confidence, rationale)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            ("doc-1::ZHCN::3", "Translation", "UI Text Accuracy", "", 0.40, "seed"),
        )

        with tempfile.TemporaryDirectory() as tmp:
            row_dir = Path(tmp)
            with (
                patch.object(taxonomy_store, "duck", return_value=conn),
                patch.object(tags_store, "_DIR", row_dir),
                patch.object(duck_lance_store, "duck", return_value=conn),
                patch.object(duck_lance_store, "_lance_table", return_value=None),
                patch.object(duck_lance_store, "is_enabled", return_value=True),
            ):
                for _chunk_id, doc_id, row_key, cat, sub, conf in rows:
                    tags_store.save(DocTags(
                        doc_id=doc_id,
                        rows={row_key: RowTag(taxonomy_category=cat, taxonomy_subcategory=sub, taxonomy_confidence=conf)},
                    ))

                count = taxonomy_store.apply_feedback_to_similar(TaxonomyFeedbackApplySimilarRequest(
                    row_id="doc-1::ZHCN::3",
                    final_category="Animation",
                    final_subcategory="Layout / Position Alignment",
                    final_tags=["layout-alignment"],
                    reviewer="test",
                    rationale="apply batch",
                ))

                updated = conn.execute(
                    "SELECT doc_id, row_key, taxonomy_category, taxonomy_subcategory, taxonomy_tags FROM chunks ORDER BY doc_id"
                ).fetchall()
                feedback_rows = conn.execute(
                    "SELECT row_id, action FROM taxonomy_feedback ORDER BY row_id"
                ).fetchall()

        self.assertEqual(count, 1)
        by_doc = {(doc_id, row_key): (cat, sub, tags) for doc_id, row_key, cat, sub, tags in updated}
        self.assertEqual(by_doc[("doc-1", "ZHCN::3")], ("Translation", "UI Text Accuracy", ""))
        self.assertEqual(by_doc[("doc-2", "FRCA::5")], ("Animation", "Layout / Position Alignment", "layout-alignment"))
        self.assertEqual(by_doc[("doc-3", "JAJP::7")], ("Translation", "UI Text Accuracy", ""))
        self.assertEqual(by_doc[("doc-4", "DEDE::2")], ("Animation", "Layout / Position Alignment", ""))
        self.assertEqual(feedback_rows, [("doc-2::FRCA::5", "auto-apply")])


if __name__ == "__main__":
    unittest.main()
