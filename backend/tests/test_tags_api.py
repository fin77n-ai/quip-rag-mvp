import unittest

from backend.models.tags import DocTags, RowTag
from backend.api import tags as tags_api


class TagsApiTest(unittest.IsolatedAsyncioTestCase):
    async def test_list_known_tags_returns_fixed_broad_categories(self):
        original_iter_all = tags_api.tags_store.iter_all
        original_all_known_detail_tags = tags_api.tags_store.all_known_detail_tags
        try:
            tags_api.tags_store.iter_all = lambda: [
                DocTags(
                    doc_id="doc-1",
                    rows={
                        "ENGB::12": RowTag(
                            category_tag="Translation",
                            detail_tags=["random-copy-note", "terminology"],
                            excluded=False,
                            is_noise=False,
                            is_issue="yes",
                        ),
                        "ENGB::13": RowTag(
                            category_tag="Translation",
                            detail_tags=["history-only-tag"],
                            excluded=True,
                            is_noise=False,
                            is_issue="no",
                        ),
                    },
                )
            ]
            tags_api.tags_store.all_known_detail_tags = lambda: [
                "history-only-tag",
                "random-copy-note",
                "terminology",
            ]

            result = await tags_api.list_known_tags()
        finally:
            tags_api.tags_store.iter_all = original_iter_all
            tags_api.tags_store.all_known_detail_tags = original_all_known_detail_tags

        self.assertEqual(result["tags"], ["Animation", "Translation", "Voice Over", "Source"])
        self.assertEqual(result["detail_tags"], list(dict.fromkeys(
            tag for tags in tags_api._TAG_TAXONOMY.values() for tag in tags
        )))
        self.assertEqual(result["active_detail_tags_count"], 2)
        self.assertEqual(result["loose_detail_tags_count"], 1)

    async def test_tag_taxonomy_returns_loose_detail_tag_candidates(self):
        original_iter_all = tags_api.tags_store.iter_all
        try:
            tags_api.tags_store.iter_all = lambda: [
                DocTags(
                    doc_id="doc-1",
                    rows={
                        "ENGB::12": RowTag(
                            category_tag="Translation",
                            detail_tags=["random-copy-note", "terminology"],
                        ),
                        "ENGB::13": RowTag(
                            category_tag="Translation",
                            detail_tags=["random-copy-note"],
                        ),
                        "ENGB::14": RowTag(
                            category_tag="Translation",
                            detail_tags=["ignored-old-tag"],
                            excluded=True,
                            is_issue="no",
                        ),
                    },
                )
            ]

            result = await tags_api.tag_taxonomy()
        finally:
            tags_api.tags_store.iter_all = original_iter_all

        candidates = {candidate.tag: candidate for candidate in result.candidates}
        self.assertIn("random-copy-note", candidates)
        self.assertEqual(candidates["random-copy-note"].count, 2)
        self.assertNotIn("terminology", candidates)

    async def test_merge_detail_tag_updates_rows_and_syncs_chunks(self):
        existing = DocTags(
            doc_id="doc-1",
            rows={
                "ENGB::12": RowTag(
                    category_tag="Translation",
                    detail_tags=["random-copy-note", "terminology"],
                    taxonomy_tags=["random-copy-note"],
                ),
                "ENGB::13": RowTag(category_tag="Animation", detail_tags=["layout-alignment"]),
            },
        )
        saved: list[DocTags] = []
        synced: list[tuple[str, str, RowTag]] = []

        original_iter_all = tags_api.tags_store.iter_all
        original_save = tags_api.tags_store.save
        original_sync = tags_api.vector_store.sync_row_tag
        try:
            tags_api.tags_store.iter_all = lambda: [existing]
            tags_api.tags_store.save = lambda doc_tags: saved.append(doc_tags) or None
            tags_api.vector_store.sync_row_tag = lambda doc_id, key, tag: synced.append((doc_id, key, tag)) or 1

            result = await tags_api.merge_detail_tag(
                tags_api.DetailTagMergeRequest(
                    from_tag="random-copy-note",
                    to_tag="localized-copy",
                    category="Translation",
                )
            )
        finally:
            tags_api.tags_store.iter_all = original_iter_all
            tags_api.tags_store.save = original_save
            tags_api.vector_store.sync_row_tag = original_sync

        self.assertEqual(result.updated_rows, 1)
        self.assertEqual(result.synced_chunks, 1)
        self.assertEqual(saved[0].rows["ENGB::12"].detail_tags, ["localized-copy", "terminology"])
        self.assertEqual(saved[0].rows["ENGB::12"].taxonomy_tags, ["localized-copy"])
        self.assertEqual(saved[0].rows["ENGB::12"].category_tag, "Translation")
        self.assertEqual(synced[0][1], "ENGB::12")

    async def test_archive_row_as_noise_marks_row_without_removing_chunk(self):
        existing = DocTags(
            doc_id="doc-1",
            rows={
                "ENGB::12": RowTag(
                    category_tag="Translation",
                    review_required=True,
                    excluded=False,
                )
            },
        )
        saved_tags: list[tuple[str, str, RowTag]] = []

        original_load = tags_api.tags_store.load
        original_set_row = tags_api.tags_store.set_row
        original_sync = tags_api.vector_store.sync_row_tag
        try:
            tags_api.tags_store.load = lambda doc_id: existing
            tags_api.tags_store.set_row = lambda doc_id, key, tag: saved_tags.append((doc_id, key, tag)) or existing
            tags_api.vector_store.sync_row_tag = lambda doc_id, key, tag: 1

            result = await tags_api.archive_row_as_noise("doc-1", "ENGB::12")
        finally:
            tags_api.tags_store.load = original_load
            tags_api.tags_store.set_row = original_set_row
            tags_api.vector_store.sync_row_tag = original_sync

        self.assertEqual(result, {"archived": 1})
        self.assertEqual(len(saved_tags), 1)
        self.assertEqual(saved_tags[0][0], "doc-1")
        self.assertEqual(saved_tags[0][1], "ENGB::12")
        self.assertTrue(saved_tags[0][2].excluded)
        self.assertTrue(saved_tags[0][2].is_noise)
        self.assertFalse(saved_tags[0][2].review_required)

    async def test_delete_row_chunk_removes_chunk_and_row_tag(self):
        deleted = {}

        original_delete_row = tags_api.tags_store.delete_row
        original_delete_chunk = tags_api.vector_store.delete_chunk_by_row
        try:
            tags_api.tags_store.delete_row = lambda doc_id, key: deleted.__setitem__("tag", (doc_id, key)) or DocTags(doc_id=doc_id)
            tags_api.vector_store.delete_chunk_by_row = lambda doc_id, key: deleted.__setitem__("chunk", (doc_id, key)) or 1

            result = await tags_api.delete_row_chunk("doc-1", "ENGB::12")
        finally:
            tags_api.tags_store.delete_row = original_delete_row
            tags_api.vector_store.delete_chunk_by_row = original_delete_chunk

        self.assertEqual(result, {"deleted": 1})
        self.assertEqual(deleted["chunk"], ("doc-1", "ENGB::12"))
        self.assertEqual(deleted["tag"], ("doc-1", "ENGB::12"))

    async def test_restore_row_chunk_clears_noise_and_excluded_when_restored(self):
        existing = DocTags(
            doc_id="doc-1",
            rows={
                "ENGB::12": RowTag(
                    category_tag="Translation",
                    review_required=False,
                    excluded=True,
                    is_noise=True,
                )
            },
        )
        saved_tags: list[tuple[str, str, RowTag]] = []

        original_load = tags_api.tags_store.load
        original_set_row = tags_api.tags_store.set_row
        original_restore = tags_api.vector_store.restore_chunk_by_row
        original_sync = tags_api.vector_store.sync_row_tag
        try:
            tags_api.tags_store.load = lambda doc_id: existing
            tags_api.tags_store.set_row = lambda doc_id, key, tag: saved_tags.append((doc_id, key, tag)) or existing
            tags_api.vector_store.restore_chunk_by_row = lambda doc_id, key: 1
            tags_api.vector_store.sync_row_tag = lambda doc_id, key, tag: 1

            result = await tags_api.restore_row_chunk("doc-1", "ENGB::12")
        finally:
            tags_api.tags_store.load = original_load
            tags_api.tags_store.set_row = original_set_row
            tags_api.vector_store.restore_chunk_by_row = original_restore
            tags_api.vector_store.sync_row_tag = original_sync

        self.assertEqual(result, {"restored": 1})
        self.assertEqual(len(saved_tags), 1)
        self.assertEqual(saved_tags[0][0], "doc-1")
        self.assertEqual(saved_tags[0][1], "ENGB::12")
        self.assertFalse(saved_tags[0][2].excluded)
        self.assertFalse(saved_tags[0][2].is_noise)

    async def test_set_row_tag_records_manual_taxonomy_feedback(self):
        previous = DocTags(
            doc_id="doc-1",
            rows={
                "FRFR::5": RowTag(
                    tags=["Copy"],
                    taxonomy_category="Translation",
                    taxonomy_subcategory="UI Text Accuracy",
                    taxonomy_tags=["terminology"],
                )
            },
        )
        updated = previous.model_copy()
        captured = {}

        def fake_save_feedback(req):
            captured["req"] = req

        original_load = tags_api.tags_store.load
        original_set_row = tags_api.tags_store.set_row
        original_ensure = tags_api.taxonomy_store.ensure_from_row_tag
        original_get_prediction = tags_api.taxonomy_store.get_prediction
        original_save_feedback = tags_api.taxonomy_store.save_feedback
        original_sync = tags_api.vector_store.sync_row_tag
        try:
            tags_api.tags_store.load = lambda doc_id: previous
            tags_api.tags_store.set_row = lambda doc_id, key, tag: updated.model_copy(
                update={"rows": {**updated.rows, key: tag}}
            )
            tags_api.taxonomy_store.ensure_from_row_tag = lambda tag: None
            tags_api.taxonomy_store.get_prediction = lambda row_id: {
                "predicted_category": "Translation",
                "predicted_subcategory": "UI Text Accuracy",
                "predicted_tags": ["terminology"],
            }
            tags_api.taxonomy_store.save_feedback = fake_save_feedback
            tags_api.vector_store.sync_row_tag = lambda doc_id, key, tag: 1

            await tags_api.set_row_tag(
                "doc-1",
                "FRFR::5",
                RowTag(
                    tags=["Copy"],
                    taxonomy_category="Animation",
                    taxonomy_subcategory="Layout / Position Alignment",
                    taxonomy_tags=["layout-alignment"],
                ),
            )
        finally:
            tags_api.tags_store.load = original_load
            tags_api.tags_store.set_row = original_set_row
            tags_api.taxonomy_store.ensure_from_row_tag = original_ensure
            tags_api.taxonomy_store.get_prediction = original_get_prediction
            tags_api.taxonomy_store.save_feedback = original_save_feedback
            tags_api.vector_store.sync_row_tag = original_sync

        self.assertEqual(captured["req"].row_id, "doc-1::FRFR::5")
        self.assertEqual(captured["req"].action, "edit")
        self.assertEqual(captured["req"].predicted_category, "Translation")
        self.assertEqual(captured["req"].final_category, "Animation")

    async def test_set_row_tag_records_structured_feedback_for_review_resolution(self):
        previous = DocTags(
            doc_id="doc-1",
            rows={
                "FRFR::5": RowTag(
                    tags=["Copy"],
                    taxonomy_category="Translation",
                    taxonomy_subcategory="UI Text Accuracy",
                    taxonomy_tags=["terminology"],
                    review_required=True,
                )
            },
        )
        captured = {}

        original_load = tags_api.tags_store.load
        original_set_row = tags_api.tags_store.set_row
        original_ensure = tags_api.taxonomy_store.ensure_from_row_tag
        original_get_prediction = tags_api.taxonomy_store.get_prediction
        original_save_feedback = tags_api.taxonomy_store.save_feedback
        original_sync = tags_api.vector_store.sync_row_tag
        try:
            tags_api.tags_store.load = lambda doc_id: previous
            tags_api.tags_store.set_row = lambda doc_id, key, tag: previous.model_copy(
                update={"rows": {**previous.rows, key: tag}}
            )
            tags_api.taxonomy_store.ensure_from_row_tag = lambda tag: None
            tags_api.taxonomy_store.get_prediction = lambda row_id: None
            tags_api.taxonomy_store.save_feedback = lambda req: captured.__setitem__("req", req)
            tags_api.vector_store.sync_row_tag = lambda doc_id, key, tag: 1

            await tags_api.set_row_tag(
                "doc-1",
                "FRFR::5",
                RowTag(
                    tags=["Copy"],
                    taxonomy_category="Translation",
                    taxonomy_subcategory="UI Text Accuracy",
                    taxonomy_tags=["terminology"],
                    review_required=False,
                    feedback_note="Looks good after human review.",
                ),
            )
        finally:
            tags_api.tags_store.load = original_load
            tags_api.tags_store.set_row = original_set_row
            tags_api.taxonomy_store.ensure_from_row_tag = original_ensure
            tags_api.taxonomy_store.get_prediction = original_get_prediction
            tags_api.taxonomy_store.save_feedback = original_save_feedback
            tags_api.vector_store.sync_row_tag = original_sync

        self.assertEqual(captured["req"].action, "approve")
        self.assertEqual(captured["req"].final_category, "Translation")
        self.assertEqual(captured["req"].rationale, "Looks good after human review.")

    async def test_set_row_tag_syncs_normalized_saved_tag_to_vector_store(self):
        previous = DocTags(doc_id="doc-1")
        normalized = RowTag(
            tags=["Translation"],
            category_tag="Translation",
            detail_tags=["status update"],
            taxonomy_category="Translation",
            taxonomy_tags=["status update"],
        )
        saved_doc = DocTags(doc_id="doc-1", rows={"JAJP::3": normalized})
        captured = {}

        original_load = tags_api.tags_store.load
        original_set_row = tags_api.tags_store.set_row
        original_ensure = tags_api.taxonomy_store.ensure_from_row_tag
        original_get_prediction = tags_api.taxonomy_store.get_prediction
        original_save_feedback = tags_api.taxonomy_store.save_feedback
        original_sync = tags_api.vector_store.sync_row_tag
        try:
            tags_api.tags_store.load = lambda doc_id: previous
            tags_api.tags_store.set_row = lambda doc_id, key, tag: saved_doc
            tags_api.taxonomy_store.ensure_from_row_tag = lambda tag: captured.__setitem__("ensured", tag)
            tags_api.taxonomy_store.get_prediction = lambda row_id: None
            tags_api.taxonomy_store.save_feedback = lambda req: None
            tags_api.vector_store.sync_row_tag = lambda doc_id, key, tag: captured.__setitem__("synced", tag) or 1

            await tags_api.set_row_tag(
                "doc-1",
                "JAJP::3",
                RowTag(
                    tags=["Translation"],
                    category_tag="Translation",
                    detail_tags=["status update"],
                ),
            )
        finally:
            tags_api.tags_store.load = original_load
            tags_api.tags_store.set_row = original_set_row
            tags_api.taxonomy_store.ensure_from_row_tag = original_ensure
            tags_api.taxonomy_store.get_prediction = original_get_prediction
            tags_api.taxonomy_store.save_feedback = original_save_feedback
            tags_api.vector_store.sync_row_tag = original_sync

        self.assertEqual(captured["ensured"].taxonomy_category, "Translation")
        self.assertEqual(captured["ensured"].taxonomy_tags, ["status update"])
        self.assertEqual(captured["synced"].taxonomy_category, "Translation")
        self.assertEqual(captured["synced"].taxonomy_tags, ["status update"])


if __name__ == "__main__":
    unittest.main()
