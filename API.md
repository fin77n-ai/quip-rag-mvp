# API Documentation

Complete API reference for Quip RAG System.

Reality check: this file reflects the live backend routes in `backend/api/*.py` as of 2026-06-10. Older notes that mention `POST /tags/feedback` or `GET /documents/{doc_id}` are stale.

**Base URL**: `http://localhost:8000`
**API Docs**: http://localhost:8000/docs (Swagger UI)

---

## Table of Contents

- [Data Input](#data-input)
- [Tag Management](#tag-management)
- [Batch Operations](#batch-operations)
- [Analytics](#analytics)
- [Health & Version](#health--version)
- [Document Management](#document-management)
- [Query](#query)
- [Rules & Taxonomy](#rules--taxonomy)

---

## Data Input

### Preview Files
Upload and preview JSON files before ingestion.

**Endpoint**: `POST /preprocess/preview`
**Content-Type**: `multipart/form-data`

**Request**:
```bash
curl -X POST http://localhost:8000/preprocess/preview \
  -F "files=@document.json"
```

**Response**:
```json
{
  "docs": [
    {
      "doc_id": "ABC123",
      "title": "Document Title",
      "sample_text": "...",
      "table_rows_count": 50,
      "qc": {
        "status": "pass",
        "issues": []
      }
    }
  ],
  "rules": { /* filter rules */ }
}
```

---

### Pull Quip Documents (SSE)
Pull documents from Quip with real-time progress updates.

**Endpoint**: `POST /preprocess/pull-quip`
**Content-Type**: `application/json`
**Response**: Server-Sent Events (SSE)

**Request**:
```bash
curl -X POST http://localhost:8000/preprocess/pull-quip \
  -H "Content-Type: application/json" \
  -d '{"urls": ["https://quip.com/thread-id"]}'
```

**SSE Events**:
```
event: start
data: {"total": 1}

event: progress
data: {"index": 1, "total": 1, "step": "fetching", "thread_id": "..."}

event: progress
data: {"index": 1, "total": 1, "step": "tagging", "title": "..."}

event: progress
data: {"index": 1, "total": 1, "step": "parsing", "thread_id": "..."}

event: progress
data: {"index": 1, "total": 1, "step": "ingesting", "thread_id": "..."}

event: doc_complete
data: {"index": 1, "total": 1, "doc": {...}, "chunks": 15}

event: complete
data: {"total": 1, "rules": {...}}
```

**Frontend Usage**:
```typescript
const response = await fetch('http://localhost:8000/preprocess/pull-quip', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ urls: ['...'] })
})

const reader = response.body.getReader()
// Parse SSE events...
```

---

## Tag Management

### List Known Tags
Get all unique tags from the system.

**Endpoint**: `GET /tags`

**Response**:
```json
{
  "category_tags": ["Translation", "Voice Over", "Animation"],
  "detail_tags": ["retake needed", "timing issue", "quality issue"]
}
```

---

### Get Document Tags
Get all tags for a specific document.

**Endpoint**: `GET /tags/{doc_id}`

**Response**:
```json
{
  "doc_id": "ABC123",
  "rows": {
    "ENUS::5": {
      "tags": ["Translation"],
      "category_tag": "Translation",
      "detail_tags": ["retake needed"],
      "confidence": 0.85,
      "excluded": false,
      "review_required": false,
      "rationale": "Clear retake requirement mentioned"
    }
  }
}
```

---

### Update Row Tag
Update tags for a specific row.

**Endpoint**: `PUT /tags/{doc_id}/row/{row_key}`
**Content-Type**: `application/json`

**Request**:
```json
{
  "category_tag": "Translation",
  "detail_tags": ["retake needed", "quality issue"],
  "confidence": 0.9,
  "excluded": false,
  "review_required": false,
  "rationale": "Updated by human reviewer"
}
```

**Response**: Full `DocTags` object

---

### Delete Row
Delete row from vector store and mark as excluded.

**Endpoint**: `DELETE /tags/{doc_id}/row/{row_key}`

**Response**:
```json
{
  "deleted": 3
}
```

**Notes**:
- Deletes all chunks for this row from vector store
- Marks row as `excluded: true` in tags
- Row won't appear in Review Queue
- `excluded` flag persists even if document is re-pulled

---

### Restore Row Chunk
Rebuild one row chunk from the saved Quip source JSON and reinsert it.

**Endpoint**: `POST /tags/{doc_id}/row/{row_key}/restore`

**Response**:
```json
{
  "restored": 1
}
```

**Notes**:
- Uses `data/sources/quip/{doc_id}.json` as the source of truth
- Re-parses the document and upserts only the target row chunk
- Successful restore clears `excluded: true` for that row

---

### Get Review Queue
Get rows requiring human review.

**Endpoint**: `GET /tags/review-queue`

**Response**:
```json
{
  "rows": [
    {
      "doc_id": "ABC123",
      "row_key": "ENUS::5",
      "title": "Document Title",
      "code": "VSD0123",
      "text": "Row content...",
      "category_tag": "Translation",
      "detail_tags": ["unclear"],
      "confidence": 0.65,
      "review_reason": "Low confidence",
      "context_before": [
        {"row_key": "ENUS::4", "text": "..."}
      ],
      "context_after": [
        {"row_key": "ENUS::6", "text": "..."}
      ]
    }
  ]
}
```

---

### Distill Feedback
Analyze feedback and generate reusable rules.

**Endpoint**: `POST /tags/feedback/distill`

**Response**:
```json
{
  "rules": [
    "When rows were previously tagged as Translation, reviewers often corrected them to Voice Over (15 times)."
  ],
  "examples": [
    {
      "row_id": "ABC123::ENUS::5",
      "from": "Translation",
      "to": "Voice Over",
      "detail_tags": ["retake needed"],
      "note": "..."
    }
  ],
  "total_feedback": 74
}
```

**Current Behavior Notes**:
- Active tag-review feedback is recorded implicitly through `PUT /tags/{doc_id}/row/{row_key}`.
- `POST /tags/feedback/distill` reads `data/feedback/tag_feedback.jsonl` and writes `data/feedback/tag_feedback_distilled.json`.
- The distilled file is now injected into auto-tagging prompts as compact guidance.
- It is still not an automatically enforced hard runtime ruleset.

---

## Batch Operations

### Batch Delete Rows
Delete multiple rows in one request.

**Endpoint**: `POST /tags/batch-delete`
**Content-Type**: `application/json`

**Request**:
```json
{
  "items": [
    {"doc_id": "ABC123", "row_key": "ENUS::5"},
    {"doc_id": "ABC123", "row_key": "ENUS::6"},
    {"doc_id": "DEF456", "row_key": "DEDE::3"}
  ]
}
```

**Response**:
```json
{
  "total": 3,
  "deleted": 7,
  "failed": [
    {
      "doc_id": "DEF456",
      "row_key": "DEDE::3",
      "reason": "Row not found"
    }
  ]
}
```

**Notes**:
- `deleted` is total number of chunks deleted (multiple chunks per row)
- Failed items include reason
- Successful deletes are marked `excluded: true`

---

### Batch Update Tags
Update tags for multiple rows in one request.

**Endpoint**: `POST /tags/batch-update`
**Content-Type**: `application/json`

**Request**:
```json
{
  "items": [
    {
      "doc_id": "ABC123",
      "row_key": "ENUS::5",
      "tag": {
        "category_tag": "Translation",
        "detail_tags": ["retake needed"],
        "confidence": 0.9
      }
    }
  ]
}
```

**Response**:
```json
{
  "total": 1,
  "updated": 1,
  "failed": []
}
```

---

## Analytics

### Get System Statistics
Get overall system statistics.

**Endpoint**: `GET /analytics/stats`

**Response**:
```json
{
  "total_docs": 5,
  "total_chunks": 225,
  "total_rows": 450,
  "review_required": 49,
  "excluded_rows": 24,
  "avg_confidence": 0.78,
  "categories": {
    "Translation": 180,
    "Voice Over": 120,
    "Animation": 150
  },
  "sprints": {
    "2026-W23": 100,
    "2026-W24": 125
  }
}
```

---

### Get Tag Distribution
Get tag distribution and confidence buckets.

**Endpoint**: `GET /analytics/tag-distribution`

**Response**:
```json
{
  "category_tags": {
    "Translation": 180,
    "Voice Over": 120,
    "Animation": 150
  },
  "detail_tags": {
    "retake needed": 45,
    "quality issue": 32,
    "timing issue": 28
  },
  "confidence_buckets": {
    "0.0-0.3": 5,
    "0.3-0.5": 12,
    "0.5-0.7": 38,
    "0.7-0.9": 125,
    "0.9-1.0": 270
  }
}
```

---

## Health & Version

### Health Check
Check system health and service status.

**Endpoint**: `GET /health`

**Response**:
```json
{
  "status": "healthy",
  "timestamp": "2026-06-10T03:00:00.000000",
  "services": {
    "vector_store": "ok (225 chunks)"
  }
}
```

**Status Values**:
- `healthy`: All services OK
- `degraded`: Some services have issues

---

### Get Version
Get system version information.

**Endpoint**: `GET /version`

**Response**:
```json
{
  "version": "1.0.0",
  "python_version": "3.13.0",
  "environment": "development"
}
```

---

## Document Management

### List Documents
List all documents with optional filters.

**Endpoint**: `GET /documents?category={category}&sprint={sprint}`

**Query Parameters**:
- `category` (optional): Filter by category (e.g., "VSD")
- `sprint` (optional): Filter by sprint (e.g., "2026-W23")

**Response**:
```json
{
  "docs": [
    {
      "doc_id": "ABC123",
      "title": "VSD0123_Document Title",
      "code": "VSD0123",
      "category": "VSD",
      "sprint": "2026-W23",
      "chunk_count": 15,
      "word_count": 1250
    }
  ]
}
```

---

### Delete Document
Delete entire document from system.

**Endpoint**: `DELETE /documents/{doc_id}`

**Response**:
```json
{
  "deleted": "ABC123"
}
```

**Notes**:
- Deletes all chunks from vector store
- Also deletes auxiliary DuckDB/Lance rows when enabled

---

### Update Document Metadata
Update document category or sprint.

**Endpoint**: `PATCH /documents/{doc_id}`
**Content-Type**: `application/json`

**Request**:
```json
{
  "category": "VSD",
  "sprint": "2026-W24"
}
```

**Response**:
```json
{
  "updated_chunks": 15
}
```

---

### Get Document Chunks
Get all chunks for a document.

**Endpoint**: `GET /documents/{doc_id}/chunks`

**Response**:
```json
{
  "chunks": [
    {
      "chunk_id": "ABC123::190",
      "text": "Chunk content...",
      "metadata": {
        "row_key": "ENUS::5",
        "sheet": "ENUS",
        "category_tag": "Translation",
        "detail_tags": "retake needed",
        "confidence": 0.85
      }
    }
  ]
}
```

---

### List Sprints
Get all unique sprints in the system.

**Endpoint**: `GET /documents/sprints`

**Response**:
```json
{
  "sprints": ["2026-W23", "2026-W24", "2026-W25"]
}
```

---

## Query

### RAG Query
Semantic search with optional filters.

**Endpoint**: `POST /query`
**Content-Type**: `application/json`

**Request**:
```json
{
  "question": "What are the translation issues in German?",
  "filters": {
    "categories": ["VSD"],
    "sprints": ["2026-W23"],
    "tags": ["Translation"]
  },
  "top_k": 12,
  "mmr_lambda": 0.7,
  "qc_enabled": true
}
```

**Response**:
```json
{
  "answer": "Generated answer based on retrieved chunks...",
  "citations": [],
  "evidence_groups": [],
  "debug": {
    "route": "single",
    "intent": "issue_lookup",
    "candidate_count": 12,
    "group_count": 4
  },
  "qc": {
    "status": "pass",
    "issues": []
  }
}
```

**Parameters**:
- `question`: Query text
- `filters.categories`: Filter by document categories
- `filters.sprints`: Filter by sprints
- `filters.tags`: Filter by category/detail tags
- `top_k`: Number of results (default: 12)
- `mmr_lambda`: MMR diversity parameter 0-1 (default: 0.7)
- `qc_enabled`: Enable quality checks (default: true)

---

## Rules & Taxonomy

### Get Filter Rules
Get current parsing filter rules.

**Endpoint**: `GET /rules`

**Response**:
```json
{
  "exclude_sheets": ["Glossary", "Legend"],
  "exclude_columns": ["Notes", "Internal"],
  "include_columns": [],
  "exclude_row_patterns": ["^\\s*$"],
  "exclude_section_headings": ["Archive"],
  "placeholder_chars": ["—", "–", "N/A"],
  "drop_empty_rows": true,
  "min_chunk_chars": 10
}
```

---

### Update Filter Rules
Update parsing filter rules.

**Endpoint**: `POST /rules`
**Content-Type**: `application/json`

**Request**: Same as GET response

**Response**: Updated rules

---

### Reset Filter Rules
Reset rules to system defaults.

**Endpoint**: `POST /rules/reset`

**Response**: Default rules

---

### Get Taxonomy
Get current taxonomy tree.

**Endpoint**: `GET /taxonomy`

**Response**:
```json
{
  "categories": {
    "Translation": {
      "subcategories": ["Retake", "Quality"],
      "tags": ["retake needed", "quality issue"]
    }
  }
}
```

### Taxonomy Feedback

These routes exist in the live backend, but are not currently part of the active wrapped frontend flow:

- `POST /taxonomy/feedback`
- `POST /taxonomy/feedback/apply-similar`
- `GET /taxonomy/feedback/metrics`

Taxonomy feedback is the structured feedback source currently used by `backend/services/feedback_retriever.py` for dynamic few-shot prompt injection during auto-tagging.

## Frontend Wrapping Status

- Wrapped in `frontend/src/api/client.ts`: 28 exported helpers
- Active screens mostly consume only `client.ts`
- Quip pull SSE is wrapped through `streamPullQuipDocs(...)` in `frontend/src/api/client.ts`
- Live backend routes with no active wrapper/helper in `client.ts` include:
  - `/preprocess/preview-with-rules`
  - `/ingest/parse`
  - `/ingest/batches/{batch_id}`
  - `/ingest/approve`
  - `/query/compare`
  - most `/taxonomy/*` mutation routes

## Current Pipeline

```text
Pull / preview
  -> parse Quip rows using rules
  -> auto_tagger classifies rows
     using relevant taxonomy feedback examples from DuckDB as prompt context
  -> low-confidence rows enter review queue
  -> human review edits row tag, review flags, and feedback note
  -> Save review:
       persists row tag + feedback history
     Save + sync chunk:
       persists row tag, resolves review_required=false, rebuilds one row chunk from saved source JSON
  -> query pipeline:
       retrieve -> rerank/MMR -> answer -> QC
```

---

## Error Responses

All endpoints return standard error format:

**400 Bad Request**:
```json
{
  "detail": "Invalid request parameters"
}
```

**404 Not Found**:
```json
{
  "detail": "Document not found"
}
```

**500 Internal Server Error**:
```json
{
  "detail": "Internal server error: <error message>"
}
```

---

## Rate Limits

- No rate limits for local development
- Production: TBD

---

## Authentication

- Local development: No authentication required
- Production: TBD (OAuth2 / API Key)

---

**Last Updated**: June 10, 2026
**API Version**: 1.0.0
