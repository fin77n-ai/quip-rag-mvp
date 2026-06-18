import { demoQuery, demoRequest, runDemoPull } from './demo'

const BASE = ''
export const DEMO_MODE = import.meta.env.VITE_DEMO_MODE !== 'false'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  if (DEMO_MODE) return demoRequest<T>(path, init)
  const res = await fetch(BASE + path, init)
  if (!res.ok) throw new Error(await res.text())
  return res.json() as Promise<T>
}

function json<T>(path: string, method: string, body?: unknown): Promise<T> {
  return request<T>(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export interface QCIssue {
  severity: 'info' | 'warning' | 'error'
  type: string
  message: string
  ref?: string
}

export interface QCReport {
  stage: string
  status: 'pass' | 'warning' | 'fail'
  summary: string
  issues: QCIssue[]
  metrics: Record<string, unknown>
}

export interface RowTag {
  tags: string[]
  excluded: boolean
  is_noise: boolean
  category_tag: string
  detail_tags: string[]
  confidence: number
  rationale: string
  review_required: boolean
  review_reason: string
  feedback_note: string
  is_issue?: string
  issue_summary?: string
  issue_type?: string
  owner?: string
  status?: string
  issue_source?: string
}

export interface DocTags {
  doc_id: string
  rows: Record<string, RowTag>
}

export interface FilterRules {
  exclude_sheets: string[]
  exclude_columns: string[]
  include_columns: string[]
  exclude_row_patterns: string[]
  exclude_section_headings: string[]
  placeholder_chars: string[]
  drop_empty_rows: boolean
  min_chunk_chars: number
}

export interface SheetStat {
  sheet: string
  kept: boolean
  reason?: string
  rows_total?: number
  rows_kept?: number
  rows_dropped?: number
  cols_dropped?: number
}

export interface PreviewDoc {
  doc_id: string
  title: string
  stats?: { sheet_breakdown: SheetStat[]; sections_kept: number }
  sections_count?: number
  table_rows_count?: number
  total_chars?: number
  sample_text?: string
  error?: string
  qc?: QCReport
}

export interface DocSummary {
  doc_id: string
  title: string
  code: string
  prefix: string
  word_count: number
}

export interface DocSummaryRow {
  doc_id: string
  title: string
  code: string
  category: string
  sprint: string
  chunk_count: number
  last_processed_at: string
}

export interface ReprocessDocumentResult {
  doc_id: string
  chunks: number
  issue_rows: number
  excluded_rows: number
  source_path: string
}

export interface ReprocessAllDocumentsResult {
  total_sources: number
  reprocessed: number
  failed: Array<{ doc_id: string; reason: string }>
  docs: ReprocessDocumentResult[]
}

export interface ReprocessAllStartEvent {
  total: number
}

export interface ReprocessAllProgressEvent {
  index: number
  total: number
  doc_id: string
  stage: string
}

export interface ReprocessAllDocCompleteEvent {
  index: number
  total: number
  processed: number
  failed: number
  doc: ReprocessDocumentResult
}

export interface ReprocessAllErrorEvent {
  index: number
  total: number
  processed: number
  failed: number
  doc_id: string
  reason: string
}

export interface ReprocessAllStreamHandlers {
  onStart?: (event: ReprocessAllStartEvent) => void
  onProgress?: (event: ReprocessAllProgressEvent) => void
  onDocComplete?: (event: ReprocessAllDocCompleteEvent) => void
  onError?: (event: ReprocessAllErrorEvent) => void
  onComplete?: (event: ReprocessAllDocumentsResult) => void
}

export interface ChunkView {
  chunk_id: string
  text: string
  metadata: Record<string, string | number>
}

export interface Stats {
  total_chunks: number
  total_docs: number
  by_category: Record<string, number>
  by_sprint: Record<string, number>
  by_tag: Record<string, number>
  embedding_model: string
}

export interface Citation {
  chunk_id: string
  doc_id: string
  title: string
  category: string
  code: string
  sprint: string
  snippet: string
  score: number
  group_id: string
  is_representative: boolean
  sibling_count: number
}

export interface SimilarEvidenceGroup {
  group_id: string
  label: string
  count: number
  representative: Citation
  supporting: Citation[]
}

export interface QueryDebug {
  route: string
  intent: string
  candidate_count: number
  group_count: number
}

export interface QueryMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface QueryResponse {
  answer: string
  citations: Citation[]
  elapsed_ms: number
  evidence_groups: SimilarEvidenceGroup[]
  qc?: QCReport | null
  debug: QueryDebug
}

export interface ReviewQueueRow {
  doc_id: string
  row_key: string
  title: string
  code: string
  sprint: string
  category: string
  category_tag: string
  detail_tags: string[]
  confidence: number
  review_reason: string
  rationale: string
  tags: string[]
  is_noise?: boolean
  text: string
  context_before: Array<{ row_key: string; text: string }>
  context_after: Array<{ row_key: string; text: string }>
}

export interface DistilledFeedback {
  rules: string[]
  examples: Array<{ row_id: string; from: string; to: string; detail_tags: string[]; note: string }>
  total_feedback: number
}

export interface TagCandidate {
  tag: string
  count: number
  categories: Record<string, number>
}

export interface TagTaxonomy {
  categories: Record<string, string[]>
  candidates: TagCandidate[]
}

export interface DetailTagMergeResponse {
  updated_rows: number
  synced_chunks: number
}

export interface KnownTagsResponse {
  tags: string[]
  detail_tags: string[]
  active_detail_tags_count: number
  loose_detail_tags_count: number
}

export interface PullQuipStartEvent {
  total: number
}

export interface PullQuipProgressEvent {
  index: number
  total: number
  step: string
  thread_id?: string
  title?: string
}

export interface PullQuipDocCompleteEvent {
  index: number
  total: number
  doc: PreviewDoc
  chunks: number
}

export interface PullQuipCompleteEvent {
  total: number
  rules: FilterRules
}

export interface PullQuipErrorEvent {
  index?: number
  total?: number
  thread_id?: string
  error: string
}

export interface PullQuipStreamHandlers {
  onStart?: (event: PullQuipStartEvent) => void
  onProgress?: (event: PullQuipProgressEvent) => void
  onDocComplete?: (event: PullQuipDocCompleteEvent) => void
  onComplete?: (event: PullQuipCompleteEvent) => void
  onError?: (event: PullQuipErrorEvent) => void
}

export async function parseFiles(files: File[]) {
  const fd = new FormData()
  files.forEach(file => fd.append('files', file))
  return request<{ batch_id: string; docs: DocSummary[] }>('/ingest/parse', { method: 'POST', body: fd })
}

export async function approveBatch(batchId: string, docIds?: string[]) {
  return json<{ ingested: number; failed: { doc_id: string; reason: string }[] }>('/ingest/approve', 'POST', {
    batch_id: batchId,
    doc_ids: docIds,
  })
}

export async function getRules() {
  return request<FilterRules>('/rules')
}

export async function saveRules(rules: FilterRules) {
  return json<FilterRules>('/rules', 'POST', rules)
}

export async function resetRules() {
  return json<FilterRules>('/rules/reset', 'POST', {})
}

export async function previewFiles(files: File[]) {
  const fd = new FormData()
  files.forEach(file => fd.append('files', file))
  return request<{ docs: PreviewDoc[]; rules: FilterRules }>('/preprocess/preview', { method: 'POST', body: fd })
}

export async function pullQuipDocs(urls: string[]) {
  return json<{ docs: PreviewDoc[]; rules: FilterRules }>('/preprocess/pull-quip', 'POST', { urls })
}

export async function streamPullQuipDocs(
  urls: string[],
  sprint: string | undefined,
  handlers: PullQuipStreamHandlers = {},
  signal?: AbortSignal,
) {
  if (DEMO_MODE) {
    await runDemoPull(urls, handlers)
    return
  }
  const response = await fetch(`${BASE}/preprocess/pull-quip`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ urls, sprint }),
    signal,
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  const reader = response.body?.getReader()
  const decoder = new TextDecoder()
  if (!reader) {
    throw new Error('No response body')
  }

  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''

    for (const rawEvent of events) {
      if (!rawEvent.trim()) continue

      let eventType = 'message'
      let data = ''
      for (const line of rawEvent.split('\n')) {
        if (line.startsWith('event:')) {
          eventType = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          data = line.slice(5).trim()
        }
      }

      if (!data) continue
      const parsed = JSON.parse(data)

      if (eventType === 'start') {
        handlers.onStart?.(parsed as PullQuipStartEvent)
      } else if (eventType === 'progress') {
        handlers.onProgress?.(parsed as PullQuipProgressEvent)
      } else if (eventType === 'doc_complete') {
        handlers.onDocComplete?.(parsed as PullQuipDocCompleteEvent)
      } else if (eventType === 'complete') {
        handlers.onComplete?.(parsed as PullQuipCompleteEvent)
      } else if (eventType === 'error') {
        const errorEvent = parsed as PullQuipErrorEvent
        handlers.onError?.(errorEvent)
        await reader.cancel()
        throw new Error(errorEvent.error)
      }
    }
  }
}

export async function getDocTags(docId: string) {
  return request<DocTags>(`/tags/${docId}`)
}

export async function deleteRowChunk(docId: string, rowKey: string) {
  return request<{ deleted: number }>(`/tags/${encodeURIComponent(docId)}/row/${encodeURIComponent(rowKey)}`, {
    method: 'DELETE',
  })
}

export async function archiveRowAsNoise(docId: string, rowKey: string) {
  return request<{ archived: number }>(`/tags/${encodeURIComponent(docId)}/row/${encodeURIComponent(rowKey)}/noise`, {
    method: 'POST',
  })
}

export async function restoreRowChunk(docId: string, rowKey: string) {
  return request<{ restored: number }>(`/tags/${encodeURIComponent(docId)}/row/${encodeURIComponent(rowKey)}/restore`, {
    method: 'POST',
  })
}

export async function setRowTag(docId: string, key: string, tag: RowTag) {
  return json<DocTags>(`/tags/${docId}/row/${encodeURIComponent(key)}`, 'PUT', tag)
}

export async function getKnownTags() {
  return request<KnownTagsResponse>('/tags')
}

export async function getTagTaxonomy() {
  return request<TagTaxonomy>('/tags/taxonomy')
}

export async function mergeDetailTag(fromTag: string, toTag: string, category: string) {
  return json<DetailTagMergeResponse>('/tags/detail-tags/merge', 'POST', {
    from_tag: fromTag,
    to_tag: toTag,
    category,
  })
}

export async function getReviewQueue() {
  return request<{ rows: ReviewQueueRow[] }>('/tags/review-queue')
}

export async function getNoiseRows() {
  return request<{ rows: ReviewQueueRow[] }>('/tags/noise')
}

export async function distillTagFeedback() {
  return json<DistilledFeedback>('/tags/feedback/distill', 'POST', {})
}

export async function getStats() {
  return request<Stats>('/documents/stats')
}

export async function getSprints() {
  return request<{ sprints: string[] }>('/documents/sprints')
}

export async function listDocuments(category?: string, sprint?: string) {
  const params = new URLSearchParams()
  if (category) params.set('category', category)
  if (sprint) params.set('sprint', sprint)
  const suffix = params.toString() ? `?${params}` : ''
  return request<{ docs: DocSummaryRow[] }>(`/documents${suffix}`)
}

export async function deleteDocument(docId: string) {
  return request<{ deleted: string }>(`/documents/${docId}`, { method: 'DELETE' })
}

export async function getDocChunks(docId: string) {
  return request<{ chunks: ChunkView[] }>(`/documents/${docId}/chunks`)
}

export async function patchDocMetadata(docId: string, body: { category?: string; sprint?: string }) {
  return json<{ updated_chunks: number }>(`/documents/${docId}`, 'PATCH', body)
}

export async function reprocessDocument(docId: string) {
  return request<ReprocessDocumentResult>(`/documents/${docId}/reprocess`, { method: 'POST' })
}

export async function reprocessAllDocuments() {
  return request<ReprocessAllDocumentsResult>('/documents/reprocess-all', { method: 'POST' })
}

export async function streamReprocessAllDocuments(docIds?: string[], handlers: ReprocessAllStreamHandlers = {}) {
  if (DEMO_MODE) {
    const ids = docIds?.length ? docIds : ['demo-launch-2025-q4', 'demo-onboarding-2026-q1', 'demo-feature-2026-q2']
    handlers.onStart?.({ total: ids.length })
    const docs: ReprocessDocumentResult[] = []
    for (const [index, docId] of ids.entries()) {
      handlers.onProgress?.({ index: index + 1, total: ids.length, doc_id: docId, stage: 'auto-tagging' })
      const doc = await demoRequest<ReprocessDocumentResult>(`/documents/${docId}/reprocess`, { method: 'POST' })
      docs.push({ ...doc, doc_id: docId })
      handlers.onDocComplete?.({ index: index + 1, total: ids.length, processed: docs.length, failed: 0, doc: docs[docs.length - 1] })
    }
    handlers.onComplete?.({ total_sources: ids.length, reprocessed: docs.length, failed: [], docs })
    return
  }
  const response = await fetch(`${BASE}/documents/reprocess-all/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(docIds ? { doc_ids: docIds } : {}),
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}`)
  }

  const reader = response.body?.getReader()
  const decoder = new TextDecoder()
  if (!reader) {
    throw new Error('No response body')
  }

  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const events = buffer.split('\n\n')
    buffer = events.pop() || ''

    for (const rawEvent of events) {
      if (!rawEvent.trim()) continue

      let eventType = 'message'
      let data = ''
      for (const line of rawEvent.split('\n')) {
        if (line.startsWith('event:')) {
          eventType = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          data = line.slice(5).trim()
        }
      }

      if (!data) continue
      const parsed = JSON.parse(data)

      if (eventType === 'start') {
        handlers.onStart?.(parsed as ReprocessAllStartEvent)
      } else if (eventType === 'progress') {
        handlers.onProgress?.(parsed as ReprocessAllProgressEvent)
      } else if (eventType === 'doc_complete') {
        handlers.onDocComplete?.(parsed as ReprocessAllDocCompleteEvent)
      } else if (eventType === 'error') {
        handlers.onError?.(parsed as ReprocessAllErrorEvent)
      } else if (eventType === 'complete') {
        handlers.onComplete?.(parsed as ReprocessAllDocumentsResult)
      }
    }
  }
}

export async function queryRAG(
  question: string,
  filters: { categories?: string[]; sprints?: string[]; tags?: string[] },
  history: QueryMessage[] = [],
  topK = 12,
  mmrLambda?: number,
  onChunk?: (chunk: any) => void
): Promise<QueryResponse> {
  if (DEMO_MODE) {
    onChunk?.({ type: 'status', message: 'Searching synthetic evidence...' })
    return demoQuery(question) as Promise<QueryResponse>
  }
  const response = await fetch(`${BASE}/query`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      question,
      history,
      filters,
      top_k: topK,
      mmr_lambda: mmrLambda,
      qc_enabled: true,
    }),
  })

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${await response.text()}`)
  }

  const reader = response.body?.getReader()
  const decoder = new TextDecoder()
  if (!reader) {
    throw new Error('No response body')
  }

  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (!line.trim()) continue
      try {
        const parsed = JSON.parse(line)
        if (onChunk) onChunk(parsed)
        if (parsed.type === 'error') {
          throw new Error(parsed.detail || parsed.message || 'Query stream failed')
        }
        if (parsed.type === 'result') {
          return parsed.data as QueryResponse
        }
      } catch (e) {
        console.error('Failed to parse line:', line, e)
      }
    }
  }

  if (buffer.trim()) {
    try {
      const parsed = JSON.parse(buffer)
      if (onChunk) onChunk(parsed)
      if (parsed.type === 'error') {
        throw new Error(parsed.detail || parsed.message || 'Query stream failed')
      }
      if (parsed.type === 'result') {
        return parsed.data as QueryResponse
      }
    } catch (e) {
      console.error('Failed to parse final line:', buffer, e)
    }
  }

  throw new Error('Stream ended without a result chunk')
}

// === Batch Operations ===

export interface BatchDeleteRequest {
  items: Array<{ doc_id: string; row_key: string }>
}

export interface BatchDeleteResponse {
  total: number
  deleted: number
  failed: Array<{ doc_id: string; row_key: string; reason: string }>
}

export async function batchDeleteRows(items: Array<{ doc_id: string; row_key: string }>): Promise<BatchDeleteResponse> {
  return json('/tags/batch-delete', 'POST', { items })
}

export interface BatchUpdateRequest {
  items: Array<{ doc_id: string; row_key: string; tag: RowTag }>
}

export interface BatchUpdateResponse {
  total: number
  updated: number
  failed: Array<{ doc_id: string; row_key: string; reason: string }>
}

export async function batchUpdateTags(items: Array<{ doc_id: string; row_key: string; tag: RowTag }>): Promise<BatchUpdateResponse> {
  return json('/tags/batch-update', 'POST', { items })
}

// === Analytics ===

export interface StatsResponse {
  total_docs: number
  total_chunks: number
  total_rows: number
  review_required: number
  excluded_rows: number
  avg_confidence: number
  categories: Record<string, number>
  sprints: Record<string, number>
}

export async function getAnalyticsStats(): Promise<StatsResponse> {
  return json('/analytics/stats', 'GET')
}

export interface TagDistribution {
  category_tags: Record<string, number>
  detail_tags: Record<string, number>
  confidence_buckets: Record<string, number>
}

export async function getTagDistribution(): Promise<TagDistribution> {
  return json('/analytics/tag-distribution', 'GET')
}

// === Health & Version ===

export interface HealthResponse {
  status: string
  timestamp: string
  services: Record<string, string>
}

export async function getHealth(): Promise<HealthResponse> {
  return json('/health', 'GET')
}

export interface VersionResponse {
  version: string
  python_version: string
  environment: string
}

export interface SprintTrend {
  sprint: string
  total_issues: number
  languages: Record<string, number>
  sources: Record<string, number>
  categories: Record<string, number>
  review_required: number
  auto_resolved: number
}

export interface VideoStat {
  video_name: string
  total_issues: number
  vendors?: Array<{
    vendor: string;
    issues: number;
    fill: string;
    categories?: Array<{ name: string; value: number; parent?: string }>
  }>
  languages?: Array<{
    language: string;
    issues: number;
    fill: string;
    categories?: Array<{ name: string; value: number; parent?: string }>
  }>
}

export interface VendorCategoryStat {
  vendor: string
  sprint?: string
  Translation?: number
  Animation?: number
  'Voice Over'?: number
  Source?: number
}

export async function getSprintTrends() {
  const [overallRes, videosRes, vendorsRes] = await Promise.all([
    request<any>('/analytics/dashboard/overall').catch(() => ({ trends: [] })),
    request<{ videos: VideoStat[] }>('/analytics/dashboard/videos').catch(() => ({ videos: [] })),
    request<{ overall: VendorCategoryStat[]; by_sprint: VendorCategoryStat[] }>('/analytics/dashboard/vendors').catch(() => ({ overall: [], by_sprint: [] })),
  ])

  // Transform backend's array format into the Record<string, number> format the frontend expects
  const trends: SprintTrend[] = (overallRes.trends || []).map((t: any) => {
    const sourcesRecord: Record<string, number> = {}
    const categoriesRecord: Record<string, number> = {}

    if (Array.isArray(t.sources)) {
      t.sources.forEach((s: any) => { sourcesRecord[s.name] = s.value })
    }

    if (Array.isArray(t.categories)) {
      t.categories.forEach((c: any) => { categoriesRecord[c.name] = c.value })
    }

    return {
      ...t,
      sources: Object.keys(sourcesRecord).length > 0 ? sourcesRecord : t.sources,
      categories: Object.keys(categoriesRecord).length > 0 ? categoriesRecord : t.categories
    }
  })

  return {
    trends,
    videos: videosRes.videos || [],
    vendors: vendorsRes,
  }
}
