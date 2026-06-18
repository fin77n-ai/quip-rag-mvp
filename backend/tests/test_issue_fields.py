import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from backend.models.quip import ParsedDoc
from backend.models.tags import DocTags, RowTag
from backend.services import chunker, issue_fields


class IssueFieldsTest(unittest.TestCase):
    def test_extract_issue_fields_from_quip_row_aliases(self):
        fields = issue_fields.extract_issue_fields({
            "Issue?": "Yes",
            "Issue One-liner": "Final VO has repeated mouth noises.",
            "Issue Type": "real/final VO noise",
            "Owner": "VO",
            "Status": "Fixed",
        })

        self.assertEqual(fields["is_issue"], "yes")
        self.assertEqual(fields["issue_summary"], "Final VO has repeated mouth noises.")
        self.assertEqual(fields["issue_type"], "real/final VO noise")
        self.assertEqual(fields["owner"], "VO")
        self.assertEqual(fields["status"], "resolved")

    def test_row_chunk_uses_short_issue_packet_and_metadata(self):
        doc = ParsedDoc(
            doc_id="doc-1",
            title="MS0001_Test",
            prefix="MS",
            code="MS0001",
            plain_text="",
            sections=[],
            word_count=0,
            created_at=datetime.now(timezone.utc),
            updated_at=datetime.now(timezone.utc),
            table_rows=[
                {
                    "sheet": "FRFR",
                    "row_index": 2,
                    "cells": {
                        "Issue?": "yes",
                        "Issue One-liner": "Final VO has repeated mouth noises.",
                        "Description/ Comment": "There are mouth noises throughout.",
                    },
                    "issue_fields": {
                        "is_issue": "yes",
                        "issue_summary": "Final VO has repeated mouth noises.",
                        "issue_type": "real/final VO noise",
                    },
                }
            ],
        )

        with patch.object(chunker.tags_store, "load", return_value=DocTags(doc_id="doc-1")):
            chunks = chunker.chunk_doc(doc)

        self.assertEqual(len(chunks), 1)
        self.assertIn("Issue: Final VO has repeated mouth noises.", chunks[0]["text"])
        self.assertNotIn("Issue One-liner:", chunks[0]["text"])
        self.assertEqual(chunks[0]["metadata"]["is_issue"], "yes")
        self.assertEqual(chunks[0]["metadata"]["issue_type"], "real/final VO noise")

    def test_manual_row_tag_issue_fields_override_parsed_fields(self):
        merged = issue_fields.merge_issue_fields(
            {"is_issue": "yes", "status": "open", "issue_type": "VO noise"},
            RowTag(status="resolved", issue_type="real/final VO noise"),
        )

        self.assertEqual(merged["is_issue"], "yes")
        self.assertEqual(merged["status"], "resolved")
        self.assertEqual(merged["issue_type"], "real/final VO noise")


if __name__ == "__main__":
    unittest.main()
