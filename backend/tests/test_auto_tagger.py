import json
import unittest
from unittest.mock import patch

from backend.models.quip import ParsedDoc
from backend.models.rules import FilterRules
from backend.services import auto_tagger


class AutoTaggerTest(unittest.IsolatedAsyncioTestCase):
    def test_batch_input_drops_empty_and_duplicate_noncritical_cells(self):
        batch = [{
            "sheet": "FRFR",
            "row_index": 4,
            "cells": {
                "Workflow Step": "Translation Validation",
                "Item Type": "Translation Validation",
                "Comment": "  Wrong   terminology  ",
                "Mirror": "Wrong terminology",
                "Empty": "  ",
                "Spacer": "\u200b",
            },
        }]

        compact = auto_tagger._batch_input(batch)["FRFR::4"]

        self.assertEqual(compact["Workflow Step"], "Translation Validation")
        self.assertEqual(compact["Item Type"], "Translation Validation")
        self.assertEqual(compact["Comment"], "Wrong terminology")
        self.assertNotIn("Mirror", compact)
        self.assertNotIn("Empty", compact)
        self.assertNotIn("Spacer", compact)

    def test_feedback_lines_are_deduplicated_without_reordering(self):
        self.assertEqual(
            auto_tagger._dedupe_lines("Rule A\nRule A\n\nRule B\nRule A"),
            "Rule A\nRule B",
        )

    async def test_department_tagged_rows_are_not_auto_excluded(self):
        parsed = ParsedDoc(
            doc_id="doc-1",
            title="MS0001_Test",
            prefix="MS",
            code="MS0001",
            plain_text="",
            sections=[],
            word_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            table_rows=[
                {
                    "sheet": "DEDE",
                    "row_index": 2,
                    "cells": {"Description/ Comment": "Implemented copy issue"},
                }
            ],
        )

        async def fake_generate(prompt):
            return json.dumps({
                "DEDE::2": {
                    "department": "Copy",
                    "excluded": True,
                }
            })

        saved = {}

        with (
            patch.object(auto_tagger.quip_parser, "parse_dict", return_value=parsed),
            patch.object(auto_tagger.tags_store, "load", return_value=auto_tagger.DocTags(doc_id="doc-1")),
            patch.object(auto_tagger.tags_store, "save", side_effect=lambda tags: saved.setdefault("tags", tags)),
            patch.object(auto_tagger.llm_client, "generate", side_effect=fake_generate),
        ):
            result = await auto_tagger.auto_tag_doc({}, FilterRules())

        self.assertEqual(result.rows["DEDE::2"].tags, ["Copy"])
        self.assertFalse(result.rows["DEDE::2"].excluded)
        self.assertFalse(saved["tags"].rows["DEDE::2"].excluded)

    async def test_legacy_excluded_rows_are_not_kept_hidden_unless_they_are_noise(self):
        parsed = ParsedDoc(
            doc_id="doc-legacy",
            title="MS0000_Test",
            prefix="MS",
            code="MS0000",
            plain_text="",
            sections=[],
            word_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            table_rows=[
                {
                    "sheet": "ESLA",
                    "row_index": 4,
                    "cells": {"Comment": "Temperature should be 18 degree Celsius in ESLA."},
                }
            ],
        )

        existing = auto_tagger.DocTags(
            doc_id="doc-legacy",
            rows={
                "ESLA::4": auto_tagger.RowTag(
                    excluded=True,
                    is_noise=False,
                )
            },
        )
        saved = {}

        async def fake_generate(prompt):
            return json.dumps({
                "ESLA::4": {
                    "category_tag": "Translation",
                    "detail_tags": ["terminology"],
                    "confidence": 0.91,
                    "excluded": False,
                    "review_required": False,
                    "review_reason": "",
                    "rationale": "Clear text issue.",
                }
            })

        with (
            patch.object(auto_tagger.quip_parser, "parse_dict", return_value=parsed),
            patch.object(auto_tagger.tags_store, "load", return_value=existing),
            patch.object(auto_tagger.tags_store, "save", side_effect=lambda tags: saved.setdefault("tags", tags)),
            patch.object(auto_tagger.llm_client, "generate", side_effect=fake_generate),
        ):
            result = await auto_tagger.auto_tag_doc({}, FilterRules())

        self.assertFalse(result.rows["ESLA::4"].excluded)
        self.assertFalse(result.rows["ESLA::4"].is_noise)
        self.assertFalse(saved["tags"].rows["ESLA::4"].excluded)

    async def test_injects_relevant_feedback_into_prompt(self):
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
                    "sheet": "FRFR",
                    "row_index": 5,
                    "cells": {"Description/ Comment": "voice over timing mismatch with animation"},
                }
            ],
        )

        seen = {}

        async def fake_generate(prompt):
            seen["prompt"] = prompt
            return json.dumps({
                "FRFR::5": {
                    "department": "Motion",
                    "excluded": False,
                    "category": "Animation",
                    "subcategory": "Timing / Sync",
                    "taxonomy_tags": ["timing-sync"],
                    "confidence": 0.88,
                    "rationale": "Matched prior correction",
                }
            })

        with (
            patch.object(auto_tagger.quip_parser, "parse_dict", return_value=parsed),
            patch.object(auto_tagger.tags_store, "load", return_value=auto_tagger.DocTags(doc_id="doc-2")),
            patch.object(auto_tagger.tags_store, "save"),
            patch.object(
                auto_tagger.feedback_retriever,
                "get_relevant_feedback",
                return_value="Reviewer Action: EDIT\nHuman Final Label: Animation > Timing / Sync",
            ),
            patch.object(auto_tagger.llm_client, "generate", side_effect=fake_generate),
        ):
            await auto_tagger.auto_tag_doc({}, FilterRules())

        self.assertIn("Relevant human-reviewed examples:", seen["prompt"])
        self.assertIn("Human Final Label: Animation > Timing / Sync", seen["prompt"])
        self.assertIn("Relevant distilled review rules:", seen["prompt"])
        self.assertIn("Return ONLY raw JSON", seen["prompt"])
        self.assertNotIn("Return your <reasoning>", seen["prompt"])
        self.assertIn('{"FRFR::5":{"Description/ Comment":"voice over timing mismatch with animation"}}', seen["prompt"])

    async def test_injects_relevant_distilled_rules_into_prompt(self):
        parsed = ParsedDoc(
            doc_id="doc-3",
            title="MS0003_Test",
            prefix="MS",
            code="MS0003",
            plain_text="",
            sections=[],
            word_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            table_rows=[
                {
                    "sheet": "ENGB",
                    "row_index": 12,
                    "cells": {"Description/ Comment": "layout alignment issue with animation frame"},
                }
            ],
        )

        seen = {}

        async def fake_generate(prompt):
            seen["prompt"] = prompt
            return json.dumps({
                "ENGB::12": {
                    "category_tag": "Animation",
                    "detail_tags": ["layout-alignment"],
                    "confidence": 0.91,
                    "excluded": False,
                    "review_required": False,
                    "review_reason": "",
                    "rationale": "Matched distilled layout guidance",
                }
            })

        with (
            patch.object(auto_tagger.quip_parser, "parse_dict", return_value=parsed),
            patch.object(auto_tagger.tags_store, "load", return_value=auto_tagger.DocTags(doc_id="doc-3")),
            patch.object(auto_tagger.tags_store, "save"),
            patch.object(auto_tagger.feedback_retriever, "get_relevant_feedback", return_value="None"),
            patch.object(
                auto_tagger.feedback_retriever,
                "get_relevant_distilled_rules",
                return_value="Rule: When rows were previously tagged as Translation, reviewers often corrected them to Animation.",
            ),
            patch.object(auto_tagger.llm_client, "generate", side_effect=fake_generate),
        ):
            await auto_tagger.auto_tag_doc({}, FilterRules())

        self.assertIn("Relevant distilled review rules:", seen["prompt"])
        self.assertIn("reviewers often corrected them to Animation", seen["prompt"])

    async def test_low_signal_no_comment_rows_are_marked_context_only_review(self):
        parsed = ParsedDoc(
            doc_id="doc-4",
            title="MS0004_Test",
            prefix="MS",
            code="MS0004",
            plain_text="",
            sections=[],
            word_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            table_rows=[
                {
                    "sheet": "ESLA",
                    "row_index": 3,
                    "cells": {"Comment": "Reviewed and no comment."},
                }
            ],
        )

        async def fake_generate(prompt):
            return json.dumps({
                "ESLA::3": {
                    "category_tag": "Translation",
                    "detail_tags": ["no issues"],
                    "confidence": 0.95,
                    "excluded": False,
                    "review_required": False,
                    "review_reason": "",
                    "rationale": "Looks like a translation confirmation.",
                }
            })

        with (
            patch.object(auto_tagger.quip_parser, "parse_dict", return_value=parsed),
            patch.object(auto_tagger.tags_store, "load", return_value=auto_tagger.DocTags(doc_id="doc-4")),
            patch.object(auto_tagger.tags_store, "save"),
            patch.object(auto_tagger.llm_client, "generate", side_effect=fake_generate),
        ):
            result = await auto_tagger.auto_tag_doc({}, FilterRules())

        self.assertEqual(result.rows["ESLA::3"].category_tag, "")
        self.assertEqual(result.rows["ESLA::3"].detail_tags, [])
        self.assertEqual(result.rows["ESLA::3"].is_issue, "no")
        self.assertTrue(result.rows["ESLA::3"].excluded)
        self.assertFalse(result.rows["ESLA::3"].review_required)

    async def test_workflow_status_rows_are_marked_as_exclude_or_context_review(self):
        parsed = ParsedDoc(
            doc_id="doc-5",
            title="MS0005_Test",
            prefix="MS",
            code="MS0005",
            plain_text="",
            sections=[],
            word_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            table_rows=[
                {
                    "sheet": "ESLA",
                    "row_index": 7,
                    "cells": {"Comment": "Reviewed and commented file uploaded on Box path"},
                }
            ],
        )

        async def fake_generate(prompt):
            return json.dumps({
                "ESLA::7": {
                    "category_tag": "Translation",
                    "detail_tags": ["no issues"],
                    "confidence": 0.94,
                    "excluded": False,
                    "review_required": False,
                    "review_reason": "",
                    "rationale": "Looks like a harmless update.",
                }
            })

        with (
            patch.object(auto_tagger.quip_parser, "parse_dict", return_value=parsed),
            patch.object(auto_tagger.tags_store, "load", return_value=auto_tagger.DocTags(doc_id="doc-5")),
            patch.object(auto_tagger.tags_store, "save"),
            patch.object(auto_tagger.llm_client, "generate", side_effect=fake_generate),
        ):
            result = await auto_tagger.auto_tag_doc({}, FilterRules())

        self.assertEqual(result.rows["ESLA::7"].category_tag, "")
        self.assertEqual(result.rows["ESLA::7"].detail_tags, [])
        self.assertEqual(result.rows["ESLA::7"].is_issue, "no")
        self.assertTrue(result.rows["ESLA::7"].excluded)
        self.assertFalse(result.rows["ESLA::7"].review_required)

    async def test_reviewed_comments_added_with_actor_is_treated_as_workflow_status(self):
        parsed = ParsedDoc(
            doc_id="doc-6",
            title="MS0006_Test",
            prefix="MS",
            code="MS0006",
            plain_text="",
            sections=[],
            word_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            table_rows=[
                {
                    "sheet": "JAJP",
                    "row_index": 3,
                    "cells": {
                        "Comment": "Reviewed and comments added.",
                        "Response by": "LB",
                        "Item Type": "Translation",
                        "Status": "",
                    },
                }
            ],
        )

        async def fake_generate(prompt):
            return json.dumps({
                "JAJP::3": {
                    "category_tag": "Translation",
                    "detail_tags": ["status update"],
                    "confidence": 0.92,
                    "excluded": False,
                    "review_required": False,
                    "review_reason": "",
                    "rationale": "Generic review note.",
                }
            })

        with (
            patch.object(auto_tagger.quip_parser, "parse_dict", return_value=parsed),
            patch.object(auto_tagger.tags_store, "load", return_value=auto_tagger.DocTags(doc_id="doc-6")),
            patch.object(auto_tagger.tags_store, "save"),
            patch.object(auto_tagger.llm_client, "generate", side_effect=fake_generate),
        ):
            result = await auto_tagger.auto_tag_doc({}, FilterRules())

        self.assertEqual(result.rows["JAJP::3"].category_tag, "")
        self.assertEqual(result.rows["JAJP::3"].detail_tags, [])
        self.assertEqual(result.rows["JAJP::3"].is_issue, "no")
        self.assertTrue(result.rows["JAJP::3"].excluded)
        self.assertFalse(result.rows["JAJP::3"].review_required)

    async def test_motion_reviewer_prior_only_applies_when_issue_text_matches_animation(self):
        parsed = ParsedDoc(
            doc_id="doc-7",
            title="MS0007_Test",
            prefix="MS",
            code="MS0007",
            plain_text="",
            sections=[],
            word_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            table_rows=[
                {
                    "sheet": "JAJP",
                    "row_index": 9,
                    "cells": {
                        "Comment": "The swipe gesture looks too rapid and needs more bounce.",
                        "Response by": " - Video SPC (Gideon)",
                    },
                }
            ],
        )

        async def fake_generate(prompt):
            return json.dumps({
                "JAJP::9": {
                    "category_tag": "",
                    "detail_tags": [],
                    "confidence": 0.41,
                    "excluded": False,
                    "review_required": True,
                    "review_reason": "Unsure whether this is visual or wording related.",
                    "rationale": "Ambiguous issue.",
                }
            })

        with (
            patch.object(auto_tagger.quip_parser, "parse_dict", return_value=parsed),
            patch.object(auto_tagger.tags_store, "load", return_value=auto_tagger.DocTags(doc_id="doc-7")),
            patch.object(auto_tagger.tags_store, "save"),
            patch.object(auto_tagger.llm_client, "generate", side_effect=fake_generate),
        ):
            result = await auto_tagger.auto_tag_doc({}, FilterRules())

        self.assertEqual(result.rows["JAJP::9"].category_tag, "Animation")
        self.assertTrue(result.rows["JAJP::9"].review_required)
        self.assertIn("Reviewer role suggests Animation", result.rows["JAJP::9"].review_reason)
        self.assertLessEqual(result.rows["JAJP::9"].confidence, 0.72)

    async def test_translation_vendor_prior_does_not_override_clear_voice_over_issue(self):
        parsed = ParsedDoc(
            doc_id="doc-8",
            title="MS0008_Test",
            prefix="MS",
            code="MS0008",
            plain_text="",
            sections=[],
            word_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            table_rows=[
                {
                    "sheet": "ENGB",
                    "row_index": 4,
                    "cells": {
                        "Comment": "VO script mismatch in line 4, pronunciation needs retake.",
                        "Response by": "LB",
                    },
                }
            ],
        )

        async def fake_generate(prompt):
            return json.dumps({
                "ENGB::4": {
                    "category_tag": "Voice Over",
                    "detail_tags": ["script mismatch", "pronunciation"],
                    "confidence": 0.91,
                    "excluded": False,
                    "review_required": False,
                    "review_reason": "",
                    "rationale": "Clear VO issue.",
                }
            })

        with (
            patch.object(auto_tagger.quip_parser, "parse_dict", return_value=parsed),
            patch.object(auto_tagger.tags_store, "load", return_value=auto_tagger.DocTags(doc_id="doc-8")),
            patch.object(auto_tagger.tags_store, "save"),
            patch.object(auto_tagger.llm_client, "generate", side_effect=fake_generate),
        ):
            result = await auto_tagger.auto_tag_doc({}, FilterRules())

        self.assertEqual(result.rows["ENGB::4"].category_tag, "Voice Over")
        self.assertFalse(result.rows["ENGB::4"].review_required)

    async def test_voice_over_script_difference_with_modified_upload_gets_retake_needed(self):
        parsed = ParsedDoc(
            doc_id="doc-9",
            title="MS0009_Test",
            prefix="MS",
            code="MS0009",
            plain_text="",
            sections=[],
            word_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            table_rows=[
                {
                    "sheet": "JAJP",
                    "row_index": 8,
                    "cells": {
                        "Comment": "The script and VO are different. script: これは... VO: これで...",
                        "Response by": "LB",
                        "Response": "From Akinori: Modified #26 VO and uploaded to box as 'v2'.",
                    },
                }
            ],
        )

        async def fake_generate(prompt):
            return json.dumps({
                "JAJP::8": {
                    "category_tag": "Voice Over",
                    "detail_tags": ["script mismatch"],
                    "confidence": 0.89,
                    "excluded": False,
                    "review_required": False,
                    "review_reason": "",
                    "rationale": "VO text does not match the script.",
                }
            })

        with (
            patch.object(auto_tagger.quip_parser, "parse_dict", return_value=parsed),
            patch.object(auto_tagger.tags_store, "load", return_value=auto_tagger.DocTags(doc_id="doc-9")),
            patch.object(auto_tagger.tags_store, "save"),
            patch.object(auto_tagger.llm_client, "generate", side_effect=fake_generate),
        ):
            result = await auto_tagger.auto_tag_doc({}, FilterRules())

        self.assertEqual(result.rows["JAJP::8"].category_tag, "Voice Over")
        self.assertIn("script mismatch", result.rows["JAJP::8"].detail_tags)
        self.assertIn("retake", result.rows["JAJP::8"].detail_tags)
        self.assertEqual(result.rows["JAJP::8"].issue_source, "LB")

    async def test_source_rows_are_allowed_as_first_class_category(self):
        parsed = ParsedDoc(
            doc_id="doc-10",
            title="MS0010_Test",
            prefix="MS",
            code="MS0010",
            plain_text="",
            sections=[],
            word_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            table_rows=[
                {
                    "sheet": "ENGB",
                    "row_index": 11,
                    "cells": {
                        "Comment": "The source screenshot is outdated and does not match the true UI.",
                    },
                }
            ],
        )

        async def fake_generate(prompt):
            return json.dumps({
                "ENGB::11": {
                    "is_issue": "yes",
                    "category_tag": "Source",
                    "detail_tags": ["ui capture", "outdated"],
                    "confidence": 0.93,
                    "excluded": False,
                    "review_required": False,
                    "review_reason": "",
                    "rationale": "The source reference itself is outdated.",
                }
            })

        with (
            patch.object(auto_tagger.quip_parser, "parse_dict", return_value=parsed),
            patch.object(auto_tagger.tags_store, "load", return_value=auto_tagger.DocTags(doc_id="doc-10")),
            patch.object(auto_tagger.tags_store, "save"),
            patch.object(auto_tagger.llm_client, "generate", side_effect=fake_generate),
        ):
            result = await auto_tagger.auto_tag_doc({}, FilterRules())

        self.assertEqual(result.rows["ENGB::11"].category_tag, "Source")
        self.assertEqual(result.rows["ENGB::11"].taxonomy_category, "Source")
        self.assertFalse(result.rows["ENGB::11"].excluded)
        self.assertEqual(result.rows["ENGB::11"].detail_tags, ["source mismatch"])

    def test_detail_tags_are_collapsed_into_summary_tags(self):
        self.assertEqual(
            auto_tagger._summarize_detail_tags("Translation", ["grammar", "spelling", "typo"]),
            ["validation"],
        )
        self.assertEqual(
            auto_tagger._summarize_detail_tags("Animation", ["render clipping", "UI capture", "transition timing"]),
            ["post editing", "ui capture", "motion timing"],
        )
        self.assertEqual(
            auto_tagger._summarize_detail_tags("", ["unmapped detail"]),
            [],
        )

    def test_vendor_identity_is_an_issue_source_not_a_forced_category(self):
        row = {
            "cells": {
                "Comment": "The VO recording has background noise.",
                "Response by": "RWS",
            }
        }

        self.assertEqual(auto_tagger._actor_vendor(row), "RWS")
        self.assertEqual(auto_tagger._actor_prior_category(row), "Translation")
        self.assertIn("Voice Over", auto_tagger._issue_signal_categories(row))

    def test_locale_difference_reminder_is_kept_as_source_context(self):
        doc_tags = auto_tagger.DocTags(doc_id="doc-context")
        row = {
            "cells": {
                "Comment": "FYI: this is an expected locale difference between FRFR and FRCA.",
                "Response by": "RWS",
            }
        }
        auto_tagger._apply_predictions(
            doc_tags,
            {
                "FRFR::3": {
                    "is_issue": "no",
                    "category_tag": "",
                    "detail_tags": [],
                    "confidence": 0.94,
                    "excluded": True,
                    "rationale": "Informational locale guidance.",
                }
            },
            {"FRFR::3": row},
        )

        saved = doc_tags.rows["FRFR::3"]
        self.assertEqual(saved.category_tag, "Source")
        self.assertEqual(saved.detail_tags, ["locale difference", "guidance"])
        self.assertEqual(saved.issue_source, "RWS")
        self.assertEqual(saved.is_issue, "no")
        self.assertFalse(saved.excluded)

    async def test_timeout_batches_split_and_preserve_successful_rows(self):
        rows = [
            {"sheet": "ENGB", "row_index": index, "cells": {"Comment": f"Issue {index}"}}
            for index in range(1, 5)
        ]
        parsed = ParsedDoc(
            doc_id="doc-split",
            title="MS0012_Test",
            prefix="MS",
            code="MS0012",
            plain_text="",
            sections=[],
            word_count=0,
            created_at="2026-01-01T00:00:00+00:00",
            updated_at="2026-01-01T00:00:00+00:00",
            table_rows=rows,
        )
        existing = auto_tagger.DocTags(
            doc_id="doc-split",
            rows={"ENGB::4": auto_tagger.RowTag(category_tag="Source", tags=["Source"])},
        )
        leaf_attempts: dict[str, int] = {}

        async def fake_predict(batch):
            if len(batch) > 1:
                raise auto_tagger.llm_client.LLMRequestTimeoutError("too large")
            key = auto_tagger._row_key(batch[0])
            leaf_attempts[key] = leaf_attempts.get(key, 0) + 1
            if key == "ENGB::4":
                raise auto_tagger.llm_client.LLMRequestTimeoutError("still timed out")
            return {
                key: {
                    "category_tag": "Translation",
                    "detail_tags": ["terminology"],
                    "confidence": 0.9,
                    "is_issue": "yes",
                }
            }

        with (
            patch.object(auto_tagger.quip_parser, "parse_dict", return_value=parsed),
            patch.object(auto_tagger.tags_store, "load", return_value=existing),
            patch.object(auto_tagger.tags_store, "save") as save_tags,
            patch.object(auto_tagger, "_predict_batch", side_effect=fake_predict),
        ):
            result = await auto_tagger.auto_tag_doc({}, FilterRules())

        for index in range(1, 4):
            self.assertEqual(result.rows[f"ENGB::{index}"].category_tag, "Translation")
        self.assertEqual(result.rows["ENGB::4"].category_tag, "Source")
        self.assertEqual(leaf_attempts["ENGB::4"], auto_tagger.AUTO_TAG_LEAF_ATTEMPTS)
        save_tags.assert_called_once()


if __name__ == "__main__":
    unittest.main()
