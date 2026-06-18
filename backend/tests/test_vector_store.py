import unittest
from unittest.mock import patch

from backend.models.tags import DocTags, RowTag
from backend.services import vector_store


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _query):
        return self

    def fetchall(self):
        return self._rows


class VectorStoreQueueTest(unittest.TestCase):
    def test_review_queue_skips_and_cleans_stale_rows_without_chunks(self):
        doc_tags = DocTags(
            doc_id="doc-1",
            rows={
                "FRCA::16": RowTag(
                    category_tag="Translation",
                    detail_tags=["ambiguous reference"],
                    confidence=0.5,
                    review_required=True,
                    review_reason="Needs context.",
                ),
                "JAJP::3": RowTag(
                    category_tag="Translation",
                    detail_tags=["terminology"],
                    confidence=0.6,
                    review_required=True,
                    review_reason="Low confidence.",
                ),
            },
        )
        cleaned = {}

        with (
            patch.object(vector_store, "list_docs", return_value=[{"doc_id": "doc-1", "title": "Doc", "code": "VSD0231", "sprint": "", "category": "VSD"}]),
            patch.object(vector_store.tags_store, "iter_all", return_value=[doc_tags]),
            patch.object(vector_store.tags_store, "delete_rows", side_effect=lambda doc_id, keys: cleaned.setdefault(doc_id, list(keys)) or doc_tags),
            patch.object(vector_store.duck_lance_store, "duck", return_value=_FakeConn([
                ("doc-1", "JAJP::3", "JAJP", 3, "live chunk text"),
            ])),
        ):
            rows = vector_store.list_review_rows()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["row_key"], "JAJP::3")
        self.assertEqual(cleaned["doc-1"], ["FRCA::16"])


if __name__ == "__main__":
    unittest.main()
