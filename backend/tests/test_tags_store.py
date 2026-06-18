import unittest
from unittest.mock import patch

from backend.models.tags import DocTags, RowTag
from backend.services import tags_store


class TagsStoreTest(unittest.TestCase):
    def test_delete_row_removes_target_key(self):
        saved = {}
        original = DocTags(
            doc_id="doc-1",
            rows={
                "DEDE::2": RowTag(tags=["Copy"]),
                "FRCA::4": RowTag(tags=["Motion"]),
            },
        )

        with (
            patch.object(tags_store, "load", return_value=original),
            patch.object(tags_store, "save", side_effect=lambda tags: saved.setdefault("tags", tags)),
        ):
            updated = tags_store.delete_row("doc-1", "DEDE::2")

        self.assertNotIn("DEDE::2", updated.rows)
        self.assertIn("FRCA::4", updated.rows)
        self.assertIs(saved["tags"], updated)

    def test_clear_excluded_preserves_tags_and_removes_empty_rows(self):
        saved = {}
        original = DocTags(
            doc_id="doc-1",
            rows={
                "DEDE::2": RowTag(tags=["Copy"], excluded=True, is_noise=True),
                "ENGB::3": RowTag(tags=[], excluded=True),
                "FRCA::4": RowTag(tags=["Motion"], excluded=False),
            },
        )

        with (
            patch.object(tags_store, "load", return_value=original),
            patch.object(tags_store, "save", side_effect=lambda tags: saved.setdefault("tags", tags)),
        ):
            updated = tags_store.clear_excluded("doc-1")

        self.assertEqual(updated.rows["DEDE::2"].tags, ["Copy"])
        self.assertFalse(updated.rows["DEDE::2"].excluded)
        self.assertFalse(updated.rows["DEDE::2"].is_noise)
        self.assertNotIn("ENGB::3", updated.rows)
        self.assertEqual(updated.rows["FRCA::4"].tags, ["Motion"])
        self.assertIs(saved["tags"], updated)


if __name__ == "__main__":
    unittest.main()
