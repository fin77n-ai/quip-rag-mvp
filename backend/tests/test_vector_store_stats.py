import unittest
from unittest.mock import patch

from backend.services import issue_analysis, vector_store, duck_lance_store


class VectorStoreStatsTest(unittest.TestCase):
    def test_stats_breakdown_counts_metadata_dimensions(self):
        memories = [
            {
                "chunk_id": "a",
                "text": "copy issue",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "Video One",
                    "code": "VSD0001",
                    "category": "VSD",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "Copy",
                    "retake_explicit": "yes",
                },
            },
            {
                "chunk_id": "b",
                "text": "motion issue",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "Video One",
                    "code": "VSD0001",
                    "category": "VSD",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "Motion,Copy",
                    "retake_explicit": "no",
                },
            },
            {
                "chunk_id": "c",
                "text": "source issue",
                "metadata": {
                    "doc_id": "doc-2",
                    "title": "Video Two",
                    "code": "VSD0002",
                    "category": "VSD",
                    "sprint": "MS19",
                    "sheet": "ZHCN",
                    "tags": "Source",
                    "retake_explicit": "yes",
                },
            },
            {
                "chunk_id": "d",
                "text": "untagged issue",
                "metadata": {
                    "doc_id": "doc-2",
                    "title": "Video Two",
                    "code": "VSD0002",
                    "category": "VSD",
                    "sprint": "MS19",
                    "sheet": "ZHCN",
                    "tags": "",
                    "retake_explicit": "no",
                },
            },
        ]

        with patch.object(duck_lance_store, "list_memories", return_value=memories):
            stats = vector_store.stats_breakdown(sprint="MS19")

        self.assertEqual(stats["total_chunks"], 4)
        self.assertEqual(stats["total_docs"], 2)
        self.assertEqual(stats["by_locale"][0], {"key": "FRCA", "count": 2})
        self.assertIn({"key": "Copy", "count": 2}, stats["by_tag"])
        self.assertIn({"key": "(untagged)", "count": 1}, stats["by_tag"])
        self.assertIn({"key": "yes", "count": 2}, stats["by_retake_explicit"])
        self.assertEqual(stats["by_doc"][0]["doc_id"], "doc-1")
        self.assertEqual(stats["by_doc"][0]["count"], 2)

    def test_repeated_issue_groups_by_normalized_description(self):
        memories = [
            {
                "chunk_id": "a",
                "text": 'Description/ Comment: Please change "Start" to "Begin" in the menu. Response: fixed',
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "Video One",
                    "code": "VSD0001",
                    "category": "VSD",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "row_index": 2,
                    "tags": "Copy",
                },
            },
            {
                "chunk_id": "b",
                "text": 'Description/ Comment: Please change "Start" to "Begin" in the menu. Response: fixed',
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "Video One",
                    "code": "VSD0001",
                    "category": "VSD",
                    "sprint": "MS19",
                    "sheet": "PTBR",
                    "row_index": 8,
                    "tags": "Copy,Motion",
                },
            },
            {
                "chunk_id": "c",
                "text": "Description/ Comment: CTA overlaps hero image on mobile. Comment: visual issue",
                "metadata": {
                    "doc_id": "doc-2",
                    "title": "Video Two",
                    "code": "VSD0002",
                    "category": "VSD",
                    "sprint": "MS19",
                    "sheet": "ZHCN",
                    "row_index": 3,
                    "tags": "Motion",
                },
            },
        ]

        with patch.object(duck_lance_store, "list_memories", return_value=memories):
            result = issue_analysis.repeated_issue_groups(sprint="MS19", tag="Copy")

        self.assertEqual(result["total_memories_scanned"], 3)
        self.assertEqual(result["total_groups"], 1)
        group = result["groups"][0]
        self.assertEqual(group["count"], 2)
        self.assertEqual(group["locales"], ["FRCA", "PTBR"])
        self.assertEqual(group["docs"][0]["doc_id"], "doc-1")
        self.assertIn("Copy", group["tags"])
        self.assertEqual([example["chunk_id"] for example in group["examples"]], ["a", "b"])

    def test_analyze_sprint_can_filter_untagged_rows(self):
        memories = [
            {
                "chunk_id": "a",
                "text": "Description/ Comment: Untagged issue",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "Video One",
                    "code": "MS0001",
                    "category": "MS",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "",
                },
            },
        ]

        with patch.object(duck_lance_store, "list_memories", return_value=memories) as list_memories:
            result = issue_analysis.analyze_sprint(sprint="MS19", tag="(untagged)")

        list_memories.assert_called_once()
        self.assertEqual(list_memories.call_args.kwargs["tag"], "(untagged)")
        self.assertEqual(result["summary"]["by_tag"], [{"key": "(untagged)", "count": 1}])
        self.assertEqual(result["repeated_groups"], [])

    def test_video_analysis_groups_repeated_and_locale_unique_issues(self):
        memories = [
            {
                "chunk_id": "a",
                "text": "Description/ Comment: Same issue with ZHCN line 4",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "Video One",
                    "code": "MS0001",
                    "category": "MS",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "row_index": 4,
                    "tags": "Copy",
                },
            },
            {
                "chunk_id": "b",
                "text": "Description/ Comment: Same issue with ZHCN line 4",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "Video One",
                    "code": "MS0001",
                    "category": "MS",
                    "sprint": "MS19",
                    "sheet": "JAJP",
                    "row_index": 5,
                    "tags": "Copy",
                },
            },
            {
                "chunk_id": "c",
                "text": "Description/ Comment: FRCA only subtitle line break issue",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "Video One",
                    "code": "MS0001",
                    "category": "MS",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "row_index": 8,
                    "tags": "Motion",
                },
            },
        ]

        with patch.object(duck_lance_store, "list_memories", return_value=memories):
            result = issue_analysis.analyze_video(doc_id="doc-1")

        self.assertEqual(result["summary"]["total_issues"], 3)
        self.assertEqual(result["doc"]["code"], "MS0001")
        self.assertEqual(result["repeated_groups"][0]["count"], 2)
        self.assertIn("FRCA", result["unique_by_locale"])

    def test_sprint_analysis_tracks_recurring_across_docs(self):
        memories = [
            {
                "chunk_id": "a",
                "text": "Description/ Comment: Missing translated album name",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "Video One",
                    "code": "MS0001",
                    "category": "MS",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "Copy",
                },
            },
            {
                "chunk_id": "b",
                "text": "Description/ Comment: Missing translated album name",
                "metadata": {
                    "doc_id": "doc-2",
                    "title": "Video Two",
                    "code": "MS0002",
                    "category": "MS",
                    "sprint": "MS19",
                    "sheet": "PTBR",
                    "tags": "Copy",
                },
            },
        ]

        with patch.object(duck_lance_store, "list_memories", return_value=memories):
            result = issue_analysis.analyze_sprint(sprint="MS19", tag="Copy")

        self.assertEqual(result["summary"]["total_docs"], 2)
        self.assertEqual(result["recurring_across_docs"][0]["count"], 2)
        self.assertEqual(len(result["recurring_across_docs"][0]["docs"]), 2)

    def test_compare_sprints_returns_persistent_resolved_and_new_groups(self):
        sprint_a = [
            {
                "chunk_id": "a",
                "text": "Description/ Comment: Persistent typo in CTA",
                "metadata": {"doc_id": "doc-1", "title": "A", "code": "MS0001", "category": "MS", "sprint": "MS19", "sheet": "FRCA", "tags": "Copy"},
            },
            {
                "chunk_id": "b",
                "text": "Description/ Comment: Old line break issue",
                "metadata": {"doc_id": "doc-1", "title": "A", "code": "MS0001", "category": "MS", "sprint": "MS19", "sheet": "JAJP", "tags": "Motion"},
            },
        ]
        sprint_b = [
            {
                "chunk_id": "c",
                "text": "Description/ Comment: Persistent typo in CTA",
                "metadata": {"doc_id": "doc-2", "title": "B", "code": "MS0002", "category": "MS", "sprint": "MS20", "sheet": "FRCA", "tags": "Copy"},
            },
            {
                "chunk_id": "d",
                "text": "Description/ Comment: New source mismatch",
                "metadata": {"doc_id": "doc-2", "title": "B", "code": "MS0002", "category": "MS", "sprint": "MS20", "sheet": "PTBR", "tags": "Source"},
            },
        ]

        def fake_list_memories(category=None, sprint=None, tag=None, doc_id=None, q=None, limit=200, **kwargs):
            return sprint_a if sprint == "MS19" else sprint_b

        with patch.object(duck_lance_store, "list_memories", side_effect=fake_list_memories):
            result = issue_analysis.compare_sprints("MS19", "MS20")

        self.assertEqual(len(result["persistent"]), 1)
        self.assertEqual(result["persistent"][0]["count_a"], 1)
        self.assertEqual(result["persistent"][0]["count_b"], 1)
        self.assertEqual(len(result["resolved"]), 1)
        self.assertEqual(len(result["new"]), 1)


if __name__ == "__main__":
    unittest.main()
