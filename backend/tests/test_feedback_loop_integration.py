import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.api import tags as tags_api
from backend.models.quip import ParsedDoc
from backend.models.rules import FilterRules
from backend.models.tags import DocTags, RowTag
from backend.services import auto_tagger
from backend.config import settings


class FeedbackLoopIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_review_feedback_flows_into_distill_and_autotagger_prompt(self):
        previous = DocTags(
            doc_id="doc-1",
            rows={
                "FRFR::5": RowTag(
                    tags=["Translation"],
                    category_tag="Translation",
                    detail_tags=["terminology"],
                    taxonomy_category="Translation",
                    taxonomy_subcategory="UI Text Accuracy",
                    taxonomy_tags=["terminology"],
                    review_required=True,
                    review_reason="Low confidence or ambiguous category.",
                )
            },
        )
        saved_doc = previous.model_copy(deep=True)
        structured_feedback = {}

        parsed = ParsedDoc(
            doc_id="doc-2",
            title="MS0002_Test",
            prefix="MS",
            code="MS0002",
            plain_text="",
            sections=[],
            word_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            table_rows=[
                {
                    "sheet": "ENGB",
                    "row_index": 12,
                    "cells": {"Description/ Comment": "animation layout alignment mismatch on screen"},
                }
            ],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            feedback_path = tmp_path / "tag_feedback.jsonl"
            distilled_path = tmp_path / "tag_feedback_distilled.json"
            original_feedback_path = tags_api._FEEDBACK_PATH
            original_distilled_path = tags_api._DISTILLED_PATH
            original_settings_feedback_path = settings.tag_feedback_path

            def fake_set_row(doc_id: str, key: str, tag: RowTag):
                saved_doc.rows[key] = tag
                return saved_doc

            async def fake_generate(prompt: str):
                structured_feedback["prompt"] = prompt
                return json.dumps({
                    "ENGB::12": {
                        "category_tag": "Animation",
                        "detail_tags": ["layout-alignment"],
                        "confidence": 0.93,
                        "excluded": False,
                        "review_required": False,
                        "review_reason": "",
                        "rationale": "Matched human corrections and distilled guidance.",
                    }
                })

            try:
                tags_api._FEEDBACK_PATH = feedback_path
                tags_api._DISTILLED_PATH = distilled_path
                settings.tag_feedback_path = feedback_path

                with (
                    patch.object(tags_api.tags_store, "load", return_value=previous),
                    patch.object(tags_api.tags_store, "set_row", side_effect=fake_set_row),
                    patch.object(tags_api.taxonomy_store, "ensure_from_row_tag"),
                    patch.object(tags_api.taxonomy_store, "get_prediction", return_value={
                        "predicted_category": "Translation",
                        "predicted_subcategory": "UI Text Accuracy",
                        "predicted_tags": ["terminology"],
                    }),
                    patch.object(tags_api.taxonomy_store, "save_feedback", side_effect=lambda req: structured_feedback.setdefault("req", req)),
                    patch.object(tags_api.vector_store, "sync_row_tag", return_value=1),
                ):
                    await tags_api.set_row_tag(
                        "doc-1",
                        "FRFR::5",
                        RowTag(
                            tags=["Animation"],
                            category_tag="Animation",
                            detail_tags=["layout-alignment"],
                            confidence=0.92,
                            rationale="Human reviewer confirmed this is an animation alignment issue.",
                            review_required=False,
                            review_reason="Resolved by human review.",
                            feedback_note="Rows mentioning layout alignment should lean Animation, not Translation.",
                            taxonomy_category="Animation",
                            taxonomy_subcategory="Layout / Position Alignment",
                            taxonomy_tags=["layout-alignment"],
                        ),
                    )

                self.assertTrue(feedback_path.exists())
                self.assertEqual(structured_feedback["req"].action, "edit")
                self.assertEqual(structured_feedback["req"].final_category, "Animation")

                distilled = await tags_api.distill_feedback()
                self.assertTrue(distilled_path.exists())
                self.assertEqual(distilled.total_feedback, 1)
                self.assertTrue(any("Animation" in rule for rule in distilled.rules))
                self.assertTrue(any("layout-alignment" in rule for rule in distilled.rules))
                self.assertTrue(any("layout" in rule for rule in distilled.rules))

                with (
                    patch.object(auto_tagger.quip_parser, "parse_dict", return_value=parsed),
                    patch.object(auto_tagger.tags_store, "load", return_value=DocTags(doc_id="doc-2")),
                    patch.object(auto_tagger.tags_store, "save"),
                    patch.object(
                        auto_tagger.feedback_retriever,
                        "get_relevant_feedback",
                        return_value=(
                            "Reviewer Action: EDIT\n"
                            "AI Originally Predicted: Translation > UI Text Accuracy\n"
                            "Human Final Label: Animation > Layout / Position Alignment"
                        ),
                    ),
                    patch.object(auto_tagger.llm_client, "generate", side_effect=fake_generate),
                ):
                    await auto_tagger.auto_tag_doc({}, FilterRules())

                self.assertIn("Relevant human-reviewed examples:", structured_feedback["prompt"])
                self.assertIn("Human Final Label: Animation > Layout / Position Alignment", structured_feedback["prompt"])
                self.assertIn("Relevant distilled review rules:", structured_feedback["prompt"])
                self.assertIn("reviewers often corrected them to Animation", structured_feedback["prompt"])
            finally:
                tags_api._FEEDBACK_PATH = original_feedback_path
                tags_api._DISTILLED_PATH = original_distilled_path
                settings.tag_feedback_path = original_settings_feedback_path


if __name__ == "__main__":
    unittest.main()
