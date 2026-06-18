import { useState } from 'react'

import type { DocTags, RowTag } from '../../api/client'

const BROAD_CATEGORY_OPTIONS = ['Animation', 'Translation', 'Voice Over'] as const
const SOURCE_OPTIONS = ['LB', 'RWS', 'Toin', 'BAL', 'Source Asset'] as const

interface Block {
  type: 'table' | 'text'
  sheet?: string
  rows?: string[][]
  text?: string
}

const TABLE_RE = /\[TABLE(?::\s*([^\]]+))?\]\s*\n([\s\S]*?)(?:\n\[\/TABLE\]|$)/g

function parseBlocks(raw: string): Block[] {
  const blocks: Block[] = []
  let lastIndex = 0
  let match: RegExpExecArray | null
  TABLE_RE.lastIndex = 0
  while ((match = TABLE_RE.exec(raw)) !== null) {
    if (match.index > lastIndex) {
      const text = raw.slice(lastIndex, match.index).trim()
      if (text) blocks.push({ type: 'text', text })
    }
    blocks.push({
      type: 'table',
      sheet: (match[1] || '').trim(),
      rows: parseTableBody(match[2]),
    })
    lastIndex = match.index + match[0].length
  }
  if (lastIndex < raw.length) {
    const text = raw.slice(lastIndex).trim()
    if (text) blocks.push({ type: 'text', text })
  }
  return blocks
}

function parseTableBody(body: string): string[][] {
  return body
    .split('\n')
    .map(line => line.trim())
    .filter(Boolean)
    .map(line => (line.includes('|') ? line.split('|').map(cell => cell.trim()) : [line]))
}

interface Props {
  raw: string
  docTags?: DocTags | null
  knownTags?: string[]
  knownDetailTags?: string[]
  activeTag?: string | null
  onTagChange?: (rowKey: string, tag: RowTag) => void | Promise<void>
}

export default function ProcessedView({
  raw,
  docTags,
  knownTags = [],
  knownDetailTags = [],
  activeTag,
  onTagChange,
}: Props) {
  const blocks = parseBlocks(raw)
  if (!blocks.length) {
    return <div className="rounded-xl border border-dashed border-gray-300 p-6 text-center text-sm text-gray-400">(empty after filtering)</div>
  }

  return (
    <div className="space-y-4">
      {blocks.map((block, index) => (
        block.type === 'table'
          ? (
            <TableCard
              key={`${block.sheet}-${index}`}
              sheet={block.sheet || '(untitled)'}
              rows={block.rows || []}
              docTags={docTags}
              knownTags={knownTags}
              knownDetailTags={knownDetailTags}
              activeTag={activeTag}
              onTagChange={onTagChange}
            />
            )
          : <TextBlock key={`text-${index}`} text={block.text || ''} />
      ))}
    </div>
  )
}

function TableCard({
  sheet,
  rows,
  docTags,
  knownTags,
  knownDetailTags,
  activeTag,
  onTagChange,
}: {
  sheet: string
  rows: string[][]
  docTags?: DocTags | null
  knownTags: string[]
  knownDetailTags: string[]
  activeTag?: string | null
  onTagChange?: (rowKey: string, tag: RowTag) => void | Promise<void>
}) {
  const [expanded, setExpanded] = useState(rows.length <= 8)
  const [editingRow, setEditingRow] = useState<string | null>(null)
  const header = rows[0] || []
  const body = expanded ? rows.slice(1) : rows.slice(1, 9)

  const quickApply = async (rowKey: string, current: RowTag) => {
    if (!onTagChange) return
    if (!activeTag) return
    await onTagChange(rowKey, {
      ...current,
      excluded: false,
      is_noise: false,
      tags: [activeTag],
      category_tag: activeTag,
      review_required: current.confidence < 0.8 || !current.detail_tags.length,
    })
  }

  return (
    <div className="overflow-hidden rounded-xl border border-zinc-800">
      <div className="flex items-center justify-between bg-zinc-900 border-b border-zinc-800 px-3 py-2 text-xs text-zinc-400">
        <span className="font-semibold">{sheet}</span>
        <span>{rows.length - 1} rows</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="border-b border-zinc-800 bg-zinc-950">
            <tr>
              <th className="px-2 py-2 text-left text-zinc-500 w-24">Tag</th>
              {header.map((cell, index) => (
                <th key={`${cell}-${index}`} className="px-2 py-2 text-left font-semibold text-zinc-300">{cell || '—'}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-zinc-800/50 bg-zinc-900">
            {body.map((row, index) => {
              const rowKey = `${sheet}::${index + 1}`
              const saved = docTags?.rows?.[rowKey]
              const current = {
                tags: [],
                category_tag: '',
                detail_tags: [],
                confidence: 0,
                rationale: '',
                review_required: false,
                review_reason: '',
                feedback_note: '',
                issue_source: '',
                ...saved,
                excluded: false,
                is_noise: false,
              }
              return (
                <tr
                  key={rowKey}
                  className={`hover:bg-zinc-800/50 ${activeTag ? 'cursor-pointer' : ''}`}
                  onClick={() => { void quickApply(rowKey, current) }}
                >
                  <td className="px-2 py-2 align-top" onClick={e => e.stopPropagation()}>
                    <button
                      onClick={() => setEditingRow(editingRow === rowKey ? null : rowKey)}
                      className={`text-[11px] font-medium tracking-wide ${
                        !(current.category_tag || current.tags[0])
                          ? 'bg-zinc-800 text-zinc-400 border border-zinc-700 px-2.5 py-1 rounded-full hover:text-white transition-colors'
                          : current.review_required
                            ? 'bg-amber-500 text-amber-950 px-2.5 py-1 rounded-full'
                            : 'bg-emerald-500 text-zinc-950 px-2.5 py-1 rounded-full'
                      }`}
                    >
                      {current.category_tag || current.tags[0] || 'set tag'}
                    </button>
                    {editingRow === rowKey && (
                      <TagEditor
                        rowKey={rowKey}
                        value={current}
                        knownTags={knownTags}
                        knownDetailTags={knownDetailTags}
                        onClose={() => setEditingRow(null)}
                        onChange={async next => {
                          await onTagChange?.(rowKey, next)
                          setEditingRow(null)
                        }}
                      />
                    )}
                  </td>
                  {row.map((cell, cellIndex) => (
                    <td key={`${rowKey}-${cellIndex}`} className="px-2 py-2 align-top">
                      <span className="block max-w-xs truncate text-zinc-300" title={cell}>{cell || '—'}</span>
                    </td>
                  ))}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {rows.length > 9 && (
        <div className="border-t border-zinc-800 bg-zinc-900/50 px-3 py-2 text-xs">
          <button onClick={() => setExpanded(value => !value)} className="text-emerald-500 hover:underline">
            {expanded ? 'Collapse rows' : `Show all ${rows.length - 1} rows`}
          </button>
        </div>
      )}
    </div>
  )
}

function TagEditor({
  rowKey,
  value,
  knownTags,
  knownDetailTags,
  onClose,
  onChange,
}: {
  rowKey: string
  value: RowTag
  knownTags: string[]
  knownDetailTags: string[]
  onClose: () => void
  onChange: (value: RowTag) => Promise<void>
}) {
  const [draft, setDraft] = useState<RowTag>(value)
  const [detailInput, setDetailInput] = useState('')

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
    <div className="absolute z-20 mt-2 w-72 rounded-xl border border-gray-200 bg-zinc-900 p-3 shadow-xl">
      <div className="mb-2 text-[11px] font-semibold text-gray-500">{rowKey}</div>
      <div className="space-y-3 text-xs">
        <div>
          <label className="mb-1 block font-semibold text-gray-600">Broad tag</label>
          <select
            value={draft.category_tag}
            onChange={e => setDraft(current => ({ ...current, tags: [e.target.value], category_tag: e.target.value }))}
            className="w-full rounded-lg border border-gray-300 px-2 py-2"
          >
            <option value="">Select...</option>
            {[...new Set([...BROAD_CATEGORY_OPTIONS, ...knownTags.filter(tag => BROAD_CATEGORY_OPTIONS.includes(tag as typeof BROAD_CATEGORY_OPTIONS[number]))])].map(tag => (
              <option key={tag} value={tag}>{tag}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block font-semibold text-gray-600">Detail tags</label>
          <div className="mb-2 flex flex-wrap gap-1">
            {draft.detail_tags.map(tag => (
              <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-emerald-500 text-zinc-950 font-bold px-2 py-0.5 text-[11px]">
                {tag}
                <button onClick={() => setDraft(current => ({ ...current, detail_tags: current.detail_tags.filter(item => item !== tag) }))}>×</button>
              </span>
            ))}
          </div>
          <input
            list={`detail-tags-${rowKey}`}
            value={detailInput}
            onChange={e => setDetailInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); addDetailTag() } }}
            placeholder="Add detail tag"
            className="w-full rounded-lg border border-gray-300 px-2 py-2"
          />
          <datalist id={`detail-tags-${rowKey}`}>
            {knownDetailTags.map(tag => <option key={tag} value={tag} />)}
          </datalist>
        </div>
        <div>
          <label className="mb-1 block font-semibold text-gray-600">Issue Source (Vendor)</label>
          <select
            value={draft.issue_source || ''}
            onChange={e => setDraft(current => ({ ...current, issue_source: e.target.value }))}
            className="w-full rounded-lg border border-zinc-700 bg-zinc-900 text-white placeholder-zinc-600 px-2 py-2"
          >
            <option value="">Select...</option>
            {SOURCE_OPTIONS.map(src => (
              <option key={src} value={src}>{src}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block font-semibold text-gray-600">Confidence</label>
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
        <label className="flex items-center gap-2 text-gray-600">
          <input
            type="checkbox"
            checked={draft.review_required}
            onChange={e => setDraft(current => ({ ...current, review_required: e.target.checked }))}
          />
          Needs human review
        </label>
        <textarea
          value={draft.review_reason}
          onChange={e => setDraft(current => ({ ...current, review_reason: e.target.value }))}
          rows={2}
          placeholder="Why should this be reviewed?"
          className="w-full rounded-lg border border-gray-300 px-2 py-2"
        />
        <textarea
          value={draft.feedback_note}
          onChange={e => setDraft(current => ({ ...current, feedback_note: e.target.value }))}
          rows={2}
          placeholder="Optional correction note for the feedback notebook"
          className="w-full rounded-lg border border-gray-300 px-2 py-2"
        />
        <div className="flex items-center justify-between">
          <button onClick={onClose} className="text-gray-500 hover:text-zinc-300">Cancel</button>
          <button
            onClick={() => onChange({
              ...draft,
              tags: draft.category_tag ? [draft.category_tag] : draft.tags,
              detail_tags: draft.detail_tags.slice(0, 5),
            })}
            className="rounded-lg bg-emerald-500 px-3 py-1.5 font-medium text-white"
          >
            Apply
          </button>
        </div>
      </div>
    </div>
  )
}

function TextBlock({ text }: { text: string }) {
  return <div className="rounded-xl border-l-4 border-gray-300 bg-zinc-800\/50 px-4 py-3 text-sm text-zinc-300 whitespace-pre-wrap">{text}</div>
}
