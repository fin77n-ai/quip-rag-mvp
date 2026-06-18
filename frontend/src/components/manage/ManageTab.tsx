import { useEffect, useState } from 'react'

import {
  archiveRowAsNoise,
  batchDeleteRows,
  deleteDocument,
  distillTagFeedback,
  getDocTags,
  getKnownTags,
  getTagTaxonomy,
  getDocChunks,
  getNoiseRows,
  getReviewQueue,
  getSprints,
  listDocuments,
  mergeDetailTag,
  patchDocMetadata,
  reprocessDocument,
  restoreRowChunk,
  setRowTag,
  streamReprocessAllDocuments,
  type ChunkView,
  type DistilledFeedback,
  type DocSummaryRow,
  type ReprocessAllDocumentsResult,
  type ReprocessAllDocCompleteEvent,
  type ReprocessAllErrorEvent,
  type ReprocessAllProgressEvent,
  type RowTag,
  type ReviewQueueRow,
  type TagTaxonomy,
} from '../../api/client'

const BROAD_CATEGORY_OPTIONS = ['Animation', 'Translation', 'Voice Over', 'Source'] as const

interface Props {
  onChanged: () => void
}

function makeSelectedRowId(docId: string, rowKey: string) {
  return JSON.stringify([docId, rowKey])
}

function parseSelectedRowId(rowId: string): [string, string] {
  const parsed = JSON.parse(rowId)
  if (!Array.isArray(parsed) || parsed.length !== 2) {
    throw new Error(`Invalid row selection id: ${rowId}`)
  }
  return [String(parsed[0]), String(parsed[1])]
}

function makeDomId(value: string) {
  return value.replace(/[^A-Za-z0-9_-]/g, '_')
}

function stageLabel(stage: string) {
  if (stage === 'loading-source') return 'Loading source'
  if (stage === 'auto-tagging') return 'Auto-tagging'
  if (stage === 'parsing') return 'Parsing'
  if (stage === 'rebuilding-chunks') return 'Rebuilding chunks'
  if (stage === 'queued') return 'Queued'
  if (stage === 'done') return 'Done'
  return stage
}

const REPROCESS_STAGES = ['loading-source', 'auto-tagging', 'parsing', 'rebuilding-chunks'] as const

function stageStatus(activeStage: string | null, stage: typeof REPROCESS_STAGES[number], hasRunSummary: boolean) {
  if (!activeStage && !hasRunSummary) return 'idle'
  const activeIndex = activeStage ? REPROCESS_STAGES.indexOf(activeStage as typeof REPROCESS_STAGES[number]) : -1
  const stageIndex = REPROCESS_STAGES.indexOf(stage)
  if (hasRunSummary && activeStage === 'done') return 'done'
  if (activeIndex > stageIndex) return 'done'
  if (activeIndex === stageIndex) return 'active'
  return 'idle'
}

function stageClasses(status: 'idle' | 'active' | 'done') {
  if (status === 'done') {
    return 'border-emerald-500/40 bg-emerald-500/10 text-emerald-300'
  }
  if (status === 'active') {
    return 'border-cyan-400/40 bg-cyan-400/10 text-cyan-200 shadow-[0_0_0_1px_rgba(34,211,238,0.12)]'
  }
  return 'border-zinc-800 bg-zinc-900/70 text-zinc-500'
}

function feedClasses(kind: ReprocessFeedItem['kind']) {
  if (kind === 'success') {
    return 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200'
  }
  if (kind === 'error') {
    return 'border-rose-500/20 bg-rose-500/10 text-rose-200'
  }
  return 'border-cyan-500/20 bg-cyan-500/10 text-cyan-100'
}

function feedBadge(kind: ReprocessFeedItem['kind']) {
  if (kind === 'success') return 'Synced'
  if (kind === 'error') return 'Blocked'
  return 'Live'
}

function summaryFeedItem(feed: ReprocessFeedItem[]) {
  return feed.find(item => item.kind === 'error') || feed.find(item => item.kind === 'success') || feed[0] || null
}

function latestChunkRebuildTime(chunks: ChunkView[]) {
  const timestamps = chunks
    .map(chunk => String(chunk.metadata.processed_at || ''))
    .filter(Boolean)
    .sort()
  return timestamps[timestamps.length - 1] || ''
}

type ReprocessFeedItem =
  | { kind: 'progress'; id: string; docId: string; text: string }
  | { kind: 'success'; id: string; docId: string; text: string }
  | { kind: 'error'; id: string; docId: string; text: string }

export default function ManageTab({ onChanged }: Props) {
  const [docs, setDocs] = useState<DocSummaryRow[]>([])
  const [reviewQueue, setReviewQueue] = useState<ReviewQueueRow[]>([])
  const [selectedRows, setSelectedRows] = useState<Set<string>>(new Set())
  const [selectedDocIds, setSelectedDocIds] = useState<Set<string>>(new Set())
  const [distilled, setDistilled] = useState<DistilledFeedback | null>(null)
  const [loading, setLoading] = useState(false)
  const [message, setMessage] = useState('')
  const [filterCategory, setFilterCategory] = useState('')
  const [filterSprint, setFilterSprint] = useState('')
  const [knownSprints, setKnownSprints] = useState<string[]>([])
  const [knownCategoryTags, setKnownCategoryTags] = useState<string[]>([])
  const [knownDetailTags, setKnownDetailTags] = useState<string[]>([])
  const [activeDetailTagCount, setActiveDetailTagCount] = useState(0)
  const [looseDetailTagCount, setLooseDetailTagCount] = useState(0)
  const [chunkDoc, setChunkDoc] = useState<{ doc: DocSummaryRow; chunks: ChunkView[] } | null>(null)
  const [editingRowId, setEditingRowId] = useState<string | null>(null)
  const [editingRowTag, setEditingRowTag] = useState<RowTag | null>(null)
  const [editingChunkRowId, setEditingChunkRowId] = useState<string | null>(null)
  const [editingChunkRowTag, setEditingChunkRowTag] = useState<RowTag | null>(null)
  const [showNoise, setShowNoise] = useState(false)
  const [taxonomyOpen, setTaxonomyOpen] = useState(false)
  const [tagTaxonomy, setTagTaxonomy] = useState<TagTaxonomy | null>(null)
  const [taxonomyBusy, setTaxonomyBusy] = useState(false)
  const [taxonomyDrafts, setTaxonomyDrafts] = useState<Record<string, { category: string; toTag: string }>>({})
  const [allCategories, setAllCategories] = useState<string[]>([])
  const [processingLabel, setProcessingLabel] = useState('')
  const [reprocessAllBusy, setReprocessAllBusy] = useState(false)
  const [distillBusy, setDistillBusy] = useState(false)
  const [batchBusy, setBatchBusy] = useState(false)
  const [activeDocAction, setActiveDocAction] = useState<{ docId: string; action: 'reprocess' | 'delete' | '' }>({ docId: '', action: '' })
  const [busyRowIds, setBusyRowIds] = useState<Set<string>>(new Set())
  const [reprocessFeed, setReprocessFeed] = useState<ReprocessFeedItem[]>([])
  const [reprocessSummary, setReprocessSummary] = useState<ReprocessAllDocumentsResult | null>(null)
  const [reprocessCurrent, setReprocessCurrent] = useState<{ current: number; total: number; docId: string; stage: string } | null>(null)
  const [reprocessFlowExpanded, setReprocessFlowExpanded] = useState(true)
  const latestReprocessFeedItem = summaryFeedItem(reprocessFeed)
  const selectedVisibleDocIds = docs.filter(doc => selectedDocIds.has(doc.doc_id)).map(doc => doc.doc_id)
  const docActionsBusy = reprocessAllBusy || Boolean(activeDocAction.docId)

  const refresh = async () => {
    setLoading(true)
    setProcessingLabel(current => current || 'Refreshing document list and review queue...')
    try {
      const [documents, sprints, queue, noise] = await Promise.all([
        listDocuments(filterCategory || undefined, filterSprint || undefined),
        getSprints(),
        getReviewQueue(),
        getNoiseRows(),
      ])
      setDocs(documents.docs)
      setSelectedDocIds(current => {
        const available = new Set(documents.docs.map(doc => doc.doc_id))
        return new Set(Array.from(current).filter(docId => available.has(docId)))
      })
      setKnownSprints(sprints.sprints)
      setReviewQueue(showNoise ? noise.rows : queue.rows)
    } finally {
      setLoading(false)
      setProcessingLabel(current => current === 'Refreshing document list and review queue...' ? '' : current)
    }
  }

  useEffect(() => { void refresh() }, [filterCategory, filterSprint, showNoise])
  useEffect(() => {
    getKnownTags()
      .then(result => {
        setKnownCategoryTags(result.tags)
        setKnownDetailTags(result.detail_tags)
        setActiveDetailTagCount(result.active_detail_tags_count)
        setLooseDetailTagCount(result.loose_detail_tags_count)
      })
      .catch(() => {})
  }, [])

  const refreshKnownTags = async () => {
    const result = await getKnownTags()
    setKnownCategoryTags(result.tags)
    setKnownDetailTags(result.detail_tags)
    setActiveDetailTagCount(result.active_detail_tags_count)
    setLooseDetailTagCount(result.loose_detail_tags_count)
  }

  const refreshTaxonomy = async () => {
    setTaxonomyBusy(true)
    setProcessingLabel('Refreshing tag taxonomy candidates...')
    try {
      const result = await getTagTaxonomy()
      setTagTaxonomy(result)
      setTaxonomyDrafts(current => {
        const next = { ...current }
        result.candidates.forEach(candidate => {
          if (!next[candidate.tag]) {
            const likelyCategory = Object.entries(candidate.categories).sort((a, b) => b[1] - a[1])[0]?.[0] || 'Translation'
            next[candidate.tag] = {
              category: result.categories[likelyCategory] ? likelyCategory : 'Translation',
              toTag: result.categories[likelyCategory]?.[0] || result.categories.Translation?.[0] || '',
            }
          }
        })
        return next
      })
    } finally {
      setTaxonomyBusy(false)
      setProcessingLabel('')
    }
  }

  useEffect(() => { void refreshTaxonomy() }, [])

  useEffect(() => {
    listDocuments().then(res => {
      setAllCategories(Array.from(new Set(res.docs.map(d => d.category))).filter(Boolean).sort())
    }).catch(console.error)
  }, [])

  const removeRowFromView = (docId: string, rowKey: string, deletedCount: number) => {
    setReviewQueue(prev => prev.filter(row => !(row.doc_id === docId && row.row_key === rowKey)))
    setSelectedRows(prev => {
      const next = new Set(prev)
      next.delete(makeSelectedRowId(docId, rowKey))
      return next
    })
    setDocs(prev => prev.map(doc => (
      doc.doc_id === docId
        ? { ...doc, chunk_count: Math.max(0, doc.chunk_count - deletedCount) }
        : doc
    )))
    setChunkDoc(prev => {
      if (!prev || prev.doc.doc_id !== docId) {
        return prev
      }
      return {
        ...prev,
        chunks: prev.chunks.filter(chunk => chunk.metadata.row_key !== rowKey),
      }
    })
  }

  const handleDelete = async (doc: DocSummaryRow) => {
    if (!confirm(`Delete ${doc.title}?`)) return
    setActiveDocAction({ docId: doc.doc_id, action: 'delete' })
    setProcessingLabel(`Deleting ${doc.code}...`)
    try {
      await deleteDocument(doc.doc_id)
      setMessage(`Deleted ${doc.code}.`)
      onChanged()
      await refresh()
    } finally {
      setActiveDocAction({ docId: '', action: '' })
      setProcessingLabel('')
    }
  }

  const handleEditCategory = async (doc: DocSummaryRow) => {
    const category = prompt('Update document category', doc.category)
    if (category === null || category === doc.category) return
    await patchDocMetadata(doc.doc_id, { category })
    setMessage(`Updated ${doc.code} category.`)
    onChanged()
    await refresh()
  }

  const handleEditSprint = async (doc: DocSummaryRow) => {
    const sprint = prompt('Update sprint', doc.sprint)
    if (sprint === null || sprint === doc.sprint) return
    await patchDocMetadata(doc.doc_id, { sprint })
    setMessage(`Updated ${doc.code} sprint.`)
    onChanged()
    await refresh()
  }

  const handleViewChunks = async (doc: DocSummaryRow) => {
    if (docActionsBusy) return
    setActiveDocAction({ docId: doc.doc_id, action: '' })
    try {
      const result = await getDocChunks(doc.doc_id)
      setChunkDoc({ doc, chunks: result.chunks })
    } catch (error) {
      setMessage(`Error loading chunks for ${doc.code}: ${error}`)
    } finally {
      setActiveDocAction({ docId: '', action: '' })
    }
  }

  const handleReprocessDoc = async (doc: DocSummaryRow) => {
    if (!confirm(`Reprocess ${doc.title} from the saved local Quip source?\n\nThis will re-run auto-tagging and rebuild its chunks using the latest rules.`)) {
      return
    }
    setActiveDocAction({ docId: doc.doc_id, action: 'reprocess' })
    setProcessingLabel(`Reprocessing ${doc.code}: re-running auto-tagging and rebuilding chunks...`)
    try {
      const result = await reprocessDocument(doc.doc_id)
      setMessage(`Reprocessed ${doc.code}. Rebuilt ${result.chunks} chunks, kept ${result.issue_rows} issue rows, auto-excluded ${result.excluded_rows} saved rows.`)
      onChanged()
      await Promise.all([refresh(), refreshKnownTags(), refreshTaxonomy()])
      if (chunkDoc?.doc.doc_id === doc.doc_id) {
        const refreshed = await getDocChunks(doc.doc_id)
        setChunkDoc(current => current ? { ...current, chunks: refreshed.chunks } : current)
      }
    } catch (error) {
      setMessage(`Error reprocessing ${doc.code}: ${error}`)
    } finally {
      setActiveDocAction({ docId: '', action: '' })
      setProcessingLabel('')
    }
  }

  const handleReprocessSelectedDocs = async () => {
    if (selectedVisibleDocIds.length === 0) {
      setMessage('Select at least one visible video to reprocess.')
      return
    }
    if (!confirm(`Reprocess ${selectedVisibleDocIds.length} selected local Quip source${selectedVisibleDocIds.length === 1 ? '' : 's'}?\n\nThis will re-run auto-tagging and rebuild chunks only for the selected videos.`)) {
      return
    }
    setReprocessAllBusy(true)
    setReprocessFeed([])
    setReprocessSummary(null)
    setReprocessCurrent(null)
    setReprocessFlowExpanded(true)
    setProcessingLabel(`Reprocessing ${selectedVisibleDocIds.length} selected sources: re-running auto-tags and rebuilding chunks...`)
    const docIdsToReprocess = selectedVisibleDocIds
    try {
      await streamReprocessAllDocuments(docIdsToReprocess, {
        onStart: event => {
          setReprocessCurrent({ current: 0, total: event.total, docId: '', stage: 'queued' })
          setReprocessFeed([{ kind: 'progress', id: 'start', docId: '', text: `Queued ${event.total} saved source files.` }])
        },
        onProgress: (event: ReprocessAllProgressEvent) => {
          setReprocessCurrent({ current: event.index, total: event.total, docId: event.doc_id, stage: event.stage })
          setReprocessFeed(prev => [
            { kind: 'progress' as const, id: `progress-${event.index}-${event.stage}`, docId: event.doc_id, text: `${event.doc_id}: ${stageLabel(event.stage)}` },
            ...prev,
          ].slice(0, 12))
        },
        onDocComplete: (event: ReprocessAllDocCompleteEvent) => {
          setReprocessFeed(prev => [
            { kind: 'success' as const, id: `success-${event.index}`, docId: event.doc.doc_id, text: `${event.doc.doc_id}: rebuilt ${event.doc.chunks} chunks, excluded ${event.doc.excluded_rows} non-issue rows.` },
            ...prev,
          ].slice(0, 12))
        },
        onError: (event: ReprocessAllErrorEvent) => {
          setReprocessFeed(prev => [
            { kind: 'error' as const, id: `error-${event.index}`, docId: event.doc_id, text: `${event.doc_id}: ${event.reason}` },
            ...prev,
          ].slice(0, 12))
        },
        onComplete: result => {
          setReprocessSummary(result)
          setReprocessCurrent(current => current ? { ...current, current: result.total_sources, stage: 'done' } : null)
          setReprocessFlowExpanded(false)
          const failureNote = result.failed.length ? ` ${result.failed.length} failed.` : ''
          setMessage(`Reprocessed ${result.reprocessed}/${result.total_sources} saved sources.${failureNote}`)
          if (result.failed.length) {
            console.error('Reprocess-all failures:', result.failed)
          }
        },
      })
      onChanged()
      await Promise.all([refresh(), refreshKnownTags(), refreshTaxonomy()])
      setSelectedDocIds(new Set())
      if (chunkDoc) {
        const refreshed = await getDocChunks(chunkDoc.doc.doc_id)
        setChunkDoc(current => current ? { ...current, chunks: refreshed.chunks } : current)
      }
    } catch (error) {
      setMessage(`Error reprocessing all docs: ${error}`)
    } finally {
      setReprocessAllBusy(false)
      setProcessingLabel('')
    }
  }

  const handleDistill = async () => {
    setDistillBusy(true)
    setProcessingLabel('Distilling wrong-answer notebook into reusable tagging rules...')
    try {
      const result = await distillTagFeedback()
      setDistilled(result)
      setMessage(`Distilled ${result.total_feedback} feedback items into a compact playbook.`)
    } finally {
      setDistillBusy(false)
      setProcessingLabel('')
    }
  }

  const handleDeleteRow = async (row: ReviewQueueRow) => {
    if (!confirm(`Archive this row as noise?\n\n${row.text?.slice(0, 100)}...\n\nIt will stay in the Noise view and stop appearing in search results. The chunk is not deleted.`)) {
      return
    }
    const rowId = makeSelectedRowId(row.doc_id, row.row_key)
    setBusyRowIds(prev => new Set(prev).add(rowId))
    setProcessingLabel(`Archiving ${row.code} ${row.row_key} as noise...`)
    try {
      await archiveRowAsNoise(row.doc_id, row.row_key)
      removeRowFromView(row.doc_id, row.row_key, 0)
      setMessage(showNoise ? 'This row is already in the noise archive.' : 'Archived row as noise. It left the human review queue, but the chunk was kept.')
      onChanged()
      await refresh()
    } catch (error) {
      setMessage(`Error archiving row as noise: ${error}`)
    } finally {
      setBusyRowIds(prev => {
        const next = new Set(prev)
        next.delete(rowId)
        return next
      })
      setProcessingLabel('')
    }
  }

  const buildDraftTag = (row: ReviewQueueRow, existing?: RowTag): RowTag => ({
    tags: existing?.tags ?? row.tags ?? (row.category_tag ? [row.category_tag] : []),
    excluded: existing?.excluded ?? false,
    is_noise: existing?.is_noise ?? false,
    category_tag: existing?.category_tag ?? row.category_tag ?? '',
    detail_tags: existing?.detail_tags ?? row.detail_tags ?? [],
    confidence: existing?.confidence ?? row.confidence ?? 0,
    rationale: existing?.rationale ?? row.rationale ?? '',
    review_required: existing?.review_required ?? true,
    review_reason: existing?.review_reason ?? row.review_reason ?? '',
    feedback_note: existing?.feedback_note ?? '',
    is_issue: existing?.is_issue ?? '',
    issue_summary: existing?.issue_summary ?? '',
    issue_type: existing?.issue_type ?? '',
    owner: existing?.owner ?? '',
    status: existing?.status ?? '',
  })

  const handleEditReviewRow = async (row: ReviewQueueRow) => {
    const rowId = makeSelectedRowId(row.doc_id, row.row_key)
    setEditingRowId(rowId)
    setEditingRowTag(null)
    try {
      const tags = await getDocTags(row.doc_id)
      setEditingRowTag(buildDraftTag(row, tags.rows[row.row_key]))
    } catch {
      setEditingRowTag(buildDraftTag(row))
    }
  }

  const handleSaveReviewRow = async (row: ReviewQueueRow, next: RowTag) => {
    await setRowTag(row.doc_id, row.row_key, {
      ...next,
      tags: next.category_tag ? [next.category_tag] : next.tags,
      detail_tags: next.detail_tags.slice(0, 5),
    })
    setEditingRowId(null)
    setEditingRowTag(null)
    setMessage(`Saved review feedback for ${row.code} ${row.row_key}.`)
    onChanged()
    await refresh()
  }

  const handleSaveReviewAndRestoreChunk = async (row: ReviewQueueRow, next: RowTag) => {
    const currentIndex = reviewQueue.findIndex(item => item.doc_id === row.doc_id && item.row_key === row.row_key)
    const nextRow = currentIndex >= 0 ? reviewQueue[currentIndex + 1] ?? null : null
    const resolvedTag: RowTag = {
      ...next,
      excluded: false,
      is_noise: false,
      review_required: false,
    }

    await setRowTag(row.doc_id, row.row_key, {
      ...resolvedTag,
      tags: resolvedTag.category_tag ? [resolvedTag.category_tag] : resolvedTag.tags,
      detail_tags: resolvedTag.detail_tags.slice(0, 5),
    })
    const result = await restoreRowChunk(row.doc_id, row.row_key)
    removeRowFromView(row.doc_id, row.row_key, 0)
    setEditingRowId(null)
    setEditingRowTag(null)
    setMessage(
      result.restored > 0
        ? `Saved review and restored ${result.restored} chunk(s) for ${row.code} ${row.row_key}.`
        : `Saved review for ${row.code} ${row.row_key}, but no source chunk could be rebuilt.`
    )
    onChanged()
    await refresh()
    if (nextRow) {
      await handleEditReviewRow(nextRow)
    }
  }

  const buildDraftTagFromChunk = (chunk: ChunkView, existing?: RowTag): RowTag => ({
    tags: existing?.tags ?? (chunk.metadata.category_tag ? [String(chunk.metadata.category_tag)] : []),
    excluded: existing?.excluded ?? false,
    is_noise: existing?.is_noise ?? (String(chunk.metadata.is_noise || '').toLowerCase() === 'yes'),
    category_tag: existing?.category_tag ?? String(chunk.metadata.category_tag || ''),
    detail_tags: existing?.detail_tags ?? String(chunk.metadata.detail_tags || '').split(',').map(tag => tag.trim()).filter(Boolean),
    confidence: existing?.confidence ?? Number(chunk.metadata.confidence || 0),
    rationale: existing?.rationale ?? String(chunk.metadata.rationale || ''),
    review_required: existing?.review_required ?? false,
    review_reason: existing?.review_reason ?? '',
    feedback_note: existing?.feedback_note ?? '',
    is_issue: existing?.is_issue ?? String(chunk.metadata.is_issue || ''),
    issue_summary: existing?.issue_summary ?? String(chunk.metadata.issue_summary || ''),
    issue_type: existing?.issue_type ?? String(chunk.metadata.issue_type || ''),
    owner: existing?.owner ?? String(chunk.metadata.owner || ''),
    status: existing?.status ?? String(chunk.metadata.status || ''),
  })

  const handleEditChunkRow = async (chunk: ChunkView) => {
    if (!chunkDoc?.doc.doc_id || !chunk.metadata.row_key) return
    const rowKey = String(chunk.metadata.row_key)
    const rowId = makeSelectedRowId(chunkDoc.doc.doc_id, rowKey)
    setEditingChunkRowId(rowId)
    setEditingChunkRowTag(null)
    try {
      const tags = await getDocTags(chunkDoc.doc.doc_id)
      setEditingChunkRowTag(buildDraftTagFromChunk(chunk, tags.rows[rowKey]))
    } catch {
      setEditingChunkRowTag(buildDraftTagFromChunk(chunk))
    }
  }

  const handleSaveChunkRow = async (chunk: ChunkView, next: RowTag) => {
    if (!chunkDoc?.doc.doc_id || !chunk.metadata.row_key) return
    const rowKey = String(chunk.metadata.row_key)
    await setRowTag(chunkDoc.doc.doc_id, rowKey, {
      ...next,
      tags: next.category_tag ? [next.category_tag] : next.tags,
      detail_tags: next.detail_tags.slice(0, 5),
    })
    const refreshed = await getDocChunks(chunkDoc.doc.doc_id)
    setChunkDoc(current => current ? { ...current, chunks: refreshed.chunks } : current)
    setEditingChunkRowId(null)
    setEditingChunkRowTag(null)
    setMessage(`Updated saved chunk tag for ${chunkDoc.doc.code} ${rowKey}.`)
    onChanged()
    await refresh()
  }

  const handleBatchDelete = async () => {
    if (selectedRows.size === 0) {
      setMessage('No rows selected.')
      return
    }
    if (!confirm(`Archive ${selectedRows.size} selected rows as noise?\n\nThey will stop appearing in search results, but remain visible in the Noise view. Chunks will be kept.`)) {
      return
    }
    const items = Array.from(selectedRows).map(rowId => {
      const [doc_id, row_key] = parseSelectedRowId(rowId)
      return { doc_id, row_key }
    })
    setBatchBusy(true)
    setProcessingLabel(`Archiving ${selectedRows.size} selected row(s) as noise...`)
    try {
      const result = await batchDeleteRows(items)
      items.forEach(item => removeRowFromView(item.doc_id, item.row_key, 0))
      setMessage(`Archived ${items.length} row(s) as noise. Chunks were kept.`)
      if (result.failed.length > 0) {
        console.error('Batch delete failures:', result.failed)
      }
      onChanged()
      await refresh()
    } catch (error) {
      setMessage(`Error archiving rows as noise: ${error}`)
    } finally {
      setBatchBusy(false)
      setProcessingLabel('')
    }
  }

  const handleMergeDetailTag = async (fromTag: string) => {
    const draft = taxonomyDrafts[fromTag]
    if (!draft?.toTag) {
      setMessage('Pick a target sub-tag before applying taxonomy changes.')
      return
    }
    setTaxonomyBusy(true)
    setProcessingLabel(`Merging detail tag "${fromTag}" into "${draft.toTag}"...`)
    try {
      const result = await mergeDetailTag(fromTag, draft.toTag, draft.category)
      setMessage(`Merged "${fromTag}" into "${draft.toTag}" across ${result.updated_rows} row(s), synced ${result.synced_chunks} chunk(s).`)
      await Promise.all([refresh(), refreshKnownTags(), refreshTaxonomy()])
      onChanged()
    } catch (error) {
      setMessage(`Error merging detail tag: ${error}`)
    } finally {
      setTaxonomyBusy(false)
      setProcessingLabel('')
    }
  }

  const toggleRowSelection = (row: ReviewQueueRow) => {
    const rowId = makeSelectedRowId(row.doc_id, row.row_key)
    setSelectedRows(prev => {
      const next = new Set(prev)
      if (next.has(rowId)) {
        next.delete(rowId)
      } else {
        next.add(rowId)
      }
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selectedRows.size === reviewQueue.length) {
      setSelectedRows(new Set())
    } else {
      setSelectedRows(new Set(reviewQueue.map(r => makeSelectedRowId(r.doc_id, r.row_key))))
    }
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-4 xl:grid-cols-[1.3fr_1fr]">
        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <div className="mb-3 flex items-center justify-between">
            <div>
              <h2 className="text-sm font-semibold text-white">{showNoise ? 'Noise Archive' : 'Human Review Queue'}</h2>
              <p className="text-xs text-zinc-400">
                {showNoise
                  ? 'Archived noise rows stay visible here, but no longer participate in search.'
                  : 'Rows with confidence below 0.8 or explicit review flags land here.'}
              </p>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setShowNoise(value => !value)}
                className={`rounded-lg px-3 py-2 text-sm font-medium ${
                  showNoise ? 'bg-rose-600 text-white hover:bg-rose-700' : 'border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 text-zinc-300 hover:bg-zinc-900/50'
                }`}
              >
                {showNoise ? 'Show review queue' : 'Show noise'}
              </button>
              {selectedRows.size > 0 && (
                <button
                  onClick={handleBatchDelete}
                  disabled={batchBusy}
                  className="rounded-lg bg-red-600 px-3 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:cursor-not-allowed disabled:opacity-60"
                >
                  {batchBusy ? 'Archiving...' : `Mark ${selectedRows.size} as noise`}
                </button>
              )}
              <button onClick={handleDistill} disabled={distillBusy} className="rounded-lg bg-emerald-500 px-3 py-2 text-sm font-medium text-zinc-950 hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60">
                {distillBusy ? 'Distilling...' : 'Distill Wrong-Answer Notebook'}
              </button>
            </div>
          </div>
          <div className="space-y-2">
            {reviewQueue.length === 0 ? (
              <div className="rounded-lg bg-zinc-900/50 p-4 text-sm text-zinc-400">
                {showNoise ? 'No noise rows are archived right now.' : 'No rows currently need review.'}
              </div>
            ) : (
              <>
                <div className="flex items-center gap-2 border-b border-zinc-800 pb-2">
                  <input
                    type="checkbox"
                    checked={selectedRows.size === reviewQueue.length && reviewQueue.length > 0}
                    onChange={toggleSelectAll}
                    className="h-4 w-4 rounded border-gray-300"
                  />
                  <span className="text-xs font-medium text-zinc-400">
                    Select all ({reviewQueue.length} rows)
                  </span>
                </div>
                {reviewQueue.map(row => {
                  const rowId = makeSelectedRowId(row.doc_id, row.row_key)
                  const isSelected = selectedRows.has(rowId)
                  const rowBusy = busyRowIds.has(rowId)
                  const rowTitleClass = isSelected || showNoise ? 'text-zinc-900' : 'text-zinc-900'
                  const rowMetaClass = isSelected || showNoise ? 'text-zinc-500' : 'text-zinc-500'
                  const rowReasonClass = isSelected || showNoise ? 'text-zinc-500' : 'text-zinc-500'
                  return (
                    <div
                      key={rowId}
                      className={`rounded-xl border p-3 ${
                        isSelected
                          ? 'border-emerald-500 bg-emerald-500/10'
                          : showNoise
                            ? 'border-rose-200 bg-rose-50'
                            : 'border-amber-200 bg-amber-50'
                      }`}
                    >
                      <div className="flex items-start gap-3">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleRowSelection(row)}
                          className="mt-1 h-4 w-4 rounded border-gray-300"
                        />
                        <div className="flex-1">
                          <div className="flex items-start justify-between gap-3">
                            <div>
                              <div className={`font-semibold ${rowTitleClass}`}>{row.title}</div>
                              <div className={`text-xs ${rowMetaClass}`}>{row.code} · {row.row_key}</div>
                            </div>
                            <div className="flex items-center gap-2">
                              <div className="rounded-full bg-zinc-900 px-2 py-1 text-xs text-amber-700">
                                confidence {(row.confidence || 0).toFixed(2)}
                              </div>
                              {row.is_noise && (
                                <div className="rounded-full bg-rose-100 px-2 py-1 text-xs text-rose-700">
                                  Noise
                                </div>
                              )}
                              <button
                                onClick={() => void handleDeleteRow(row)}
                                disabled={showNoise || rowBusy}
                                className="rounded-lg bg-red-100 px-2 py-1 text-xs text-red-700 hover:bg-red-200 disabled:cursor-not-allowed disabled:opacity-60"
                              >
                                {showNoise ? 'Already noise' : rowBusy ? 'Archiving...' : 'Archive as noise'}
                              </button>
                            </div>
                          </div>

                          {/* Context Before */}
                          {row.context_before && row.context_before.length > 0 && (
                            <div className="mt-2 space-y-1">
                              {row.context_before.map((ctx, idx) => (
                                <div key={`before-${idx}`} className="rounded-lg bg-zinc-800 px-3 py-2 text-xs italic text-zinc-400">
                                  <span className="font-mono text-gray-400">{ctx.row_key}:</span> {ctx.text}
                                </div>
                              ))}
                            </div>
                          )}

                          {/* Current Row Content */}
                          <div className="mt-2 rounded-lg bg-zinc-900 px-3 py-2 text-sm text-white border border-zinc-800">
                            {row.text}
                          </div>

                          {/* Context After */}
                          {row.context_after && row.context_after.length > 0 && (
                            <div className="mt-2 space-y-1">
                              {row.context_after.map((ctx, idx) => (
                                <div key={`after-${idx}`} className="rounded-lg bg-zinc-800 px-3 py-2 text-xs italic text-zinc-400">
                                  <span className="font-mono text-gray-400">{ctx.row_key}:</span> {ctx.text}
                                </div>
                              ))}
                            </div>
                          )}

                          <div className="mt-2 flex flex-wrap gap-2 text-xs">
                            <span className="rounded-full bg-emerald-500 text-zinc-950 font-bold px-2 py-0.5">{row.category_tag || 'Unclassified'}</span>
                            {row.detail_tags.map(tag => (
                              <span key={tag} className="rounded-full bg-zinc-900 px-2 py-0.5 text-zinc-300 border border-zinc-800">{tag}</span>
                            ))}
                          </div>
                          <p className={`mt-2 text-sm ${rowReasonClass}`}>{row.review_reason || row.rationale || 'Needs human review.'}</p>
                          <div className="mt-3 flex justify-end gap-2">
                            <button
                              onClick={() => void handleEditReviewRow(row)}
                              className="rounded-lg border bg-zinc-800 px-3 py-1.5 text-xs font-medium text-white hover:bg-zinc-700"
                            >
                              Review / edit
                            </button>
                          </div>
                          {editingRowId === rowId && (
                            <div className="mt-3 rounded-xl border border-white bg-zinc-900 p-3">
                              {editingRowTag ? (
                                <ReviewRowEditor
                                  row={row}
                                  value={editingRowTag}
                                  knownTags={knownCategoryTags}
                                  knownDetailTags={knownDetailTags}
                                  onClose={() => {
                                    setEditingRowId(null)
                                    setEditingRowTag(null)
                                  }}
                                  onChange={async next => {
                                    await handleSaveReviewRow(row, next)
                                  }}
                                  onRestore={async next => {
                                    await handleSaveReviewAndRestoreChunk(row, next)
                                  }}
                                />
                              ) : (
                                <div className="text-xs text-zinc-400">Loading row details...</div>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                    </div>
                  )
                })}
              </>
            )}
          </div>
          {distilled && (
            <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-900/50 p-4">
              <div className="mb-2 text-sm font-semibold text-white">Distilled guidance</div>
              <div className="space-y-2 text-sm text-zinc-300">
                {distilled.rules.map(rule => <p key={rule}>{rule}</p>)}
              </div>
            </div>
          )}
        </section>

        <section className="rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          <div className="mb-3 text-sm font-semibold text-white">Document Controls</div>
          <div className="flex flex-wrap gap-2">
            <select value={filterCategory} onChange={e => setFilterCategory(e.target.value)} className="rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-3 py-2 text-sm">
              <option value="">All categories</option>
              {allCategories.map(category => <option key={category} value={category}>{category}</option>)}
            </select>
            <select value={filterSprint} onChange={e => setFilterSprint(e.target.value)} className="rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-3 py-2 text-sm">
              <option value="">All sprints</option>
              {knownSprints.map(sprint => <option key={sprint} value={sprint}>{sprint}</option>)}
            </select>
            <button onClick={() => void refresh()} disabled={loading} className="rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-3 py-2 text-sm disabled:cursor-not-allowed disabled:opacity-60">{loading ? 'Refreshing...' : 'Refresh'}</button>
            <button onClick={() => void handleReprocessSelectedDocs()} disabled={docActionsBusy || selectedVisibleDocIds.length === 0} className="rounded-lg bg-emerald-500 px-3 py-2 text-sm font-medium text-zinc-950 hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60">{reprocessAllBusy ? 'Reprocessing selected...' : `Reprocess selected (${selectedVisibleDocIds.length})`}</button>
            <button
              onClick={() => {
                setTaxonomyOpen(true)
                void refreshTaxonomy()
              }}
              disabled={taxonomyBusy}
              className="rounded-lg border bg-emerald-500 px-3 py-2 text-sm font-medium text-zinc-950 hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {taxonomyBusy ? 'Loading taxonomy...' : 'Tag taxonomy'}
            </button>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
              <div className="text-[11px] uppercase tracking-wide text-zinc-500">Visible Docs</div>
              <div className="mt-1 text-2xl font-semibold text-white">{docs.length}</div>
              <div className="mt-1 text-xs text-zinc-400">Filtered by category and sprint.</div>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
              <div className="text-[11px] uppercase tracking-wide text-zinc-500">Review Queue</div>
              <div className="mt-1 text-2xl font-semibold text-white">{showNoise ? reviewQueue.length : reviewQueue.length}</div>
              <div className="mt-1 text-xs text-zinc-400">
                {showNoise ? 'Currently showing archived noise rows.' : 'Rows still waiting for human confirmation.'}
              </div>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
              <div className="text-[11px] uppercase tracking-wide text-zinc-500">Known Broad Tags</div>
              <div className="mt-1 text-2xl font-semibold text-white">{knownCategoryTags.length}</div>
              <div className="mt-1 text-xs text-zinc-400">Controlled top-level issue buckets.</div>
            </div>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
              <div className="text-[11px] uppercase tracking-wide text-zinc-500">Active Detail Tags</div>
              <div className="mt-1 text-2xl font-semibold text-white">{activeDetailTagCount}</div>
              <div className="mt-1 text-xs text-zinc-400">
                {looseDetailTagCount > 0
                  ? `${looseDetailTagCount} loose tag${looseDetailTagCount === 1 ? '' : 's'} still need merging.`
                  : 'All current issue tags sit inside the controlled set.'}
              </div>
            </div>
          </div>
          <div className="mt-4 rounded-xl border border-zinc-800 bg-zinc-900/50 p-3 text-xs text-zinc-400">
            Reprocess actions use locally saved Quip source files in <span className="font-mono text-zinc-300">data/sources/quip</span>.
            Reprocess = re-run auto-tagging + rebuild chunks. Pending review rows are included, so new issue rules can clean them up automatically.
          </div>
          <div className="mt-4 overflow-hidden rounded-2xl border border-cyan-400/20 bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.12),transparent_28%),linear-gradient(180deg,rgba(10,14,22,0.96),rgba(24,24,27,0.98))] p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <div className="text-[11px] uppercase tracking-[0.22em] text-cyan-300">Task Flow</div>
                <div className="mt-1 text-lg font-semibold text-white">
                  {reprocessCurrent
                    ? `Reprocessing ${Math.min(reprocessCurrent.current, reprocessCurrent.total)} / ${reprocessCurrent.total}`
                    : reprocessSummary
                      ? `Reprocessed ${reprocessSummary.reprocessed} / ${reprocessSummary.total_sources}`
                      : 'System Idle'}
                </div>
                <div className="mt-1 text-xs text-zinc-400">
                  {reprocessCurrent?.docId
                    ? `Current: ${reprocessCurrent.docId} · ${stageLabel(reprocessCurrent.stage)}`
                    : reprocessSummary
                      ? 'Run finished. See summary and event feed below.'
                      : 'Awaiting tasks. Select videos below to rebuild their chunks.'}
                </div>
                <div className="mt-3 inline-flex items-center gap-2 rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-1 text-[11px] uppercase tracking-[0.2em] text-cyan-200">
                  <span className={`h-2 w-2 rounded-full shadow-[0_0_10px_rgba(103,232,249,0.9)] ${reprocessAllBusy || reprocessCurrent?.docId ? 'bg-cyan-300 animate-pulse' : 'bg-cyan-600'}`} />
                  {reprocessCurrent?.docId ? `${reprocessCurrent.docId} is in flight` : reprocessAllBusy ? 'Queue is waking up' : 'Ready'}
                </div>
              </div>
              {reprocessSummary && (
                <div className="flex items-start gap-3">
                  <div className="grid gap-2 sm:grid-cols-3">
                    <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-center">
                      <div className="text-[11px] uppercase tracking-wide text-zinc-500">Succeeded</div>
                      <div className="text-xl font-semibold text-white">{reprocessSummary.reprocessed}</div>
                    </div>
                    <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-center">
                      <div className="text-[11px] uppercase tracking-wide text-zinc-500">Failed</div>
                      <div className="text-xl font-semibold text-white">{reprocessSummary.failed.length}</div>
                    </div>
                    <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-center">
                      <div className="text-[11px] uppercase tracking-wide text-zinc-500">Sources</div>
                      <div className="text-xl font-semibold text-white">{reprocessSummary.total_sources}</div>
                    </div>
                  </div>
                  <button
                    onClick={() => setReprocessFlowExpanded(value => !value)}
                    className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[11px] uppercase tracking-[0.18em] text-cyan-200 hover:bg-cyan-400/15"
                  >
                    {reprocessFlowExpanded ? 'Collapse' : 'Expand'}
                  </button>
                </div>
              )}
              {reprocessSummary === null && !reprocessAllBusy && !reprocessCurrent && (
                <div className="flex items-start gap-3">
                  <div className="grid gap-2 sm:grid-cols-3 opacity-50 grayscale mix-blend-luminosity">
                    <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-center">
                      <div className="text-[11px] uppercase tracking-wide text-zinc-500">Succeeded</div>
                      <div className="text-xl font-semibold text-white">-</div>
                    </div>
                    <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-center">
                      <div className="text-[11px] uppercase tracking-wide text-zinc-500">Failed</div>
                      <div className="text-xl font-semibold text-white">-</div>
                    </div>
                    <div className="rounded-lg border border-zinc-800 bg-zinc-900/70 px-3 py-2 text-center">
                      <div className="text-[11px] uppercase tracking-wide text-zinc-500">Sources</div>
                      <div className="text-xl font-semibold text-white">-</div>
                    </div>
                  </div>
                  <button
                    onClick={() => setReprocessFlowExpanded(value => !value)}
                    className="rounded-full border border-cyan-400/20 bg-cyan-400/10 px-3 py-2 text-[11px] uppercase tracking-[0.18em] text-cyan-200 hover:bg-cyan-400/15"
                  >
                    {reprocessFlowExpanded ? 'Collapse' : 'Expand'}
                  </button>
                </div>
              )}
            </div>
            {reprocessFlowExpanded ? (
              <>
                <div className="mt-4 grid gap-2 md:grid-cols-4">
                  {REPROCESS_STAGES.map(stage => {
                    const status = reprocessCurrent === null && !reprocessSummary
                      ? 'idle'
                      : stageStatus(reprocessCurrent?.stage ?? null, stage, Boolean(reprocessSummary))
                    return (
                      <div
                        key={stage}
                        className={`rounded-xl border px-3 py-3 transition-colors ${status === 'idle' ? 'border-zinc-800 bg-zinc-900/40 text-zinc-600' : stageClasses(status)}`}
                      >
                        <div className="text-[11px] uppercase tracking-[0.18em]">Stage</div>
                        <div className={`mt-1 text-sm font-semibold ${status === 'idle' ? 'text-zinc-500' : ''}`}>{stageLabel(stage)}</div>
                        <div className="mt-1 text-[11px]">
                          {status === 'done' ? 'Completed' : status === 'active' ? 'Running now' : status === 'idle' ? 'Standby' : 'Waiting'}
                        </div>
                      </div>
                    )
                  })}
                </div>
                <div className="mt-4 grid gap-3 xl:grid-cols-[1.4fr_1fr]">
                  <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
                    <div className="mb-2 text-sm font-semibold text-white">Live Event Feed</div>
                    <div className="space-y-2">
                      {reprocessFeed.length === 0 ? (
                        <div className="text-xs text-zinc-500">No events yet. Start a reprocess task to see logs here.</div>
                      ) : (
                        reprocessFeed.map(item => (
                          <div key={item.id} className={`flex items-start gap-2 rounded-xl border px-3 py-2 text-xs ${feedClasses(item.kind)}`}>
                            <span className="rounded-full border border-current/20 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em]">
                              {feedBadge(item.kind)}
                            </span>
                            <span>{item.text}</span>
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                  <div className="rounded-xl border border-zinc-800 bg-zinc-900/60 p-3">
                    <div className="mb-2 text-sm font-semibold text-white">Run Notes</div>
                    <div className="space-y-2 text-xs text-zinc-400">
                      <p>Each source goes through: loading source, auto-tagging, parsing, and chunk rebuild.</p>
                      <p>Pending review rows are re-evaluated too, so the latest issue-first rules can auto-drop non-issues.</p>
                      <p>Single-document Reprocess uses the exact same pipeline, so tags can be safely re-run without re-uploading.</p>
                      {reprocessSummary?.failed.length ? (
                        <p className="text-rose-300">Failures stay listed in the browser console and the final summary.</p>
                      ) : reprocessSummary ? (
                        <p className="text-emerald-300">No failures recorded in the latest completed run.</p>
                      ) : null}
                    </div>
                  </div>
                </div>
              </>
            ) : (
              <div className="mt-4 rounded-xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <div className="text-sm font-semibold text-white">Run Summary</div>
                    <div className="mt-1 text-xs text-zinc-300">
                      {reprocessSummary?.failed.length
                        ? `Finished with ${reprocessSummary.failed.length} failed source${reprocessSummary.failed.length === 1 ? '' : 's'}. Expand to inspect the event feed.`
                        : 'Finished cleanly. Expand to inspect the event feed and stage history.'}
                    </div>
                  </div>
                  <div className="inline-flex items-center gap-2 rounded-full border border-emerald-400/20 bg-emerald-400/10 px-3 py-1 text-[11px] uppercase tracking-[0.18em] text-emerald-200">
                    <span className="h-2 w-2 rounded-full bg-emerald-300 shadow-[0_0_10px_rgba(110,231,183,0.75)]" />
                    Archived as summary card
                  </div>
                </div>
                {latestReprocessFeedItem && (
                  <div className={`mt-3 flex items-start gap-2 rounded-xl border px-3 py-2 text-xs ${feedClasses(latestReprocessFeedItem.kind)}`}>
                    <span className="rounded-full border border-current/20 px-2 py-0.5 text-[10px] uppercase tracking-[0.18em]">
                      {latestReprocessFeedItem.kind === 'error' ? 'Latest failure' : latestReprocessFeedItem.kind === 'success' ? 'Latest success' : 'Latest event'}
                    </span>
                    <span>{latestReprocessFeedItem.text}</span>
                  </div>
                )}
              </div>
            )}
          </div>
          {processingLabel && <p className="mt-3 text-sm text-emerald-400">{processingLabel}</p>}
          {message && <p className="mt-3 text-sm text-zinc-400">{message}</p>}
          {loading && <p className="mt-3 text-sm text-emerald-500">Loading...</p>}
        </section>
      </div>

      <div className="overflow-x-auto rounded-xl border border-zinc-800 bg-zinc-900">
        <table className="w-full text-sm">
          <thead className="bg-zinc-900/50 text-left text-xs uppercase tracking-wide text-zinc-400">
            <tr>
              <th className="w-10 px-3 py-3">
                <input
                  type="checkbox"
                  aria-label="Select all visible videos"
                  checked={docs.length > 0 && selectedVisibleDocIds.length === docs.length}
                  onChange={event => setSelectedDocIds(event.target.checked ? new Set(docs.map(doc => doc.doc_id)) : new Set())}
                  disabled={docActionsBusy || docs.length === 0}
                  className="h-4 w-4 accent-emerald-500"
                />
              </th>
              <th className="px-3 py-3">Code</th>
              <th className="px-3 py-3">Title</th>
              <th className="px-3 py-3">Category</th>
              <th className="px-3 py-3">Sprint</th>
              <th className="px-3 py-3 text-right">Chunks</th>
              <th className="px-3 py-3">Last processed</th>
              <th className="px-3 py-3">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100">
            {docs.map(doc => (
              <tr key={doc.doc_id} className="hover:bg-zinc-900/50">
                <td className="px-3 py-3">
                  <input
                    type="checkbox"
                    aria-label={`Select ${doc.title}`}
                    checked={selectedDocIds.has(doc.doc_id)}
                    onChange={() => setSelectedDocIds(current => {
                      const next = new Set(current)
                      if (next.has(doc.doc_id)) next.delete(doc.doc_id)
                      else next.add(doc.doc_id)
                      return next
                    })}
                    disabled={docActionsBusy}
                    className="h-4 w-4 accent-emerald-500"
                  />
                </td>
                <td className="px-3 py-3 font-mono text-xs text-emerald-400">{doc.code}</td>
                <td className="px-3 py-3">{doc.title}</td>
                <td className="px-3 py-3">
                  <button onClick={() => void handleEditCategory(doc)} className="rounded-full bg-emerald-500/20 px-2 py-1 text-xs text-emerald-400">
                    {doc.category}
                  </button>
                </td>
                <td className="px-3 py-3">
                  <button onClick={() => void handleEditSprint(doc)} className="rounded-full bg-amber-50 px-2 py-1 text-xs text-amber-700">
                    {doc.sprint || 'Set sprint'}
                  </button>
                </td>
                <td className="px-3 py-3 text-right text-zinc-400">{doc.chunk_count}</td>
                <td className="whitespace-nowrap px-3 py-3 text-xs text-zinc-400">
                  {doc.last_processed_at ? new Date(doc.last_processed_at).toLocaleString() : 'Not recorded'}
                </td>
                <td className="px-3 py-3 space-x-3 text-xs">
                  <button onClick={() => void handleViewChunks(doc)} disabled={docActionsBusy} className="text-zinc-400 hover:underline disabled:cursor-not-allowed disabled:opacity-60">{activeDocAction.docId === doc.doc_id && activeDocAction.action === '' ? 'Loading...' : 'View chunks'}</button>
                  <button onClick={() => void handleReprocessDoc(doc)} disabled={docActionsBusy} className="text-emerald-400 hover:underline disabled:cursor-not-allowed disabled:opacity-60">{activeDocAction.docId === doc.doc_id && activeDocAction.action === 'reprocess' ? 'Reprocessing...' : 'Reprocess'}</button>
                  <button onClick={() => void handleDelete(doc)} disabled={docActionsBusy} className="text-red-600 hover:underline disabled:cursor-not-allowed disabled:opacity-60">{activeDocAction.docId === doc.doc_id && activeDocAction.action === 'delete' ? 'Deleting...' : 'Delete'}</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {chunkDoc && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={() => setChunkDoc(null)}>
          <div className="flex h-full w-[720px] flex-col bg-zinc-900 shadow-xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
              <div>
                <div className="font-mono text-xs text-emerald-400">{chunkDoc.doc.code}</div>
                <h2 className="text-lg font-semibold text-white">{chunkDoc.doc.title}</h2>
                <div className="mt-1 text-xs text-zinc-400">
                  Last chunk rebuild: {latestChunkRebuildTime(chunkDoc.chunks) ? new Date(latestChunkRebuildTime(chunkDoc.chunks)).toLocaleString() : 'Not recorded'}
                </div>
              </div>
              <button onClick={() => setChunkDoc(null)} className="text-zinc-400 hover:text-zinc-300">Close</button>
            </div>
            <div className="flex-1 space-y-3 overflow-y-auto p-5">
              {chunkDoc.chunks.map(chunk => (
                <div key={chunk.chunk_id} className="rounded-xl border border-zinc-800 p-4">
                  <div className="mb-3 flex flex-wrap items-center gap-2">
                    <div className="font-mono text-xs text-gray-400">{chunk.chunk_id}</div>
                    {chunk.metadata.sheet && (
                      <span className="rounded-full bg-purple-100 px-2 py-0.5 text-xs font-medium text-purple-700">
                        📑 {chunk.metadata.sheet}
                      </span>
                    )}
                    {chunk.metadata.row_key && (
                      <span className="rounded-full bg-emerald-500/20 px-2 py-0.5 text-xs font-medium text-emerald-400">
                        🔢 {chunk.metadata.row_key}
                      </span>
                    )}
                    {chunk.metadata.row_index !== undefined && (
                      <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400">
                        Line {chunk.metadata.row_index}
                      </span>
                    )}
                    {chunk.metadata.category_tag && (
                      <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700">
                        {chunk.metadata.category_tag}
                      </span>
                    )}
                    {String(chunk.metadata.is_noise || '').toLowerCase() === 'yes' && (
                      <span className="rounded-full bg-rose-100 px-2 py-0.5 text-xs text-rose-700">
                        Noise
                      </span>
                    )}
                    {chunk.metadata.detail_tags && (
                      <span className="text-xs text-zinc-400">
                        {String(chunk.metadata.detail_tags).split(',').filter(Boolean).map(tag => (
                          <span key={tag} className="ml-1 rounded bg-amber-100 px-1.5 py-0.5 text-amber-700">
                            {tag.trim()}
                          </span>
                        ))}
                      </span>
                    )}
                    {chunk.metadata.processed_at && (
                      <span className="rounded-full bg-zinc-800 px-2 py-0.5 text-xs text-zinc-400" title="Processing Time">
                        🕒 {new Date(String(chunk.metadata.processed_at)).toLocaleString()}
                      </span>
                    )}
                    {chunk.metadata.row_key && (
                      <button
                        onClick={() => void handleEditChunkRow(chunk)}
                        className="ml-auto rounded-lg bg-zinc-800 px-2 py-1 text-xs font-medium text-white hover:bg-zinc-700"
                      >
                        Edit tag
                      </button>
                    )}
                  </div>
                  <pre className="whitespace-pre-wrap text-xs leading-relaxed text-zinc-300">{chunk.text}</pre>
                  <details className="mt-3 rounded-lg border border-zinc-800 bg-zinc-950/60">
                    <summary className="cursor-pointer select-none px-3 py-2 text-xs font-medium text-zinc-300 hover:text-white">
                      Debug details
                    </summary>
                    <div className="border-t border-zinc-800 p-3">
                      <dl className="grid gap-x-4 gap-y-2 text-xs sm:grid-cols-2">
                        {[
                          ['Chunk ID', chunk.chunk_id],
                          ['Document ID', chunk.metadata.doc_id],
                          ['Video code', chunk.metadata.video_code],
                          ['Language', chunk.metadata.language],
                          ['Sheet', chunk.metadata.sheet],
                          ['Row key', chunk.metadata.row_key],
                          ['Row index', chunk.metadata.row_index],
                          ['Category', chunk.metadata.category],
                          ['Sprint', chunk.metadata.sprint],
                          ['Is issue', chunk.metadata.is_issue],
                          ['Issue type', chunk.metadata.issue_type],
                          ['Issue summary', chunk.metadata.issue_summary],
                          ['Owner', chunk.metadata.owner],
                          ['Status', chunk.metadata.status],
                          ['Confidence', chunk.metadata.confidence],
                          ['Word count', chunk.metadata.word_count],
                          ['Processed at', chunk.metadata.processed_at],
                        ].map(([label, value]) => (
                          <div key={String(label)} className="grid grid-cols-[110px_minmax(0,1fr)] gap-2">
                            <dt className="text-zinc-500">{label}</dt>
                            <dd className="break-words font-mono text-zinc-300">{value === undefined || value === null || value === '' ? '-' : String(value)}</dd>
                          </div>
                        ))}
                      </dl>
                      <div className="mt-3 border-t border-zinc-800 pt-3">
                        <div className="mb-2 text-[11px] font-medium uppercase tracking-wide text-zinc-500">Raw chunk JSON</div>
                        <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded-md bg-black/30 p-3 text-[11px] leading-relaxed text-zinc-400">
                          {JSON.stringify({ chunk_id: chunk.chunk_id, text: chunk.text, metadata: chunk.metadata }, null, 2)}
                        </pre>
                      </div>
                    </div>
                  </details>
                  {editingChunkRowId === makeSelectedRowId(chunkDoc.doc.doc_id, String(chunk.metadata.row_key || '')) && (
                    <div className="mt-3 rounded-xl border border-gray-100 bg-zinc-900/50 p-3">
                      {editingChunkRowTag ? (
                        <ReviewRowEditor
                          row={{
                            doc_id: chunkDoc.doc.doc_id,
                            row_key: String(chunk.metadata.row_key || ''),
                            title: chunkDoc.doc.title,
                            code: chunkDoc.doc.code,
                            sprint: chunkDoc.doc.sprint,
                            category: chunkDoc.doc.category,
                            category_tag: String(chunk.metadata.category_tag || ''),
                            detail_tags: String(chunk.metadata.detail_tags || '').split(',').map(tag => tag.trim()).filter(Boolean),
                            confidence: Number(chunk.metadata.confidence || 0),
                            review_reason: '',
                            rationale: String(chunk.metadata.rationale || ''),
                            tags: String(chunk.metadata.tags || '').split(',').map(tag => tag.trim()).filter(Boolean),
                            is_noise: String(chunk.metadata.is_noise || '').toLowerCase() === 'yes',
                            text: chunk.text,
                            context_before: [],
                            context_after: [],
                          }}
                          value={editingChunkRowTag}
                          knownTags={knownCategoryTags}
                          knownDetailTags={knownDetailTags}
                          onClose={() => {
                            setEditingChunkRowId(null)
                            setEditingChunkRowTag(null)
                          }}
                          onChange={async next => {
                            await handleSaveChunkRow(chunk, next)
                          }}
                        />
                      ) : (
                        <div className="text-xs text-zinc-400">Loading saved chunk tag...</div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {taxonomyOpen && tagTaxonomy && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/30" onClick={() => setTaxonomyOpen(false)}>
          <div className="flex h-full w-[760px] flex-col bg-zinc-900 shadow-xl" onClick={e => e.stopPropagation()}>
            <div className="flex items-center justify-between border-b border-zinc-800 px-5 py-4">
              <div>
                <div className="font-mono text-xs text-emerald-400">Controlled tag taxonomy</div>
                <h2 className="text-lg font-semibold text-white">Standardize detail tags</h2>
                <p className="mt-1 text-xs text-zinc-400">Keep broad categories fixed, then merge new detail tags into a small controlled set.</p>
              </div>
              <button onClick={() => setTaxonomyOpen(false)} className="text-zinc-400 hover:text-zinc-300">Close</button>
            </div>
            <div className="flex-1 space-y-5 overflow-y-auto p-5">
              <div className="grid gap-3 sm:grid-cols-2">
                {Object.entries(tagTaxonomy.categories).map(([category, tags]) => (
                  <div key={category} className="rounded-xl border border-zinc-800 bg-zinc-900/50 p-3">
                    <div className="mb-2 text-sm font-semibold text-white">{category}</div>
                    <div className="flex flex-wrap gap-1">
                      {tags.map(tag => (
                        <span key={tag} className="rounded-full bg-zinc-900 px-2 py-1 text-xs text-zinc-300 ring-1 ring-zinc-700">{tag}</span>
                      ))}
                    </div>
                  </div>
                ))}
              </div>

              <div>
                <div className="mb-2 flex items-end justify-between">
                  <div>
                    <h3 className="text-sm font-semibold text-white">Candidate detail tags</h3>
                    <p className="text-xs text-zinc-400">These are saved tags outside the controlled set. Merge them instead of deleting data.</p>
                  </div>
                  <button
                    onClick={() => void refreshTaxonomy()}
                    disabled={taxonomyBusy}
                    className="rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-3 py-1.5 text-xs text-zinc-300 disabled:opacity-50"
                  >
                    {taxonomyBusy ? 'Refreshing...' : 'Refresh candidates'}
                  </button>
                </div>
                {tagTaxonomy.candidates.length === 0 ? (
                  <div className="rounded-xl bg-green-50 p-4 text-sm text-green-700">No loose detail tags right now. Tiny taxonomy goblin is pleased.</div>
                ) : (
                  <div className="space-y-2">
                    {tagTaxonomy.candidates.map(candidate => {
                      const draft = taxonomyDrafts[candidate.tag] || {
                        category: 'Translation',
                        toTag: tagTaxonomy.categories.Translation?.[0] || '',
                      }
                      const categoryTags = tagTaxonomy.categories[draft.category] || []
                      const targetListId = `taxonomy-target-${makeDomId(candidate.tag)}`
                      return (
                        <div key={candidate.tag} className="rounded-xl border border-zinc-800 p-3">
                          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                            <div>
                              <span className="font-mono text-sm font-semibold text-white">{candidate.tag}</span>
                              <span className="ml-2 rounded-full bg-amber-50 px-2 py-0.5 text-xs text-amber-700">{candidate.count} rows</span>
                            </div>
                            <div className="text-xs text-zinc-400">
                              {Object.entries(candidate.categories).map(([category, count]) => `${category}: ${count}`).join(' · ') || 'No category signal'}
                            </div>
                          </div>
                          <div className="grid gap-2 sm:grid-cols-[160px_1fr_auto]">
                            <select
                              value={draft.category}
                              onChange={e => {
                                const category = e.target.value
                                setTaxonomyDrafts(current => ({
                                  ...current,
                                  [candidate.tag]: {
                                    category,
                                    toTag: tagTaxonomy.categories[category]?.[0] || '',
                                  },
                                }))
                              }}
                              className="rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-2 py-2 text-sm"
                            >
                              {Object.keys(tagTaxonomy.categories).map(category => (
                                <option key={category} value={category}>{category}</option>
                              ))}
                            </select>
                            <input
                              list={targetListId}
                              value={draft.toTag}
                              onChange={e => setTaxonomyDrafts(current => ({
                                ...current,
                                [candidate.tag]: { ...draft, toTag: e.target.value },
                              }))}
                              className="rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-2 py-2 text-sm"
                              placeholder="Target sub-tag"
                            />
                            <datalist id={targetListId}>
                              {categoryTags.map(tag => <option key={tag} value={tag} />)}
                            </datalist>
                            <button
                              onClick={() => void handleMergeDetailTag(candidate.tag)}
                              disabled={taxonomyBusy || !draft.toTag}
                              className="rounded-lg bg-emerald-500 px-3 py-2 text-sm font-medium text-zinc-950 hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-50"
                            >
                              {taxonomyBusy ? 'Applying...' : 'Apply'}
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

function ReviewRowEditor({
  row,
  value,
  knownTags,
  knownDetailTags,
  onClose,
  onChange,
  onRestore,
}: {
  row: ReviewQueueRow
  value: RowTag
  knownTags: string[]
  knownDetailTags: string[]
  onClose: () => void
  onChange: (value: RowTag) => Promise<void>
  onRestore?: (value: RowTag) => Promise<void>
}) {
  const [draft, setDraft] = useState<RowTag>(value)
  const [detailInput, setDetailInput] = useState('')
  const [submitMode, setSubmitMode] = useState<'save' | 'restore' | ''>('')

  const addDetailTag = () => {
    const next = detailInput.trim()
    if (!next) return
    setDraft(current => ({
      ...current,
      detail_tags: Array.from(new Set([...current.detail_tags, next])).slice(0, 5),
    }))
    setDetailInput('')
  }

  return (
    <div className="space-y-3 text-xs">
      <div className="font-semibold text-zinc-400">{row.code} · {row.row_key}</div>
      <div>
        <label className="mb-1 block font-semibold text-zinc-400">Broad tag</label>
        <select
          value={draft.category_tag}
          onChange={e => setDraft(current => ({
            ...current,
            tags: e.target.value ? [e.target.value] : [],
            category_tag: e.target.value,
          }))}
          className="w-full rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-2 py-2"
        >
          <option value="">Select...</option>
          {[...new Set([...BROAD_CATEGORY_OPTIONS, ...knownTags.filter(tag => BROAD_CATEGORY_OPTIONS.includes(tag as typeof BROAD_CATEGORY_OPTIONS[number]))])].map(tag => (
            <option key={tag} value={tag}>{tag}</option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-1 block font-semibold text-zinc-400">Detail tags</label>
        <div className="mb-2 flex flex-wrap gap-1">
          {draft.detail_tags.map(tag => (
            <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-emerald-500/10 px-2 py-0.5 text-[11px] text-emerald-400">
              {tag}
              <button onClick={() => setDraft(current => ({ ...current, detail_tags: current.detail_tags.filter(item => item !== tag) }))}>×</button>
            </span>
          ))}
        </div>
        <input
          list={`manage-detail-tags-${row.doc_id}-${row.row_key}`}
          value={detailInput}
          onChange={e => setDetailInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addDetailTag() } }}
          placeholder="Add detail tag"
          className="w-full rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-2 py-2"
        />
        <datalist id={`manage-detail-tags-${row.doc_id}-${row.row_key}`}>
          {knownDetailTags.map(tag => <option key={tag} value={tag} />)}
        </datalist>
      </div>
      <div>
        <label className="mb-1 block font-semibold text-zinc-400">Issue Source (Vendor)</label>
        <select
          value={draft.issue_source || ''}
          onChange={e => setDraft(current => ({ ...current, issue_source: e.target.value }))}
          className="w-full rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-2 py-2"
        >
          <option value="">Select...</option>
          {['LB', 'RWS', 'Toin', 'BAL', 'Source Asset'].map(src => (
            <option key={src} value={src}>{src}</option>
          ))}
        </select>
      </div>
      <div>
        <label className="mb-1 block font-semibold text-zinc-400">Confidence</label>
        <input
          type="number"
          min={0}
          max={1}
          step={0.01}
          value={draft.confidence}
          onChange={e => setDraft(current => ({ ...current, confidence: Number(e.target.value) }))}
          className="w-full rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-2 py-2"
        />
      </div>
      <label className="flex items-center gap-2 text-zinc-400">
        <input
          type="checkbox"
          checked={draft.review_required}
          onChange={e => setDraft(current => ({ ...current, review_required: e.target.checked }))}
        />
        Keep in human review queue
      </label>
      <label className="flex items-center gap-2 text-zinc-400">
        <input
          type="checkbox"
          checked={draft.is_noise}
          onChange={e => setDraft(current => ({
            ...current,
            is_noise: e.target.checked,
            excluded: e.target.checked ? true : current.excluded,
            review_required: e.target.checked ? false : current.review_required,
          }))}
        />
        Mark as noise (keep visible, exclude from search)
      </label>
      <div>
        <label className="mb-1 block font-semibold text-zinc-400">Review reason</label>
        <textarea
          value={draft.review_reason}
          onChange={e => setDraft(current => ({ ...current, review_reason: e.target.value }))}
          rows={2}
          placeholder="Why does this row need review or what changed?"
          className="w-full rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-2 py-2"
        />
      </div>
      <div>
        <label className="mb-1 block font-semibold text-zinc-400">Feedback note</label>
        <textarea
          value={draft.feedback_note}
          onChange={e => setDraft(current => ({ ...current, feedback_note: e.target.value }))}
          rows={3}
          placeholder="Write the human correction note for the wrong-answer notebook"
          className="w-full rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-2 py-2"
        />
      </div>
      <div>
        <label className="mb-1 block font-semibold text-zinc-400">Rationale</label>
        <textarea
          value={draft.rationale}
          onChange={e => setDraft(current => ({ ...current, rationale: e.target.value }))}
          rows={3}
          placeholder="Optional rationale"
          className="w-full rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-2 py-2"
        />
      </div>
      <div className="flex items-center justify-between">
        <button onClick={onClose} className="text-zinc-400 hover:text-zinc-300">Cancel</button>
        <div className="flex items-center gap-2">
          <button
            onClick={async () => {
              setSubmitMode('save')
              try {
                await onChange({
                  ...draft,
                  tags: draft.category_tag ? [draft.category_tag] : draft.tags,
                  detail_tags: draft.detail_tags.slice(0, 5),
                })
              } finally {
                setSubmitMode('')
              }
            }}
            disabled={submitMode !== ''}
            className="rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-3 py-1.5 font-medium text-zinc-300 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitMode === 'save' ? 'Saving...' : 'Save review'}
          </button>
          {onRestore && (
            <button
              onClick={async () => {
                setSubmitMode('restore')
                try {
                  await onRestore({
                    ...draft,
                    excluded: false,
                    tags: draft.category_tag ? [draft.category_tag] : draft.tags,
                    detail_tags: draft.detail_tags.slice(0, 5),
                  })
                } finally {
                  setSubmitMode('')
                }
              }}
              disabled={submitMode !== ''}
              className="rounded-lg bg-emerald-500 px-3 py-1.5 font-medium text-zinc-950 hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {submitMode === 'restore' ? 'Saving + syncing...' : 'Save + sync chunk'}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
