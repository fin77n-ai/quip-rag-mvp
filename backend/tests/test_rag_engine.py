import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

from backend.models.query import QueryFilters, QueryRequest, QueryResponse, Citation, QueryDebug, CompareRequest, QueryMessage
from backend.models.qc import QCReport
from backend.services import duck_lance_store, rag_engine


class FakeCollection:
    def get(self, where=None, include=None):
        return {
            "ids": ["copy-id", "motion-id"],
            "metadatas": [
                {
                    "doc_id": "doc-1",
                    "title": "MS0001_Copy",
                    "category": "MS",
                    "code": "MS0001",
                    "sprint": "",
                    "tags": "Copy",
                },
                {
                    "doc_id": "doc-2",
                    "title": "MS0002_Motion",
                    "category": "MS",
                    "code": "MS0002",
                    "sprint": "",
                    "tags": "Motion",
                },
            ],
        }


class MatchingCollection:
    def __init__(self, ids, metadatas):
        self.ids = ids
        self.metadatas = metadatas

    def get(self, where=None, include=None):
        return {
            "ids": self.ids,
            "metadatas": self.metadatas,
        }


class RagEngineTagFilterTest(unittest.IsolatedAsyncioTestCase):
    async def _run_answer(self, req: QueryRequest) -> QueryResponse:
        import json
        last_data = None
        async for chunk in rag_engine.answer(req):
            data = json.loads(chunk)
            if data["type"] == "result":
                last_data = data["data"]
        if last_data is None:
            raise ValueError("No result chunk yielded")
        return QueryResponse(**last_data)

    async def test_answer_stream_emits_error_chunk_when_query_fails(self):
        with patch.object(rag_engine.query_planner, "plan_query", side_effect=RuntimeError("budget exhausted")):
            chunks = []
            async for chunk in rag_engine.answer(QueryRequest(question="What broke?"), "trace-123"):
                chunks.append(chunk)

        self.assertTrue(any('"type": "error"' in chunk for chunk in chunks))
        self.assertTrue(any("budget exhausted" in chunk for chunk in chunks))

    async def test_attach_query_qc_repairs_failed_answer_once(self):
        response = QueryResponse(
            answer="There are 9 major issues everywhere.",
            citations=[
                Citation(
                    chunk_id="c1",
                    doc_id="doc-1",
                    title="Doc",
                    category="MS",
                    code="MS0001",
                    sprint="MS19",
                    snippet="One pacing issue is cited here.",
                    score=1.0,
                )
            ],
            elapsed_ms=5,
            debug=QueryDebug(route="stats"),
        )

        class RepairResult:
            text = "There is at least one cited pacing issue in [MS0001]."
            prompt_tokens = 3
            candidates_tokens = 4
            total_tokens = 7

        reports = [
            QCReport(stage="query_answer", status="fail", summary="bad", metrics={"repair_instruction": "Remove unsupported count claims"}),
            QCReport(stage="query_answer", status="pass", summary="good", metrics={}),
        ]

        with (
            patch.object(rag_engine.qc_service, "qc_query_answer", side_effect=reports) as qc_run,
            patch.object(rag_engine, "_repair_answer_with_qc", return_value=RepairResult()) as repair,
        ):
            updated = await rag_engine._attach_query_qc(QueryRequest(question="Top issues?", qc_enabled=True), response)

        self.assertEqual(updated.answer, "There is at least one cited pacing issue in [MS0001].")
        self.assertEqual(updated.qc.status, "pass")
        self.assertTrue(updated.qc.metrics["repair_applied"])
        self.assertEqual(qc_run.await_count, 2)
        repair.assert_awaited_once()

    async def test_compare_attaches_qc_to_primary_result(self):
        compare_response = rag_engine.CompareResponse(
            sprint_a="MS18",
            sprint_b="MS19",
            result_a=QueryResponse(answer="Compare answer", citations=[], elapsed_ms=1, debug=QueryDebug(route="compare")),
            result_b=QueryResponse(answer="", citations=[], elapsed_ms=0, debug=QueryDebug(route="compare")),
        )

        qc_report = QCReport(stage="query_answer", status="pass", summary="ok")

        with patch.object(rag_engine, "_attach_query_qc", return_value=compare_response.result_a.model_copy(update={"qc": qc_report})) as attach:
            updated = await rag_engine._attach_compare_qc(CompareRequest(question="Compare", sprint_a="MS18", sprint_b="MS19", qc_enabled=True), compare_response)

        self.assertEqual(updated.result_a.qc.status, "pass")
        attach.assert_awaited_once()

    async def test_tag_filter_restricts_vector_query_to_matching_ids(self):
        captured = {}

        def fake_search(query_embedding, top_k, where=None, include_embeddings=False, ids=None):
            captured["query_embedding"] = query_embedding
            captured["top_k"] = top_k
            captured["where"] = where
            captured["include_embeddings"] = include_embeddings
            captured["ids"] = ids
            return {
                "ids": [["copy-id"]],
                "documents": [["Button label is mistranslated."]],
                "metadatas": [[
                    {
                        "doc_id": "doc-1",
                        "title": "MS0001_Copy",
                        "category": "MS",
                        "code": "MS0001",
                        "sprint": "",
                        "tags": "Copy",
                    }
                ]],
                "distances": [[0.1]],
            }

        async def fake_generate(prompt, model_type="default", **kwargs):
            captured["prompt"] = prompt
            return "Use the copy issue citation."

        with (
            patch.object(rag_engine.embedder, "encode", return_value=[[0.1, 0.2]]),

            patch.object(rag_engine.vector_store, "get_chunk_ids", return_value=["copy-id"]),
            patch.object(rag_engine.vector_store, "search", side_effect=fake_search),
            patch.object(rag_engine.llm_client, "generate", side_effect=fake_generate),
            patch.object(rag_engine.settings, "rerank_enabled", False),
            patch.object(rag_engine.settings, "mmr_enabled", False),
            patch.object(rag_engine.settings, "keyword_recall_enabled", False),
        ):
            res = await self._run_answer(
                QueryRequest(
                    question="What copy issues exist?",
                    filters=QueryFilters(tags=["Copy"]),
                    top_k=2,
                )
            )

        self.assertEqual(captured["ids"], ["copy-id"])
        self.assertEqual(captured["top_k"], 1)
        self.assertEqual(res.answer, "Use the copy issue citation.")
        self.assertEqual([c.chunk_id for c in res.citations], ["copy-id"])

    async def test_follow_up_history_is_included_in_retrieval_and_prompt(self):
        captured = {}

        def fake_search(query_embedding, top_k, where=None, include_embeddings=False, ids=None):
            captured["query_embedding"] = query_embedding
            return {
                "ids": [["copy-id"]],
                "documents": [["French copy issue on settings screen."]],
                "metadatas": [[
                    {
                        "doc_id": "doc-1",
                        "title": "MS0001_Copy",
                        "category": "MS",
                        "code": "MS0001",
                        "sprint": "",
                        "tags": "Translation",
                    }
                ]],
                "distances": [[0.1]],
            }

        async def fake_generate(prompt, model_type="default", **kwargs):
            captured["prompt"] = prompt
            return "Follow-up answer."

        with (
            patch.object(rag_engine.embedder, "encode", side_effect=lambda texts: captured.__setitem__("embedded_text", texts[0]) or [[0.1, 0.2]]),
            patch.object(rag_engine.vector_store, "get_chunk_ids", return_value=["copy-id"]),
            patch.object(rag_engine.vector_store, "search", side_effect=fake_search),
            patch.object(rag_engine.llm_client, "generate", side_effect=fake_generate),
            patch.object(rag_engine.query_planner, "plan_query", return_value=SimpleNamespace(route="rag", intent="rag", inferred_tags=[])),
            patch.object(rag_engine.settings, "rerank_enabled", False),
            patch.object(rag_engine.settings, "mmr_enabled", False),
            patch.object(rag_engine.settings, "keyword_recall_enabled", False),
        ):
            res = await self._run_answer(
                QueryRequest(
                    question="那法语呢？",
                    history=[
                        QueryMessage(role="user", content="哪些语言的 translation 问题最多？"),
                        QueryMessage(role="assistant", content="目前看到 JAJP 和 FRFR 比较多。"),
                    ],
                    filters=QueryFilters(tags=["Translation"]),
                    top_k=2,
                    intent_override="rag",
                )
            )

        self.assertIn("哪些语言的 translation 问题最多", captured["embedded_text"])
        self.assertIn("Current user question: 那法语呢？", captured["embedded_text"])
        self.assertIn("Conversation so far:", captured["prompt"])
        self.assertIn("Assistant: 目前看到 JAJP 和 FRFR 比较多。", captured["prompt"])
        self.assertIn("Current user question: 那法语呢？", captured["prompt"])
        self.assertEqual(res.answer, "Follow-up answer.")

    async def test_aggregate_question_sends_stats_and_chunks_to_llm(self):
        memories = [
            {
                "chunk_id": "a",
                "text": "Copy issue A",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "VSD0001_Test",
                    "category": "VSD",
                    "code": "VSD0001",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "Copy",
                },
            },
            {
                "chunk_id": "b",
                "text": "Copy issue B",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "VSD0001_Test",
                    "category": "VSD",
                    "code": "VSD0001",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "Copy,Motion",
                },
            },
            {
                "chunk_id": "c",
                "text": "Copy issue C",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "VSD0001_Test",
                    "category": "VSD",
                    "code": "VSD0001",
                    "sprint": "MS19",
                    "sheet": "ZHCN",
                    "tags": "Copy",
                },
            },
        ]
        captured = {}

        async def fake_generate(prompt, model_type="default", **kwargs):
            captured["prompt"] = prompt
            return "LLM aggregate answer."

        with (
            patch.object(rag_engine.query_planner, "plan_query", return_value=SimpleNamespace(route="stats", intent="aggregate", inferred_tags=[])),
            patch.object(rag_engine.vector_store, "list_memories", return_value=memories),
            patch.object(rag_engine.embedder, "encode") as encode,
            patch.object(rag_engine.llm_client, "generate", side_effect=fake_generate) as generate,
        ):
            res = await self._run_answer(
                QueryRequest(
                    question="in MS19 how many copy issues and which locale has the most problems",
                    filters=QueryFilters(categories=["VSD"], sprints=["MS19"]),
                    top_k=2,
                )
            )

        self.assertEqual(res.answer, "LLM aggregate answer.")
        self.assertIn("Total matching chunks: 3", captured["prompt"])
        self.assertIn("Most affected locale(s): FRCA (2)", captured["prompt"])
        self.assertIn("Issue type breakdown: Copy: 3, Motion: 1", captured["prompt"])
        self.assertIn("Locale digest:", captured["prompt"])
        self.assertIn("FRCA: 2 chunks; tags: Copy: 2, Motion: 1", captured["prompt"])
        self.assertNotIn("Representative chunks:", captured["prompt"])
        self.assertEqual([c.chunk_id for c in res.citations], ["a", "c", "b"])
        self.assertEqual(res.debug.route, "stats")
        self.assertEqual(res.debug.intent, "aggregate")
        self.assertEqual(res.debug.candidate_count, 3)
        encode.assert_not_called()
        generate.assert_awaited_once()

    async def test_retake_aggregate_question_prefers_explicit_retake_chunks(self):
        memories = [
            {
                "chunk_id": "retake-1",
                "text": "Description/ Comment: VO needs retake due to mouth noise.",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "MS0001_Test",
                    "category": "MS",
                    "code": "MS0001",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "Source",
                    "retake_explicit": "yes",
                    "retake_terms": "retake",
                },
            },
            {
                "chunk_id": "vo-generic",
                "text": "Description/ Comment: VO pacing is a little slow.",
                "metadata": {
                    "doc_id": "doc-2",
                    "title": "MS0002_Test",
                    "category": "MS",
                    "code": "MS0002",
                    "sprint": "MS19",
                    "sheet": "JAJP",
                    "tags": "Source",
                    "retake_explicit": "no",
                    "retake_terms": "",
                },
            },
        ]
        captured = {"prompts": []}

        async def fake_generate(prompt, model_type="default", **kwargs):
            captured["prompts"].append(prompt)
            return "There is 1 explicit retake issue."

        with (
            patch.object(rag_engine.query_planner, "plan_query", return_value=SimpleNamespace(route="stats", intent="aggregate", inferred_tags=[])),
            patch.object(rag_engine.vector_store, "list_memories", return_value=memories),
            patch.object(rag_engine.embedder, "encode") as encode,
            patch.object(rag_engine.llm_client, "generate", side_effect=fake_generate) as generate,
        ):
            res = await self._run_answer(
                QueryRequest(
                    question="How many VO retake issues are explicitly mentioned in MS19?",
                    filters=QueryFilters(sprints=["MS19"]),
                    top_k=3,
                )
            )

        self.assertEqual(res.answer, "There is 1 explicit retake issue.")
        first_prompt = captured["prompts"][0]
        self.assertIn("Total matching chunks: 1", first_prompt)
        self.assertIn("retake", first_prompt.lower())
        self.assertNotIn("VO pacing is a little slow", first_prompt)
        self.assertEqual([c.chunk_id for c in res.citations], ["retake-1"])
        encode.assert_not_called()
        self.assertGreaterEqual(generate.await_count, 1)

    async def test_chinese_worst_region_question_routes_to_stats(self):
        memories = [
            {
                "chunk_id": "a",
                "text": "Description/ Comment: Motion issue A",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "MS0001_Test",
                    "category": "MS",
                    "code": "MS0001",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "Motion",
                },
            },
            {
                "chunk_id": "b",
                "text": "Description/ Comment: Copy issue B",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "MS0001_Test",
                    "category": "MS",
                    "code": "MS0001",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "Copy",
                },
            },
            {
                "chunk_id": "c",
                "text": "Description/ Comment: Source issue C",
                "metadata": {
                    "doc_id": "doc-2",
                    "title": "MS0002_Test",
                    "category": "MS",
                    "code": "MS0002",
                    "sprint": "MS19",
                    "sheet": "ZHCN",
                    "tags": "Source",
                },
            },
        ]
        captured = {}

        async def fake_generate(prompt, model_type="default", **kwargs):
            captured["prompt"] = prompt
            return "LLM 中文分析。"

        with (
            patch.object(rag_engine.query_planner, "plan_query", return_value=SimpleNamespace(route="stats", intent="aggregate", inferred_tags=[])),
            patch.object(rag_engine.vector_store, "list_memories", return_value=memories),
            patch.object(rag_engine.embedder, "encode") as encode,
            patch.object(rag_engine.llm_client, "generate", side_effect=fake_generate) as generate,
        ):
            res = await self._run_answer(
                QueryRequest(
                    question="这个 sprint 主要出现了哪些问题，最严重的地区是什么",
                    filters=QueryFilters(categories=["MS"], sprints=["MS19"]),
                    top_k=2,
                )
            )

        self.assertEqual(res.debug.route, "stats")
        self.assertEqual(res.debug.intent, "aggregate")
        self.assertEqual(res.answer, "LLM 中文分析。")
        self.assertIn("Answer in the same language as the user question", captured["prompt"])
        self.assertIn("Most affected locale(s): FRCA (2)", captured["prompt"])
        self.assertIn("Issue type breakdown: Motion: 1, Copy: 1, Source: 1", captured["prompt"])
        encode.assert_not_called()
        generate.assert_awaited_once()

    async def test_language_breakdown_question_filters_to_focus_term_chunks(self):
        memories = [
            {
                "chunk_id": "vo-frca",
                "text": "Description/ Comment: VO pronunciation sounds unnatural.",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "MS0001_Test",
                    "category": "MS",
                    "code": "MS0001",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "Source",
                },
            },
            {
                "chunk_id": "vo-zHCN",
                "text": "Description/ Comment: VO is out of sync with subtitles.",
                "metadata": {
                    "doc_id": "doc-2",
                    "title": "MS0002_Test",
                    "category": "MS",
                    "code": "MS0002",
                    "sprint": "MS19",
                    "sheet": "ZHCN",
                    "tags": "Motion",
                },
            },
            {
                "chunk_id": "copy-frca",
                "text": "Description/ Comment: CTA copy typo.",
                "metadata": {
                    "doc_id": "doc-3",
                    "title": "MS0003_Test",
                    "category": "MS",
                    "code": "MS0003",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "Copy",
                },
            },
        ]
        captured = {}

        async def fake_generate(prompt, model_type="default", **kwargs):
            captured["prompt"] = prompt
            return "VO pronunciation and sync analysis."

        with (
            patch.object(rag_engine.query_planner, "plan_query", return_value=SimpleNamespace(route="stats", intent="aggregate", inferred_tags=[])),
            patch.object(rag_engine.vector_store, "list_memories", return_value=memories),
            patch.object(rag_engine.embedder, "encode") as encode,
            patch.object(rag_engine.llm_client, "generate", side_effect=fake_generate) as generate,
        ):
            res = await self._run_answer(
                QueryRequest(
                    question="MS19 VO 有什么问题吗？ 帮忙列举一下各个语言的情况",
                    filters=QueryFilters(sprints=["MS19"]),
                    top_k=2,
                )
            )

        self.assertEqual(res.debug.route, "stats")
        self.assertEqual(res.debug.intent, "aggregate")
        self.assertEqual(res.debug.candidate_count, 2)
        self.assertIn("Total matching chunks: 2", captured["prompt"])
        self.assertIn("Locale breakdown: FRCA: 1, ZHCN: 1", captured["prompt"])
        self.assertIn("Focus terms used to narrow chunks: vo", captured["prompt"])
        self.assertIn("FRCA: 1 chunks; tags: Source: 1", captured["prompt"])
        self.assertIn("ZHCN: 1 chunks; tags: Motion: 1", captured["prompt"])
        self.assertNotIn("CTA copy typo", captured["prompt"])
        self.assertEqual([c.chunk_id for c in res.citations], ["vo-frca", "vo-zHCN"])
        encode.assert_not_called()
        generate.assert_awaited_once()

    async def test_broad_chinese_issue_question_routes_to_full_sprint_analysis(self):
        memories = [
            {
                "chunk_id": "a",
                "text": "Description/ Comment: Motion issue A",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "VSD0001_Test",
                    "category": "VSD",
                    "code": "VSD0001",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "Motion",
                },
            },
            {
                "chunk_id": "b",
                "text": "Description/ Comment: Copy issue B",
                "metadata": {
                    "doc_id": "doc-2",
                    "title": "MS0001_Test",
                    "category": "MS",
                    "code": "MS0001",
                    "sprint": "MS19",
                    "sheet": "ZHCN",
                    "tags": "Copy",
                },
            },
        ]
        captured = {}

        async def fake_generate(prompt, model_type="default", **kwargs):
            captured["prompt"] = prompt
            return "Full sprint analysis."

        with (
            patch.object(rag_engine.query_planner, "plan_query", return_value=SimpleNamespace(route="stats", intent="aggregate", inferred_tags=[])),
            patch.object(rag_engine.vector_store, "list_memories", return_value=memories) as list_memories,
            patch.object(rag_engine.embedder, "encode") as encode,
            patch.object(rag_engine.llm_client, "generate", side_effect=fake_generate) as generate,
        ):
            res = await self._run_answer(
                QueryRequest(
                    question="MS19的视频有什么都有的问题吗",
                    filters=QueryFilters(sprints=["MS19"]),
                    top_k=2,
                )
            )

        self.assertEqual(res.debug.route, "stats")
        self.assertEqual(res.debug.intent, "aggregate")
        self.assertEqual(res.debug.candidate_count, 2)
        self.assertEqual(list_memories.call_args.kwargs["limit"], rag_engine.AGGREGATE_MEMORY_LIMIT)
        self.assertIn("Total matching chunks: 2", captured["prompt"])
        self.assertIn("Locale digest:", captured["prompt"])
        encode.assert_not_called()
        generate.assert_awaited_once()

    async def test_aggregate_citations_are_capped_for_large_result_sets(self):
        memories = [
            {
                "chunk_id": f"chunk-{i}",
                "text": f"Copy issue {i}",
                "metadata": {
                    "doc_id": f"doc-{i}",
                    "title": f"MS{i:04d}_Test",
                    "category": "MS",
                    "code": f"MS{i:04d}",
                    "sprint": "MS19",
                    "sheet": f"L{i % 5}",
                    "tags": "Copy",
                },
            }
            for i in range(80)
        ]

        res_obj = type("Resp", (), {
            "text": "LLM aggregate answer.",
            "prompt_tokens": 10,
            "candidates_tokens": 20,
            "total_tokens": 30,
        })()

        with (
            patch.object(rag_engine.query_planner, "plan_query", return_value=SimpleNamespace(route="stats", intent="aggregate", inferred_tags=[])),
            patch.object(rag_engine.vector_store, "list_memories", return_value=memories),
            patch.object(rag_engine.embedder, "encode") as encode,
            patch.object(rag_engine.llm_client, "generate_with_metrics", return_value=res_obj),
        ):
            res = await self._run_answer(
                QueryRequest(
                    question="MS19 有多少 copy 问题？",
                    filters=QueryFilters(sprints=["MS19"]),
                    top_k=5,
                )
            )

        self.assertEqual(res.debug.candidate_count, 80)
        self.assertEqual(res.debug.selected_count, rag_engine.AGGREGATE_CITATION_LIMIT)
        self.assertEqual(len(res.citations), rag_engine.AGGREGATE_CITATION_LIMIT)
        encode.assert_not_called()

    async def test_compare_caps_memory_fetch_limit(self):
        captured = {}

        def fake_list_memories(*, sprint=None, tag=None, limit=None):
            captured[sprint] = limit
            return [{
                "chunk_id": f"{sprint}-1",
                "text": f"{sprint} issue",
                "metadata": {
                    "doc_id": f"doc-{sprint}",
                    "title": f"title-{sprint}",
                    "category": "MS",
                    "code": f"MS-{sprint}",
                    "sprint": sprint,
                    "issue_type": "Copy",
                },
            }]

        plan = type("Plan", (), {"route": "rag", "intent": "rag", "inferred_tags": []})()
        res_obj = type("Resp", (), {
            "text": "compare answer",
            "prompt_tokens": 10,
            "candidates_tokens": 20,
            "total_tokens": 30,
        })()

        with (
            patch.object(rag_engine.query_planner, "plan_query", return_value=plan),
            patch.object(duck_lance_store, "list_memories", side_effect=fake_list_memories),
            patch.object(rag_engine.llm_client, "generate_with_metrics", return_value=res_obj),
        ):
            res = await rag_engine.compare(rag_engine.CompareRequest(
                question="what changed",
                sprint_a="MS18",
                sprint_b="MS19",
                top_k=10000,
            ))

        self.assertEqual(captured["MS18"], rag_engine.COMPARE_MEMORY_LIMIT)
        self.assertEqual(captured["MS19"], rag_engine.COMPARE_MEMORY_LIMIT)
        self.assertEqual(res.result_a.debug.selected_count, 1)
        self.assertEqual(len(res.result_a.citations), 1)

    async def test_chinese_voiceover_question_focuses_vo_chunks(self):
        memories = [
            {
                "chunk_id": "vo-source",
                "text": "Comment: The overall pacing of the scratch VO feels slower than real VO.",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "VSD0001_Test",
                    "category": "VSD",
                    "code": "VSD0001",
                    "sprint": "MS18",
                    "sheet": "TRTR",
                    "tags": "Source",
                },
            },
            {
                "chunk_id": "vo-motion",
                "text": "Comment: I hear lots of mouth noises throughout the real VO recording.",
                "metadata": {
                    "doc_id": "doc-2",
                    "title": "VSD0002_Test",
                    "category": "VSD",
                    "code": "VSD0002",
                    "sprint": "MS18",
                    "sheet": "JAJP",
                    "tags": "Motion",
                },
            },
            {
                "chunk_id": "copy",
                "text": "Comment: CTA copy has a typo.",
                "metadata": {
                    "doc_id": "doc-3",
                    "title": "VSD0003_Test",
                    "category": "VSD",
                    "code": "VSD0003",
                    "sprint": "MS18",
                    "sheet": "FRCA",
                    "tags": "Copy",
                },
            },
        ]
        captured = {}

        captured["prompts"] = []

        async def fake_generate(prompt, model_type="default", **kwargs):
            captured["prompts"].append(prompt)
            captured["prompt"] = prompt
            if len(captured["prompts"]) == 1:
                return "只提到了普通 VO 问题。"
            return "补充：scratch VO pacing 较慢，并且 real VO 有 mouth noise。"

        with (
            patch.object(rag_engine.query_planner, "plan_query", return_value=SimpleNamespace(route="stats", intent="aggregate", inferred_tags=[])),
            patch.object(rag_engine.vector_store, "list_memories", return_value=memories),
            patch.object(rag_engine.embedder, "encode") as encode,
            patch.object(rag_engine.llm_client, "generate", side_effect=fake_generate) as generate,
        ):
            res = await self._run_answer(
                QueryRequest(
                    question="MS18的视频配音有很严重的问题吗",
                    filters=QueryFilters(sprints=["MS18"]),
                    top_k=2,
                )
            )

        self.assertEqual(res.debug.route, "stats")
        self.assertEqual(res.debug.intent, "aggregate")
        self.assertEqual(res.debug.candidate_count, 2)
        first_prompt = captured["prompts"][0]
        repair_prompt = captured["prompts"][1]
        self.assertIn("Focus terms used to narrow chunks: vo", first_prompt)
        self.assertIn("Total matching chunks: 2", first_prompt)
        self.assertIn("Theme digest:", first_prompt)
        self.assertIn("scratch VO pacing / timing: 1 chunks", first_prompt)
        self.assertIn("real/final VO noise: 1 chunks", first_prompt)
        self.assertIn("Missing themes that must be covered", repair_prompt)
        self.assertIn("scratch VO pacing / timing", repair_prompt)
        self.assertIn("real/final VO noise", repair_prompt)
        self.assertNotIn("CTA copy has a typo", first_prompt)
        self.assertEqual([c.chunk_id for c in res.citations], ["vo-source", "vo-motion"])
        self.assertEqual(res.answer, "补充：scratch VO pacing 较慢，并且 real VO 有 mouth noise。")
        encode.assert_not_called()
        self.assertEqual(generate.await_count, 2)

    async def test_repeated_question_routes_to_analysis_without_llm(self):
        repeated = {
            "total_groups": 1,
            "total_memories_scanned": 2,
            "filters": {"sprint": "MS19", "tag": "Copy"},
            "groups": [
                {
                    "key": "same issue",
                    "summary": "Same issue with ZHCN line 4",
                    "count": 2,
                    "locales": ["FRCA", "JAJP"],
                    "docs": [{"doc_id": "doc-1", "code": "MS0001", "title": "Video One"}],
                    "tags": ["Copy"],
                    "examples": [
                        {
                            "chunk_id": "a",
                            "doc_id": "doc-1",
                            "code": "MS0001",
                            "title": "Video One",
                            "locale": "FRCA",
                            "row_index": 4,
                            "tags": ["Copy"],
                            "text": "Description/ Comment: Same issue with ZHCN line 4",
                        }
                    ],
                }
            ],
        }

        async def fake_generate(*args, **kwargs):
            return '{"intent": "repeated", "reasoning": "test"}'

        with (
            patch.object(rag_engine.issue_analysis, "repeated_issue_groups", return_value=repeated) as analysis,
            patch.object(rag_engine.embedder, "encode") as encode,
            patch.object(rag_engine.llm_client, "generate", side_effect=fake_generate) as generate,
        ):
            res = await self._run_answer(
                QueryRequest(
                    question="which copy issues are repeated across locales in MS19?",
                    filters=QueryFilters(sprints=["MS19"]),
                    top_k=2,
                )
            )

        analysis.assert_called_once()
        self.assertEqual(analysis.call_args.kwargs["tag"], "Copy")
        self.assertIn("Repeated issue groups found", res.answer)
        self.assertEqual(res.debug.route, "analyze/repeated")
        self.assertEqual(res.debug.intent, "repeated")
        self.assertEqual(res.debug.inferred_tags, ["Copy"])
        encode.assert_not_called()
        self.assertEqual(generate.call_count, 1)

    async def test_hybrid_score_can_promote_keyword_and_metadata_matches(self):
        def fake_search(query_embedding, top_k, where=None, include_embeddings=False, ids=None):
            return {
                "ids": [["semantic-id", "keyword-id"]],
                "documents": [[
                    "Description/ Comment: Generic visual issue.",
                    "Description/ Comment: Same issue with ZHCN line 4, pending confirm from VSD Team.",
                ]],
                "metadatas": [[
                    {
                        "doc_id": "doc-1",
                        "title": "MS0001_Motion",
                        "category": "MS",
                        "code": "MS0001",
                        "sprint": "MS19",
                        "sheet": "FRCA",
                        "tags": "Motion",
                    },
                    {
                        "doc_id": "doc-1",
                        "title": "MS0001_Copy",
                        "category": "MS",
                        "code": "MS0001",
                        "sprint": "MS19",
                        "sheet": "ZHCN",
                        "tags": "Copy",
                    },
                ]],
                "distances": [[0.05, 0.30]],
                "embeddings": [[[0.1, 0.1], [0.2, 0.2]]] if include_embeddings else None,
            }

        async def fake_generate(prompt, model_type="default", **kwargs):
            return "Keyword-backed answer."

        collection = MatchingCollection(
            ["semantic-id", "keyword-id"],
            [
                {
                    "doc_id": "doc-1",
                    "title": "MS0001_Motion",
                    "category": "MS",
                    "code": "MS0001",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "Motion",
                },
                {
                    "doc_id": "doc-1",
                    "title": "MS0001_Copy",
                    "category": "MS",
                    "code": "MS0001",
                    "sprint": "MS19",
                    "sheet": "ZHCN",
                    "tags": "Copy",
                },
            ],
        )

        with (
            patch.object(rag_engine.embedder, "encode", return_value=[[0.1, 0.2]]),

            patch.object(rag_engine.vector_store, "get_chunk_ids", return_value=["semantic-id", "keyword-id"]),
            patch.object(rag_engine.vector_store, "search", side_effect=fake_search),
            patch.object(rag_engine.reranker, "rerank", return_value=[0.0, 0.0]),
            patch.object(rag_engine.llm_client, "generate", side_effect=fake_generate),
            patch.object(rag_engine.settings, "rerank_enabled", True),
            patch.object(rag_engine.settings, "mmr_enabled", False),
            patch.object(rag_engine.settings, "keyword_recall_enabled", False),
        ):
            res = await self._run_answer(
                QueryRequest(
                    question="MS19 Copy line 4 issue",
                    filters=QueryFilters(sprints=["MS19"]),
                    top_k=1,
                )
            )

        self.assertEqual([c.chunk_id for c in res.citations], ["keyword-id"])
        self.assertGreater(res.citations[0].keyword_score, 0)
        self.assertGreater(res.citations[0].metadata_score, 0)
        self.assertIn("copy", res.citations[0].matched_terms)
        self.assertEqual(res.debug.route, "rag")
        self.assertEqual(res.debug.candidate_count, 2)
        self.assertEqual(res.debug.selected_count, 1)

    async def test_keyword_recall_adds_candidate_missed_by_vector_search(self):
        def fake_search(query_embedding, top_k, where=None, include_embeddings=False, ids=None):
            return {
                "ids": [["semantic-id"]],
                "documents": [["Description/ Comment: Generic visual issue."]],
                "metadatas": [[
                    {
                        "doc_id": "doc-1",
                        "title": "MS0001_Motion",
                        "category": "MS",
                        "code": "MS0001",
                        "sprint": "MS19",
                        "sheet": "FRCA",
                        "tags": "Motion",
                    }
                ]],
                "distances": [[0.05]],
            }

        memories = [
            {
                "chunk_id": "keyword-id",
                "text": "Description/ Comment: Same issue with ZHCN line 4, pending confirm from VSD Team.",
                "metadata": {
                    "doc_id": "doc-1",
                    "title": "MS0001_Copy",
                    "category": "MS",
                    "code": "MS0001",
                    "sprint": "MS19",
                    "sheet": "ZHCN",
                    "tags": "Copy",
                },
            }
        ]

        async def fake_generate(prompt, model_type="default", **kwargs):
            return "Keyword recall answer."

        collection = MatchingCollection(
            ["semantic-id", "keyword-id"],
            [
                {
                    "doc_id": "doc-1",
                    "title": "MS0001_Motion",
                    "category": "MS",
                    "code": "MS0001",
                    "sprint": "MS19",
                    "sheet": "FRCA",
                    "tags": "Motion",
                },
                memories[0]["metadata"],
            ],
        )

        with (
            patch.object(rag_engine.embedder, "encode", return_value=[[0.1, 0.2]]),

            patch.object(rag_engine.vector_store, "get_chunk_ids", return_value=["semantic-id", "keyword-id"]),
            patch.object(rag_engine.vector_store, "search", side_effect=fake_search),
            patch.object(rag_engine.vector_store, "list_memories", return_value=memories),
            patch.object(rag_engine.llm_client, "generate", side_effect=fake_generate),
            patch.object(rag_engine.settings, "rerank_enabled", False),
            patch.object(rag_engine.settings, "mmr_enabled", False),
            patch.object(rag_engine.settings, "keyword_recall_enabled", True),
        ):
            res = await self._run_answer(
                QueryRequest(
                    question="MS19 Copy line 4 issue",
                    filters=QueryFilters(sprints=["MS19"]),
                    top_k=1,
                )
            )

        self.assertEqual([c.chunk_id for c in res.citations], ["keyword-id"])
        self.assertEqual(res.debug.vector_candidate_count, 1)
        self.assertEqual(res.debug.keyword_candidate_count, 1)
        self.assertEqual(res.debug.candidate_count, 2)

    async def test_mmr_accepts_numpy_embeddings(self):
        def fake_search(query_embedding, top_k, where=None, include_embeddings=False, ids=None):
            return {
                "ids": [["first-id", "second-id"]],
                "documents": [["First issue.", "Second issue."]],
                "metadatas": [[
                    {
                        "doc_id": "doc-1",
                        "title": "MS0001_First",
                        "category": "MS",
                        "code": "MS0001",
                        "sprint": "MS19",
                        "tags": "Copy",
                    },
                    {
                        "doc_id": "doc-2",
                        "title": "MS0002_Second",
                        "category": "MS",
                        "code": "MS0002",
                        "sprint": "MS19",
                        "tags": "Copy",
                    },
                ]],
                "distances": [[0.1, 0.2]],
                "embeddings": [[np.array([0.1, 0.2]), np.array([0.2, 0.1])]],
            }

        async def fake_generate(prompt, model_type="default", **kwargs):
            return "MMR answer."

        collection = MatchingCollection(
            ["first-id", "second-id"],
            [
                {
                    "doc_id": "doc-1",
                    "title": "MS0001_First",
                    "category": "MS",
                    "code": "MS0001",
                    "sprint": "MS19",
                    "tags": "Copy",
                },
                {
                    "doc_id": "doc-2",
                    "title": "MS0002_Second",
                    "category": "MS",
                    "code": "MS0002",
                    "sprint": "MS19",
                    "tags": "Copy",
                },
            ],
        )

        with (
            patch.object(rag_engine.embedder, "encode", return_value=[[0.1, 0.2]]),

            patch.object(rag_engine.vector_store, "get_chunk_ids", return_value=["first-id", "second-id"]),
            patch.object(rag_engine.vector_store, "search", side_effect=fake_search),
            patch.object(rag_engine, "generate_search_synonyms", return_value=[]),
            patch.object(rag_engine.llm_client, "generate", side_effect=fake_generate),
            patch.object(rag_engine.settings, "rerank_enabled", False),
            patch.object(rag_engine.settings, "mmr_enabled", True),
            patch.object(rag_engine.settings, "mmr_lambda_default", 0.7),
            patch.object(rag_engine.settings, "keyword_recall_enabled", False),
        ):
            res = await self._run_answer(
                QueryRequest(
                    question="MS19 Copy issues",
                    filters=QueryFilters(sprints=["MS19"]),
                    top_k=1,
                )
            )

        self.assertEqual(len(res.citations), 1)
        self.assertTrue(res.debug.mmr_used)


if __name__ == "__main__":
    unittest.main()
