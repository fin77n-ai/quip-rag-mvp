import unittest

from backend.models.rules import FilterRules
from backend.models.tags import DocTags, RowTag
from backend.services import quip_parser


class QuipParserPlainTextTest(unittest.TestCase):
    def test_cleaned_plain_text_json_recovers_doc_id_and_table_rows(self):
        data = {
            "doc_id": "doc-123",
            "title": "MS0001_Test",
            "plain_text": (
                "MS0001_Test\n"
                "[TABLE]\n"
                " | A | B | C | D\n"
                ": 1, A: Status, B: Description/ Comment, C: Response, D: Response by\n"
                ": 2, A: Open, B: Button label is mistranslated, C: Please update copy, D: Copy\n"
                "[/TABLE]"
            ),
            "sections": [],
        }
        rules = FilterRules(
            include_columns=["Description/ Comment", "Response", "Response by"],
            min_chunk_chars=1,
        )

        parsed = quip_parser.parse_dict(data, rules)
        preview = quip_parser.preview_dict(data, rules)

        self.assertEqual(parsed.doc_id, "doc-123")
        self.assertEqual(preview["doc_id"], "doc-123")
        self.assertEqual(len(parsed.table_rows), 1)
        self.assertEqual(parsed.table_rows[0]["row_index"], 2)
        self.assertEqual(parsed.table_rows[0]["cells"]["Description/ Comment"], "Button label is mistranslated")


class QuipParserNestedThreadTest(unittest.TestCase):
    def test_nested_thread_json_is_supported(self):
        data = {
            "thread": {
                "id": "nested-1",
                "title": "VSD0002_Nested",
                "created_usec": 1_700_000_000_000_000,
                "updated_usec": 1_700_000_000_000_000,
            },
            "html": "<h1>Intro</h1><p>Hello from nested thread.</p>",
        }

        parsed = quip_parser.parse_dict(data, FilterRules(min_chunk_chars=1))

        self.assertEqual(parsed.doc_id, "nested-1")
        self.assertEqual(parsed.title, "VSD0002_Nested")
        self.assertIn("Hello from nested thread.", parsed.plain_text)


class QuipParserPreviewTest(unittest.TestCase):
    def test_preview_does_not_hide_rows_excluded_by_saved_tags(self):
        data = {
            "thread_id": "tagged-doc",
            "title": "MS0003_Tagged",
            "html": (
                "<table title='DEDE'>"
                "<tr><td>Description/ Comment</td><td>Response</td><td>Response by</td></tr>"
                "<tr><td>Visible in preview</td><td>Needs answer</td><td>Copy</td></tr>"
                "</table>"
            ),
        }
        rules = FilterRules(
            include_columns=["Description/ Comment", "Response", "Response by"],
            min_chunk_chars=1,
        )

        original_load = quip_parser.tags_store.load
        quip_parser.tags_store.load = lambda doc_id: DocTags(
            doc_id=doc_id,
            rows={"DEDE::1": RowTag(tags=[], excluded=True)},
        )
        try:
            preview = quip_parser.preview_dict(data, rules)
            parsed = quip_parser.parse_dict(data, rules)
        finally:
            quip_parser.tags_store.load = original_load

        self.assertEqual(preview["table_rows_count"], 1)
        self.assertIn("Visible in preview", preview["sample_text"])
        self.assertEqual(len(parsed.table_rows), 0)


if __name__ == "__main__":
    unittest.main()
