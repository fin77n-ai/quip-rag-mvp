import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'

import {
  approveBatch,
  getDocTags,
  getKnownTags,
  getRules,
  parseFiles,
  previewFiles,
  resetRules,
  saveRules,
  setRowTag,
  streamPullQuipDocs,
  type DocTags,
  type FilterRules,
  type PreviewDoc,
  type RowTag,
} from '../../api/client'
import ListEditor from './ListEditor'
import ProcessedView from './ProcessedView'

interface Props {
  onIngested: () => void
}

type PullStatus = 'idle' | 'running' | 'completed' | 'stopped' | 'failed'

const PULL_STAGES = ['Fetching', 'Auto-tagging', 'Parsing', 'Indexing'] as const

function pullStageState(stage: typeof PULL_STAGES[number], activeStep: string | undefined, status: PullStatus) {
  const stageIndex = PULL_STAGES.indexOf(stage)
  const activeIndex = PULL_STAGES.indexOf(activeStep as typeof PULL_STAGES[number])
  if (status === 'completed' || activeStep === 'Saved') return 'done'
  if (activeIndex > stageIndex) return 'done'
  if (activeIndex === stageIndex && status === 'running') return 'active'
  return 'idle'
}

export default function PreviewTab({ onIngested }: Props) {
  const [rules, setRules] = useState<FilterRules | null>(null)
  const [files, setFiles] = useState<File[]>([])
  const [previews, setPreviews] = useState<PreviewDoc[]>([])
  const [selectedIdx, setSelectedIdx] = useState(0)
  const [loading, setLoading] = useState(false)
  const [pulling, setPulling] = useState(false)
  const [message, setMessage] = useState('')
  const [pullProgress, setPullProgress] = useState<{current: number, total: number, step: string, title?: string} | null>(null)
  const [pullStatus, setPullStatus] = useState<PullStatus>('idle')
  const [pullStatusDetail, setPullStatusDetail] = useState('')
  const [docTags, setDocTags] = useState<DocTags | null>(null)
  const [knownCategoryTags, setKnownCategoryTags] = useState<string[]>([])
  const [knownDetailTags, setKnownDetailTags] = useState<string[]>([])
  const [quickCategoryTag, setQuickCategoryTag] = useState('Translation')
  const [quipInput, setQuipInput] = useState('')
  const [sprintInput, setSprintInput] = useState('')
  const pullAbortRef = useRef<AbortController | null>(null)

  const currentPreview = previews[selectedIdx]

  const refreshKnownTags = useCallback(async () => {
    const result = await getKnownTags()
    setKnownCategoryTags(result.tags)
    setKnownDetailTags(result.detail_tags)
  }, [])

  useEffect(() => {
    getRules().then(setRules).catch(err => setMessage(`Failed to load rules: ${err.message}`))
    refreshKnownTags().catch(() => {})
  }, [refreshKnownTags])

  useEffect(() => {
    const current = previews[selectedIdx]
    if (!current?.doc_id || current.error) {
      setDocTags(null)
      return
    }
    getDocTags(current.doc_id).then(setDocTags).catch(() => setDocTags(null))
  }, [selectedIdx, previews])

  const runPreview = useCallback(async (nextFiles: File[]) => {
    if (!nextFiles.length) return
    setLoading(true)
    try {
      const result = await previewFiles(nextFiles)
      setFiles(nextFiles)
      setPreviews(result.docs)
      setRules(result.rules)
      setSelectedIdx(0)
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }, [])

  const handleFiles = async (nextFiles: File[]) => {
    const jsonFiles = nextFiles.filter(file => file.name.endsWith('.json'))
    await runPreview(jsonFiles)
  }

  const handlePullQuip = async () => {
    const urls = quipInput
      .split(/\s+/)
      .map(item => item.trim())
      .filter(Boolean)
    if (!urls.length) return

    setPulling(true)
    setPullStatus('running')
    setPullStatusDetail('Preparing Quip pull...')
    setMessage('')
    setPullProgress(null)

    const controller = new AbortController()
    pullAbortRef.current = controller
    const collectedDocs: PreviewDoc[] = []
    let collectedRules: FilterRules | null = null
    let streamError = ''

    try {
      await streamPullQuipDocs(urls, sprintInput || undefined, {
        onStart: parsed => {
          setPullProgress({ current: 0, total: parsed.total, step: 'Starting' })
          setPullStatusDetail(`Queued ${parsed.total} document(s).`)
        },
        onProgress: parsed => {
          const stepLabels: Record<string, string> = {
            fetching: 'Fetching',
            tagging: 'Auto-tagging',
            parsing: 'Parsing',
            ingesting: 'Indexing',
          }
          setPullProgress({
            current: Math.max(0, parsed.index - 1),
            total: parsed.total,
            step: stepLabels[parsed.step] || parsed.step,
            title: parsed.title,
          })
          setPullStatusDetail(parsed.title || parsed.thread_id || `Document ${parsed.index}`)
        },
        onDocComplete: parsed => {
          collectedDocs.push(parsed.doc)
          setPreviews([...collectedDocs])
          setPullProgress({
            current: parsed.index,
            total: parsed.total,
            step: 'Saved',
            title: parsed.doc.title,
          })
          setPullStatusDetail(`${parsed.doc.title}: indexed ${parsed.chunks} chunk(s).`)
        },
        onComplete: parsed => {
          collectedRules = parsed.rules
          setPullStatus('completed')
          setPullStatusDetail(`All ${collectedDocs.length} document(s) completed.`)
        },
        onError: parsed => {
          streamError = parsed.error
          setPullStatus('failed')
          setPullStatusDetail(parsed.error)
        },
      }, controller.signal)

      setPreviews(collectedDocs)
      if (collectedRules) setRules(collectedRules)
      setSelectedIdx(0)
      setQuipInput('')
      setMessage(`Pulled ${collectedDocs.length} document(s), auto-tagged, and indexed.`)
    } catch (err) {
      if (controller.signal.aborted) {
        setPullStatus('stopped')
        setPullStatusDetail(`Stopped by user. Kept ${collectedDocs.length} completed document(s).`)
        setMessage(`Pull stopped. Kept ${collectedDocs.length} completed document(s).`)
      } else {
        const detail = streamError || (err instanceof Error ? err.message : String(err))
        setPullStatus('failed')
        setPullStatusDetail(detail)
        setMessage(`Pull stopped on error. Kept ${collectedDocs.length} completed document(s).`)
      }
    } finally {
      setPreviews([...collectedDocs])
      setSelectedIdx(0)
      if (collectedDocs.length) {
        await refreshKnownTags().catch(() => {})
        onIngested()
      }
      if (pullAbortRef.current === controller) pullAbortRef.current = null
      setPulling(false)
    }
  }

  const handleStopPull = () => {
    if (!pullAbortRef.current) return
    setPullStatusDetail('Stopping after the current operation...')
    pullAbortRef.current.abort()
  }

  const handleSaveRules = async () => {
    if (!rules) return
    setLoading(true)
    try {
      const saved = await saveRules(rules)
      setRules(saved)
      if (files.length) {
        await runPreview(files)
      }
      setMessage('Rules saved.')
    } finally {
      setLoading(false)
    }
  }

  const handleResetRules = async () => {
    setLoading(true)
    try {
      const reset = await resetRules()
      setRules(reset)
      if (files.length) {
        await runPreview(files)
      }
      setMessage('Rules reset to defaults.')
    } finally {
      setLoading(false)
    }
  }

  const handleRowTagChange = async (rowKey: string, tag: RowTag) => {
    if (!currentPreview?.doc_id) return
    const updated = await setRowTag(currentPreview.doc_id, rowKey, {
      ...tag,
      excluded: false,
      is_noise: false,
    })
    setDocTags(updated)
    await refreshKnownTags()
  }

  const handleConfirmIngest = async () => {
    if (!files.length && !previews.length) {
      setMessage('Pull Quip documents or upload JSON files first.')
      return
    }
    if (!files.length) {
      setMessage('Quip-pulled documents are already ingested (auto-tagged and ready). Check Manage RAG tab.')
      return
    }
    setLoading(true)
    try {
      const parsed = await parseFiles(files)
      const result = await approveBatch(parsed.batch_id)
      setMessage(`Ingested ${result.ingested} docs${result.failed.length ? `, ${result.failed.length} failed.` : '.'}`)
      onIngested()
    } catch (err) {
      setMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  if (!rules) return <div className="p-8 text-sm text-zinc-400 font-medium">Loading rules...</div>

  return (
    <div className="flex flex-col h-full bg-zinc-950">
      <header className="px-10 pt-12 pb-8 flex items-center shrink-0">
        <div className="flex-1">
          <h1 className="text-3xl font-semibold tracking-tight text-white">Ingest & Define</h1>
          <p className="text-zinc-400 mt-2 text-sm">Upload or pull Quip documents to parse, chunk, and index.</p>
        </div>
      </header>

      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="px-10 pb-20 flex-1 flex flex-col gap-6 max-w-[1400px] w-full mx-auto">
        <div className="grid grid-cols-[1.3fr_1fr] gap-6">
          {/* Pull Box */}
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-6 shadow-[0_2px_8px_rgba(0,0,0,0.02)] space-y-4">
            <div className="flex items-center justify-between">
              <h2 className="text-base font-semibold text-white">Pull Directly From Quip</h2>
              <span className="text-xs text-zinc-400 uppercase tracking-wider font-medium">URL / Thread ID</span>
            </div>
            <textarea
              value={quipInput}
              onChange={e => setQuipInput(e.target.value)}
              rows={3}
              placeholder="Paste one or many Quip URLs / thread IDs, separated by spaces or new lines"
              className="w-full rounded-xl border border-zinc-800 px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all bg-zinc-950/50"
            />
            <div className="flex items-center gap-4">
              <input
                type="text"
                value={sprintInput}
                onChange={e => setSprintInput(e.target.value)}
                placeholder="Target Sprint (e.g. MS10) - Optional"
                className="w-1/2 rounded-xl border border-zinc-800 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all bg-zinc-950/50"
              />
            </div>
            <div className="flex items-center justify-between gap-4">
              <p className="text-xs text-zinc-400">Completed documents are saved immediately and remain available if the run stops.</p>
              <button
                onClick={handlePullQuip}
                disabled={pulling || !quipInput.trim()}
                className="shrink-0 rounded-lg bg-emerald-500 px-4 py-2 text-sm font-medium text-zinc-950 shadow-sm transition-colors hover:bg-emerald-400 disabled:opacity-40"
              >
                {pulling ? 'Pulling...' : 'Pull Quip'}
              </button>
            </div>
          {pullStatus !== 'idle' && pullProgress && (
            <div className="mt-2 space-y-4 rounded-xl border border-zinc-800 bg-zinc-950/50 p-4" aria-live="polite">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <div className="flex items-center gap-2 text-sm font-semibold text-white">
                    <span>{pullStatus === 'running' ? 'Pull in progress' : pullStatus === 'completed' ? 'Pull completed' : pullStatus === 'stopped' ? 'Pull stopped' : 'Pull failed'}</span>
                    <span className={`rounded-full border px-2 py-0.5 text-[10px] uppercase tracking-wider ${
                      pullStatus === 'completed'
                        ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                        : pullStatus === 'failed'
                          ? 'border-rose-500/30 bg-rose-500/10 text-rose-300'
                          : pullStatus === 'stopped'
                            ? 'border-amber-500/30 bg-amber-500/10 text-amber-300'
                            : 'border-cyan-400/30 bg-cyan-400/10 text-cyan-200'
                    }`}>
                      {pullStatus}
                    </span>
                  </div>
                  <div className="mt-1 max-w-xl truncate text-xs text-zinc-400">{pullStatusDetail}</div>
                </div>
                {pulling && (
                  <button
                    type="button"
                    onClick={handleStopPull}
                    className="shrink-0 rounded-lg border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-xs font-semibold text-rose-200 transition-colors hover:bg-rose-500/20"
                  >
                    Stop pull
                  </button>
                )}
              </div>
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs font-medium text-zinc-400">
                  <span>{pullProgress.step}</span>
                  <span>{pullProgress.current}/{pullProgress.total} completed</span>
                </div>
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-zinc-800">
                  <div
                    className={`h-full transition-all duration-300 ${pullStatus === 'failed' ? 'bg-rose-500' : pullStatus === 'stopped' ? 'bg-amber-400' : 'bg-emerald-500'}`}
                    style={{ width: `${pullProgress.total ? (pullProgress.current / pullProgress.total) * 100 : 0}%` }}
                  />
                </div>
              </div>
              <div className="grid grid-cols-4 gap-2">
                {PULL_STAGES.map(stage => {
                  const stageState = pullStageState(stage, pullProgress.step, pullStatus)
                  return (
                    <div
                      key={stage}
                      className={`rounded-lg border px-3 py-2 text-xs ${
                        stageState === 'done'
                          ? 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300'
                          : stageState === 'active'
                            ? 'border-cyan-400/40 bg-cyan-400/10 text-cyan-200'
                            : 'border-zinc-800 bg-zinc-900/70 text-zinc-500'
                      }`}
                    >
                      <div className="font-semibold">{stage}</div>
                      <div className="mt-1 text-[10px] uppercase tracking-wider">{stageState === 'done' ? 'Done' : stageState === 'active' ? 'Running' : 'Waiting'}</div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}
        </div>

        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white">Upload Local Quip JSON</h2>
            <span className="text-xs text-zinc-400">Preview before ingest</span>
          </div>
          <label className="flex min-h-[132px] cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed border-zinc-700 bg-zinc-800 text-center text-sm text-zinc-400 hover:border-zinc-600">
            <span>{files.length ? `${files.length} file(s) loaded` : 'Drop JSON files here or click to choose'}</span>
            <input
              type="file"
              multiple
              accept=".json"
              className="hidden"
              onChange={e => handleFiles(Array.from(e.target.files ?? []))}
            />
          </label>
        </div>
      </div>

      {message && <p className="text-sm text-zinc-400">{message}</p>}

      <div className="grid min-h-0 flex-1 grid-cols-[240px_1fr_340px] gap-3">
        <div className="overflow-y-auto rounded-xl border border-zinc-800 bg-zinc-900">
          <div className="border-b border-zinc-800 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-zinc-400">
            Preview Docs ({previews.length})
          </div>
          {previews.length === 0 ? (
            <div className="p-4 text-sm text-zinc-400">Pull Quip data or upload files to start.</div>
          ) : (
            <ul className="divide-y divide-zinc-800 text-sm">
              {previews.map((preview, index) => (
                <li
                  key={`${preview.doc_id}-${index}`}
                  onClick={() => setSelectedIdx(index)}
                  className={`cursor-pointer px-3 py-3 ${index === selectedIdx ? 'bg-zinc-800' : 'hover:bg-zinc-800'}`}
                >
                  <div className="font-medium text-white">{preview.title}</div>
                  <div className="mt-1 text-xs text-zinc-400">
                    rows {preview.table_rows_count ?? 0} · chars {(preview.total_chars ?? 0).toLocaleString()}
                  </div>
                  {preview.qc && (
                    <div className={`mt-2 inline-flex rounded-full px-2 py-0.5 text-[11px] ${
                      preview.qc.status === 'pass'
                        ? 'bg-green-100 text-green-700'
                        : preview.qc.status === 'warning'
                          ? 'bg-amber-100 text-amber-700'
                          : 'bg-red-100 text-red-700'
                    }`}>
                      QC {preview.qc.status}
                    </div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="min-h-0 overflow-y-auto rounded-xl border border-zinc-800 bg-zinc-900 p-4">
          {!currentPreview ? (
            <div className="flex h-full items-center justify-center text-sm text-zinc-400">No preview selected.</div>
          ) : currentPreview.error ? (
            <div className="text-sm text-red-600">{currentPreview.error}</div>
          ) : (
            <div className="space-y-4">
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h2 className="text-lg font-semibold text-white">{currentPreview.title}</h2>
                  <p className="text-xs text-zinc-400">
                    {currentPreview.table_rows_count ?? 0} table rows · {currentPreview.sections_count ?? 0} text sections
                  </p>
                </div>
                {currentPreview.qc && (
                  <div className={`rounded-lg px-3 py-2 text-xs ${
                    currentPreview.qc.status === 'pass'
                      ? 'bg-green-50 text-green-700'
                      : currentPreview.qc.status === 'warning'
                        ? 'bg-amber-50 text-amber-700'
                        : 'bg-red-50 text-red-700'
                  }`}>
                    <div className="font-semibold uppercase">Preview QC {currentPreview.qc.status}</div>
                    <div>{currentPreview.qc.summary}</div>
                  </div>
                )}
              </div>

              <div className="rounded-xl border border-zinc-800 bg-zinc-800 p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span className="font-semibold text-zinc-400">Quick brush:</span>
                  {(['Translation', 'Voice Over', 'Animation'] as const).map(tag => (
                    <button
                      key={tag}
                      onClick={() => setQuickCategoryTag(tag)}
                      className={`rounded-full px-3 py-1 ${
                        quickCategoryTag === tag ? 'bg-emerald-500 text-white' : 'bg-zinc-900 text-zinc-400'
                      }`}
                    >
                      {tag}
                    </button>
                  ))}
                  <span className="ml-auto text-zinc-400">Click a row to apply the selected tag.</span>
                </div>
              </div>

              <ProcessedView
                raw={currentPreview.sample_text || ''}
                docTags={docTags}
                knownTags={knownCategoryTags}
                knownDetailTags={knownDetailTags}
                activeTag={quickCategoryTag}
                onTagChange={handleRowTagChange}
              />
            </div>
          )}
        </div>

        {/* Right Sidebar - Rules & Actions */}
        <div className="flex flex-col gap-6 overflow-y-auto">
          {/* Rules Panel */}
          <div className="rounded-2xl border border-zinc-800 bg-zinc-900 shadow-[0_2px_8px_rgba(0,0,0,0.02)] flex flex-col min-h-0 flex-1">
            <div className="border-b border-zinc-800 px-4 py-3 text-xs font-bold uppercase tracking-wider text-zinc-400 sticky top-0 bg-zinc-900/90 backdrop-blur-sm z-10">
              Extraction Rules
            </div>
            <div className="flex-1 overflow-y-auto p-5 space-y-5">
              <ListEditor label="Exclude Sheets" value={rules.exclude_sheets} onChange={value => setRules({ ...rules, exclude_sheets: value })} />
              <ListEditor label="Include Columns" value={rules.include_columns} onChange={value => setRules({ ...rules, include_columns: value })} />
              <ListEditor label="Exclude Columns" value={rules.exclude_columns} onChange={value => setRules({ ...rules, exclude_columns: value })} />
              <ListEditor label="Exclude Row Patterns" value={rules.exclude_row_patterns} onChange={value => setRules({ ...rules, exclude_row_patterns: value })} />
              <ListEditor label="Exclude Section Headings" value={rules.exclude_section_headings} onChange={value => setRules({ ...rules, exclude_section_headings: value })} />
              <ListEditor label="Placeholder Chars" value={rules.placeholder_chars} onChange={value => setRules({ ...rules, placeholder_chars: value })} />
              <label className="flex items-center gap-2 text-sm text-zinc-400 font-medium cursor-pointer">
                <input
                  type="checkbox"
                  checked={rules.drop_empty_rows}
                  onChange={e => setRules({ ...rules, drop_empty_rows: e.target.checked })}
                  className="rounded border-zinc-700 text-emerald-400 focus:ring-indigo-500/20"
                />
                Drop empty / placeholder-only rows
              </label>
              <div className="space-y-2">
                <label className="block text-sm font-semibold text-white">Min Chunk Chars</label>
                <input
                  type="number"
                  value={rules.min_chunk_chars}
                  onChange={e => setRules({ ...rules, min_chunk_chars: Number(e.target.value) })}
                  className="w-full rounded-xl border border-zinc-800 px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all bg-zinc-950/50"
                />
              </div>
            </div>
          </div>

          <div className="flex flex-col gap-2.5 shrink-0 bg-zinc-900 p-5 rounded-2xl border border-zinc-800 shadow-[0_2px_8px_rgba(0,0,0,0.02)]">
            <button onClick={handleSaveRules} disabled={loading} className="w-full rounded-xl bg-zinc-800 px-4 py-2.5 text-sm font-medium text-white shadow-sm disabled:opacity-40 hover:bg-zinc-700 transition-colors">
              Save Rules
            </button>
            <button onClick={handleResetRules} disabled={loading} className="w-full rounded-xl bg-zinc-950 border border-zinc-800 px-4 py-2.5 text-sm font-medium text-zinc-400 shadow-sm disabled:opacity-40 hover:text-white hover:border-zinc-700 transition-colors">
              Reset Config
            </button>
            <hr className="my-2 border-zinc-800" />
            <button onClick={handleConfirmIngest} disabled={loading || !files.length} className="w-full rounded-xl bg-emerald-500 px-4 py-2.5 text-sm font-medium text-zinc-950 shadow-[0_0_15px_rgba(16,185,129,0.2)] disabled:opacity-40 hover:bg-emerald-400 transition-all">
              Confirm & Ingest Uploads
            </button>
          </div>
        </div>
      </div>
    </motion.div>
    </div>
  )
}
