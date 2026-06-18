const wait = (ms = 180) => new Promise(resolve => window.setTimeout(resolve, ms))

const rules = {
  exclude_sheets: ['Archive', 'Instructions'],
  exclude_columns: ['Last edited by', 'Internal notes'],
  include_columns: ['Project', 'Locale', 'Issue', 'Owner', 'Status'],
  exclude_row_patterns: ['^N/A$', '^No issues$'],
  exclude_section_headings: ['Reference only'],
  placeholder_chars: ['-', '/', 'TBD'],
  drop_empty_rows: true,
  min_chunk_chars: 18,
}

const rowTags = {
  'row-014': {
    tags: ['subtitle', 'timing'], excluded: false, is_noise: false,
    category_tag: 'Translation', detail_tags: ['subtitle timing', 'reading speed'], confidence: 0.72,
    rationale: 'The note mentions captions ending before the spoken line.', review_required: true,
    review_reason: 'Translation and animation signals overlap.', feedback_note: '', is_issue: 'yes',
    issue_summary: 'French captions disappear before narration ends', issue_type: 'Timing',
    owner: 'Mira Chen', status: 'In progress', issue_source: 'QA review',
  },
  'row-027': {
    tags: ['voice-over', 'sync'], excluded: false, is_noise: false,
    category_tag: 'Voice Over', detail_tags: ['lip sync', 'audio drift'], confidence: 0.64,
    rationale: 'The report describes a mismatch between narration and on-screen action.', review_required: true,
    review_reason: 'Could be source animation timing rather than localized audio.', feedback_note: '', is_issue: 'yes',
    issue_summary: 'Japanese narration drifts after the chapter transition', issue_type: 'Sync',
    owner: 'Noah Park', status: 'Needs review', issue_source: 'Vendor handoff',
  },
  'row-041': {
    tags: ['source', 'overlay'], excluded: false, is_noise: false,
    category_tag: 'Source', detail_tags: ['missing asset', 'text overlay'], confidence: 0.58,
    rationale: 'The localized file is missing an overlay present in the master.', review_required: true,
    review_reason: 'The original note uses the legacy field name asset gap.', feedback_note: '', is_issue: 'yes',
    issue_summary: 'German export is missing the final legal overlay', issue_type: 'Missing asset',
    owner: 'Ari Singh', status: 'Open', issue_source: 'Final QC',
  },
}

const documents = [
  { doc_id: 'demo-launch-2025-q4', title: 'Product Launch Series Q4', code: 'PLS-Q4', category: 'Campaign', sprint: '2025 Q4', chunk_count: 96, last_processed_at: '2026-01-08T09:40:00Z' },
  { doc_id: 'demo-onboarding-2026-q1', title: 'Customer Onboarding Q1', code: 'ONB-Q1', category: 'Education', sprint: '2026 Q1', chunk_count: 82, last_processed_at: '2026-04-03T11:20:00Z' },
  { doc_id: 'demo-feature-2026-q2', title: 'Feature Stories Q2', code: 'FST-Q2', category: 'Campaign', sprint: '2026 Q2', chunk_count: 71, last_processed_at: '2026-06-16T06:15:00Z' },
]

const reviews = Object.entries(rowTags).map(([row_key, tag], index) => ({
  doc_id: documents[index].doc_id,
  row_key,
  title: documents[index].title,
  code: documents[index].code,
  sprint: documents[index].sprint,
  category: documents[index].category,
  category_tag: tag.category_tag,
  detail_tags: tag.detail_tags,
  confidence: tag.confidence,
  review_reason: tag.review_reason,
  rationale: tag.rationale,
  tags: tag.tags,
  text: tag.issue_summary,
  context_before: [{ row_key: `before-${index}`, text: 'Locale owner confirmed the latest master was used.' }],
  context_after: [{ row_key: `after-${index}`, text: `Follow-up: ${tag.owner} is validating the proposed fix.` }],
}))

export const demoDashboard = {
  trends: [
    ['2025 Q1', 42, 7, 24, 10, 5, 3], ['2025 Q2', 55, 8, 31, 12, 7, 5],
    ['2025 Q3', 48, 6, 25, 11, 8, 4], ['2025 Q4', 67, 10, 35, 15, 9, 8],
    ['2026 Q1', 59, 7, 29, 13, 10, 7], ['2026 Q2', 44, 5, 20, 9, 8, 7],
  ].map(([sprint, total, review, translation, animation, voice, source]) => ({
    sprint, total_issues: total, review_required: review, auto_resolved: Number(total) - Number(review),
    languages: { French: 13, German: 11, Japanese: 9, Spanish: 8 },
    sources: { Northstar: Math.round(Number(total) * .44), BluePeak: Math.round(Number(total) * .34), InHouse: Math.round(Number(total) * .22) },
    categories: { Translation: translation, Animation: animation, 'Voice Over': voice, Source: source },
  })),
  videos: [
    { video_name: 'Launch Story 07', total_issues: 31, vendors: [{ vendor: 'Northstar', issues: 14, fill: '#10b981' }, { vendor: 'BluePeak', issues: 10, fill: '#34d399' }, { vendor: 'InHouse', issues: 7, fill: '#6ee7b7' }], languages: [{ language: 'French', issues: 10, fill: '#10b981' }, { language: 'German', issues: 8, fill: '#34d399' }, { language: 'Japanese', issues: 7, fill: '#6ee7b7' }] },
    { video_name: 'Onboarding Chapter 03', total_issues: 24, vendors: [{ vendor: 'BluePeak', issues: 12, fill: '#10b981' }, { vendor: 'Northstar', issues: 8, fill: '#34d399' }, { vendor: 'InHouse', issues: 4, fill: '#6ee7b7' }], languages: [{ language: 'Japanese', issues: 9, fill: '#10b981' }, { language: 'French', issues: 8, fill: '#34d399' }, { language: 'Spanish', issues: 7, fill: '#6ee7b7' }] },
  ],
  vendors: {
    overall: [
      { vendor: 'Northstar', Translation: 62, Animation: 25, 'Voice Over': 18, Source: 11 },
      { vendor: 'BluePeak', Translation: 49, Animation: 22, 'Voice Over': 21, Source: 9 },
      { vendor: 'InHouse', Translation: 31, Animation: 13, 'Voice Over': 11, Source: 10 },
    ],
    by_sprint: [
      { vendor: 'Northstar', sprint: '2026 Q2', Translation: 9, Animation: 4, 'Voice Over': 3, Source: 2 },
      { vendor: 'BluePeak', sprint: '2026 Q2', Translation: 7, Animation: 3, 'Voice Over': 4, Source: 2 },
      { vendor: 'InHouse', sprint: '2026 Q2', Translation: 4, Animation: 2, 'Voice Over': 1, Source: 3 },
    ],
  },
}

export async function demoQuery(question: string) {
  await wait(520)
  const asksAboutTrend = /trend|repeat|recurr|pattern|why|increase|decrease/i.test(question)
  const answer = asksAboutTrend
    ? '**Subtitle timing is the clearest recurring pattern.** It peaked in 2025 Q4, then fell 43% after the team added a preflight reading-speed check.\n\nThe remaining cases cluster in French and Japanese, mostly around late script changes. I would follow up with Northstar on the two open timing issues and keep the preflight rule in the next sprint.'
    : '**Three issues need project-manager attention.** Two are blocked on source confirmation and one needs the category corrected before it can be included in the vendor trend.\n\nThe strongest next action is to resolve the Japanese sync case first because it affects both delivery status and the current vendor comparison.'
  const citations = reviews.slice(0, 3).map((row, index) => ({
    chunk_id: `chunk-${index + 1}`, doc_id: row.doc_id, title: row.title, category: row.category,
    code: row.code, sprint: row.sprint, snippet: row.text, score: .94 - index * .06,
    group_id: index === 2 ? 'source-assets' : 'timing-sync', is_representative: index !== 1,
    sibling_count: index === 0 ? 2 : 1,
  }))
  return {
    answer, citations, elapsed_ms: 684,
    evidence_groups: [
      { group_id: 'timing-sync', label: 'Timing and sync', count: 2, representative: citations[0], supporting: [citations[1]] },
      { group_id: 'source-assets', label: 'Source asset gaps', count: 1, representative: citations[2], supporting: [] },
    ],
    qc: { stage: 'answer', status: 'pass', summary: 'Claims are supported by cited rows.', issues: [], metrics: { citation_coverage: 1, evidence_groups: 2 } },
    debug: { route: 'hybrid-rag', intent: asksAboutTrend ? 'trend-analysis' : 'issue-triage', candidate_count: 18, group_count: 2 },
  }
}

export async function demoRequest<T>(path: string, init?: RequestInit): Promise<T> {
  await wait()
  const method = init?.method || 'GET'
  if (path === '/documents/stats') return { total_chunks: 389, total_docs: 18, by_category: { Campaign: 211, Education: 112, Product: 66 }, by_sprint: { '2025 Q3': 72, '2025 Q4': 104, '2026 Q1': 109, '2026 Q2': 104 }, by_tag: { timing: 81, terminology: 68, sync: 57, 'missing asset': 39 }, embedding_model: 'multilingual-e5' } as T
  if (path === '/analytics/dashboard/overall') return { trends: demoDashboard.trends } as T
  if (path === '/analytics/dashboard/videos') return { videos: demoDashboard.videos } as T
  if (path === '/analytics/dashboard/vendors') return demoDashboard.vendors as T
  if (path === '/rules' || path === '/rules/reset') return rules as T
  if (path === '/tags') return { tags: ['Animation', 'Translation', 'Voice Over', 'Source'], detail_tags: ['subtitle timing', 'reading speed', 'lip sync', 'audio drift', 'missing asset', 'text overlay'], active_detail_tags_count: 6, loose_detail_tags_count: 2 } as T
  if (path === '/tags/taxonomy') return { categories: { Animation: ['timing', 'transition'], Translation: ['subtitle timing', 'reading speed'], 'Voice Over': ['lip sync', 'audio drift'], Source: ['missing asset', 'text overlay'] }, candidates: [{ tag: 'asset gap', count: 4, categories: { Source: 4 } }] } as T
  if (path === '/tags/review-queue') return { rows: reviews } as T
  if (path === '/tags/noise') return { rows: [] } as T
  if (path === '/tags/feedback/distill') return { rules: ['When narration drift follows a chapter transition, prefer Voice Over unless the master timing also changed.'], examples: [], total_feedback: 7 } as T
  if (path === '/documents/sprints') return { sprints: ['2025 Q4', '2026 Q1', '2026 Q2'] } as T
  if (path.startsWith('/documents?') || path === '/documents') return { docs: documents } as T
  if (/^\/documents\/[^/]+\/chunks$/.test(path)) return { chunks: reviews.map((row, index) => ({ chunk_id: `chunk-${index + 1}`, text: row.text, metadata: { sprint: row.sprint, category: row.category_tag, confidence: row.confidence } })) } as T
  if (/^\/tags\/[^/]+$/.test(path)) return { doc_id: path.split('/')[2], rows: rowTags } as T
  if (path === '/preprocess/preview') return { docs: [{ doc_id: 'uploaded-demo', title: 'Synthetic upload preview', sections_count: 4, table_rows_count: 28, total_chars: 2840, sample_text: 'Project | Locale | Issue | Owner | Status', qc: { stage: 'preview', status: 'warning', summary: 'Two legacy column names were normalized.', issues: [{ severity: 'warning', type: 'schema_drift', message: 'Mapped PIC to Owner and Resolution to Status.' }], metrics: { normalized_columns: 2 } } }], rules } as T
  if (path === '/ingest/parse') return { batch_id: 'demo-batch', docs: [{ doc_id: 'uploaded-demo', title: 'Synthetic upload', code: 'DEMO', prefix: 'UPL', word_count: 412 }] } as T
  if (path === '/ingest/approve') return { ingested: 1, failed: [] } as T
  if (path.includes('/reprocess')) return { doc_id: 'demo-onboarding-2026-q1', chunks: 82, issue_rows: 24, excluded_rows: 3, source_path: 'synthetic://onboarding-q1' } as T
  if (path.includes('/row/') && method === 'DELETE') return { deleted: 1 } as T
  if (path.includes('/row/') && path.endsWith('/noise')) return { archived: 1 } as T
  if (path.includes('/row/') && path.endsWith('/restore')) return { restored: 1 } as T
  if (path.includes('/row/') && method === 'PUT') return { doc_id: path.split('/')[2], rows: rowTags } as T
  if (path === '/tags/batch-delete') return { total: 1, deleted: 1, failed: [] } as T
  if (path === '/tags/batch-update') return { total: 1, updated: 1, failed: [] } as T
  if (path === '/tags/detail-tags/merge') return { updated_rows: 4, synced_chunks: 4 } as T
  if (method === 'DELETE') return { deleted: path.split('/').pop() } as T
  if (method === 'PATCH') return { updated_chunks: 82 } as T
  throw new Error(`Demo route not implemented: ${method} ${path}`)
}

interface DemoPullHandlers {
  onStart?: (event: any) => void
  onProgress?: (event: any) => void
  onDocComplete?: (event: any) => void
  onComplete?: (event: any) => void
  onError?: (event: any) => void
}

export async function runDemoPull(urls: string[], handlers: DemoPullHandlers) {
  handlers.onStart?.({ total: urls.length || 1 })
  const steps = ['Fetching', 'Auto-tagging', 'Parsing', 'Indexing']
  for (const step of steps) {
    await wait(280)
    handlers.onProgress?.({ index: 1, total: 1, step, thread_id: 'synthetic-thread', title: 'Synthetic project log' })
  }
  handlers.onDocComplete?.({ index: 1, total: 1, chunks: 28, doc: { doc_id: 'synthetic-thread', title: 'Synthetic project log', table_rows_count: 28, sections_count: 4, total_chars: 2840, sample_text: 'Project | Locale | Issue | Owner | Status' } })
  handlers.onComplete?.({ total: 1, rules })
}
