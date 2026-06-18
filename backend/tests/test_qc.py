import unittest
from unittest.mock import patch

from backend.models.quip import ParsedDoc
from backend.models.rules import FilterRules
from backend.services import qc


class QCTest(unittest.IsolatedAsyncioTestCase):
    def _doc(self, table_rows=None):
        return ParsedDoc(
            doc_id="doc-1",
            title="VSD0001_Test",
            prefix="VSD",
            code="VSD0001",
            plain_text="",
            sections=[],
            word_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            table_rows=table_rows or [],
        )

    def test_chunk_qc_flags_missing_row_metadata(self):
        doc = self._doc(table_rows=[{
            "sheet": "ZHCN",
            "row_index": 3,
            "cells": {"Description/ Comment": "Copy issue"},
        }])
        report = qc.qc_chunks(doc, [{
            "id": "doc-1::0",
            "text": "Description/ Comment: Copy issue",
            "metadata": {"doc_id": "doc-1", "row_key": "ZHCN::3"},
        }])

        self.assertEqual(report.status, "fail")
        self.assertIn("missing_row_metadata", [issue.type for issue in report.issues])

    def test_preview_qc_flags_empty_preview(self):
        report = qc.qc_preview_doc({
            "doc_id": "doc-1",
            "title": "VSD0001_Test",
            "stats": {"sheet_breakdown": []},
            "sections_count": 0,
            "table_rows_count": 0,
            "total_chars": 0,
        }, FilterRules())

        self.assertEqual(report.status, "fail")
        self.assertIn("empty_preview", [issue.type for issue in report.issues])

    async def test_query_qc_no_answer_without_citations_skips_llm(self):
        with patch.object(qc.llm_client, "generate_with_metrics") as generate:
            report = await qc.qc_query_answer(
                "What happened?",
                "I couldn't find relevant information in the loaded documents.",
                [],
            )

        self.assertEqual(report.status, "pass")
        generate.assert_not_called()

    async def test_query_qc_high_risk_question_triggers_llm(self):
        class Result:
            text = '{"status":"pass","summary":"ok","issues":[],"repair_instruction":""}'
            prompt_tokens = 1
            candidates_tokens = 1
            total_tokens = 2

        citation = type("Citation", (), {
            "chunk_id": "c1",
            "code": "MS0001",
            "title": "Doc",
            "snippet": "There are 3 voice over issues in FRCA.",
        })()

        with patch.object(qc.llm_client, "generate_with_metrics", return_value=Result()) as generate:
            report = await qc.qc_query_answer(
                "What are the top 3 voice over issues?",
                "Top 3 issues are pacing, noise, and sync.",
                [citation],
                route="stats",
            )

        self.assertEqual(report.status, "pass")
        self.assertTrue(report.metrics["llm_qc_triggered"])
        generate.assert_called_once()

    async def test_query_qc_low_risk_question_skips_llm(self):
        citation = type("Citation", (), {
            "chunk_id": "c1",
            "code": "MS0001",
            "title": "Doc",
            "snippet": "Button label is truncated.",
        })()

        with patch.object(qc.llm_client, "generate_with_metrics") as generate:
            report = await qc.qc_query_answer(
                "What issue is shown here?",
                "The issue is a truncated button label.",
                [citation],
                route="rag",
            )

        self.assertFalse(report.metrics["llm_qc_triggered"])
        generate.assert_not_called()


if __name__ == "__main__":
    unittest.main()
