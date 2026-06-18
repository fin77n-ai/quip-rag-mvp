import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from backend.api import documents
from backend.config import settings


class DocumentsApiTest(unittest.IsolatedAsyncioTestCase):
    def test_reprocess_source_paths_preserve_selection_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_quip_dir = settings.quip_dir
            settings.quip_dir = Path(tmpdir)
            (settings.quip_dir / "quip-key.json").write_text(
                json.dumps({"thread_id": "doc-1"}), encoding="utf-8"
            )
            try:
                paths = documents._reprocess_source_paths(["doc-2", "doc-1", "doc-2"])
                empty_paths = documents._reprocess_source_paths([])
            finally:
                settings.quip_dir = original_quip_dir

        self.assertEqual([path.name for path in paths], ["doc-2.json", "quip-key.json"])
        self.assertEqual(empty_paths, [])

    async def test_reprocess_document_rebuilds_from_saved_local_source(self):
        raw_doc = {
            "thread_id": "doc-1",
            "title": "MS0001_Test",
            "created_usec": 0,
            "updated_usec": 0,
            "html": "<html></html>",
        }

        parsed = type("Parsed", (), {"doc_id": "doc-1", "prefix": "MS"})()
        chunks = [
            {
                "metadata": {"row_key": "ENGB::1", "is_issue": "yes"},
                "text": "Example issue",
                "embed_text": "Example issue",
            }
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            original_quip_dir = settings.quip_dir
            settings.quip_dir = Path(tmpdir)
            (settings.quip_dir / "quip-key.json").write_text(json.dumps(raw_doc), encoding="utf-8")

            try:
                with (
                    patch.object(documents.rules_store, "load", return_value=object()),
                    patch.object(documents.auto_tagger, "auto_tag_doc"),
                    patch.object(documents.quip_parser, "parse_dict", return_value=parsed),
                    patch.object(documents.vector_store, "delete_doc"),
                    patch.object(documents.chunker, "chunk_doc", return_value=chunks),
                    patch.object(documents.vector_store, "upsert_chunks"),
                    patch.object(documents.tags_store, "load", return_value=type("SavedTags", (), {"rows": {"ENGB::1": type("Row", (), {"excluded": False})()}})()),
                ):
                    result = await documents.reprocess_document("doc-1")
            finally:
                settings.quip_dir = original_quip_dir

        self.assertEqual(result.doc_id, "doc-1")
        self.assertEqual(result.chunks, 1)
        self.assertEqual(result.issue_rows, 1)
        self.assertEqual(result.excluded_rows, 0)

    async def test_reprocess_document_raises_404_when_saved_source_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_quip_dir = settings.quip_dir
            settings.quip_dir = Path(tmpdir)
            try:
                with self.assertRaises(HTTPException) as ctx:
                    await documents.reprocess_document("missing-doc")
            finally:
                settings.quip_dir = original_quip_dir

        self.assertEqual(ctx.exception.status_code, 404)

    async def test_reprocess_all_documents_reprocesses_every_saved_source(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_quip_dir = settings.quip_dir
            settings.quip_dir = Path(tmpdir)
            for doc_id in ("doc-1", "doc-2"):
                (settings.quip_dir / f"{doc_id}.json").write_text("{}", encoding="utf-8")

            try:
                with patch.object(documents, "_reprocess_document", side_effect=[
                    documents.ReprocessResponse(doc_id="doc-1", chunks=3, issue_rows=2, excluded_rows=1, source_path="a"),
                    documents.ReprocessResponse(doc_id="doc-2", chunks=4, issue_rows=3, excluded_rows=0, source_path="b"),
                ]):
                    result = await documents.reprocess_all_documents()
            finally:
                settings.quip_dir = original_quip_dir

        self.assertEqual(result.total_sources, 2)
        self.assertEqual(result.reprocessed, 2)
        self.assertEqual(result.failed, [])
        self.assertEqual([doc.doc_id for doc in result.docs], ["doc-1", "doc-2"])

    async def test_reprocess_all_documents_collects_failures_and_continues(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            original_quip_dir = settings.quip_dir
            settings.quip_dir = Path(tmpdir)
            for doc_id in ("doc-1", "doc-2"):
                (settings.quip_dir / f"{doc_id}.json").write_text("{}", encoding="utf-8")

            try:
                with patch.object(documents, "_reprocess_document", side_effect=[
                    documents.ReprocessResponse(doc_id="doc-1", chunks=3, issue_rows=2, excluded_rows=1, source_path="a"),
                    HTTPException(400, "broken"),
                ]):
                    result = await documents.reprocess_all_documents()
            finally:
                settings.quip_dir = original_quip_dir

        self.assertEqual(result.total_sources, 2)
        self.assertEqual(result.reprocessed, 1)
        self.assertEqual(len(result.failed), 1)
        self.assertEqual(result.failed[0]["doc_id"], "doc-2")


if __name__ == "__main__":
    unittest.main()
