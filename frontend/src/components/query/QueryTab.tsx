import { useState } from 'react'
import { motion } from 'framer-motion'
import { SlidersHorizontal } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { queryRAG, type QueryMessage, type QueryResponse, type SimilarEvidenceGroup, type Stats } from '../../api/client'

interface Props {
  stats: Stats | null
}

export default function QueryTab({ stats }: Props) {
  const [question, setQuestion] = useState('')
  const [selectedCategories, setSelectedCategories] = useState<string[]>([])
  const [selectedSprints, setSelectedSprints] = useState<string[]>([])
  const [selectedTags, setSelectedTags] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [response, setResponse] = useState<QueryResponse | null>(null)
  const [conversation, setConversation] = useState<QueryMessage[]>([])
  const [error, setError] = useState('')
  const [statusMsg, setStatusMsg] = useState('')
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({})

  const categories = Object.keys(stats?.by_category || {})
  const sprints = Object.keys(stats?.by_sprint || {}).filter(sprint => sprint !== '(unassigned)')
  const tags = Object.keys(stats?.by_tag || {})

  const toggle = (value: string, current: string[], setter: (next: string[]) => void) => {
    setter(current.includes(value) ? current.filter(item => item !== value) : [...current, value])
  }

  const handleSubmit = async () => {
    if (!question.trim()) return
    setLoading(true)
    setError('')
    setStatusMsg('')
    const askedQuestion = question.trim()
    try {
      const next = await queryRAG(
        askedQuestion,
        {
          categories: selectedCategories.length ? selectedCategories : undefined,
          sprints: selectedSprints.length ? selectedSprints : undefined,
          tags: selectedTags.length ? selectedTags : undefined,
        },
        conversation,
        12,
        undefined,
        (chunk) => {
          if (chunk.type === 'status') {
            setStatusMsg(chunk.message)
          } else if (chunk.type === 'error') {
            setStatusMsg(`Error: ${chunk.detail || chunk.message || 'Query failed'}`)
          }
        }
      )
      setResponse(next)
      setConversation(current => [
        ...current,
        { role: 'user', content: askedQuestion },
        { role: 'assistant', content: next.answer },
      ])
      setQuestion('')
      setOpenGroups({})
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err)
      setError(message)
      setStatusMsg(`Error: ${message}`)
    } finally {
      setLoading(false)
    }
  }

  return (
    <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="mx-auto max-w-5xl space-y-6 pb-20">
      <div className="bg-zinc-900 rounded-2xl border border-zinc-800 shadow-[0_2px_8px_rgba(0,0,0,0.02)] p-6 space-y-5">
        <div className="border-b border-zinc-800 pb-3 mb-2 flex items-center gap-2">
          <div className="p-1.5 bg-emerald-500/10 text-emerald-400 rounded-lg"><SlidersHorizontal className="w-4 h-4"/></div>
          <h2 className="text-sm font-semibold text-white">Search Filters</h2>
        </div>
        <FilterRow label="Category" values={categories} selected={selectedCategories} onToggle={value => toggle(value, selectedCategories, setSelectedCategories)} counts={stats?.by_category || {}} />
        <FilterRow label="Sprint" values={sprints} selected={selectedSprints} onToggle={value => toggle(value, selectedSprints, setSelectedSprints)} counts={stats?.by_sprint || {}} />
        <FilterRow label="Tag" values={tags} selected={selectedTags} onToggle={value => toggle(value, selectedTags, setSelectedTags)} counts={stats?.by_tag || {}} />
      </div>

      <div className="rounded-3xl border border-zinc-800 bg-zinc-900 shadow-[0_4px_16px_rgba(0,0,0,0.03)] p-2">
        {conversation.length > 0 && (
          <div className="mb-4 space-y-3 rounded-2xl bg-zinc-800/80 p-5 border border-zinc-800/80">
            <div className="flex items-center justify-between">
              <div className="text-[11px] font-bold uppercase tracking-wider text-zinc-400">Context Window</div>
              <button
                onClick={() => {
                  setConversation([])
                  setResponse(null)
                  setOpenGroups({})
                  setError('')
                }}
                className="text-xs font-semibold text-zinc-400 hover:text-white transition-colors bg-zinc-900 px-3 py-1.5 rounded-lg border border-zinc-800 shadow-sm"
              >
                Clear Context
              </button>
            </div>
            {conversation.map((message, index) => (
              <div key={`${message.role}-${index}`} className={`rounded-2xl px-5 py-3.5 text-sm leading-relaxed shadow-sm ${
                message.role === 'user'
                  ? 'bg-emerald-500 text-white ml-8 shadow-indigo-500/20'
                  : 'bg-zinc-900 text-zinc-400 border border-zinc-800 mr-8'
              }`}>
                <div className={`mb-1.5 text-[10px] font-bold uppercase tracking-wider ${message.role === 'user' ? 'text-indigo-200' : 'text-zinc-400'}`}>
                  {message.role === 'user' ? 'You' : 'RAG System'}
                </div>
                <div className="whitespace-pre-wrap">{message.content}</div>
              </div>
            ))}
          </div>
        )}
        <textarea
          value={question}
          onChange={e => setQuestion(e.target.value)}
          rows={3}
          placeholder={conversation.length > 0 ? 'Follow up, for example: does the French issue belong to Voice Over or Translation?' : 'Ask anything. Filter the corpus above, and I will search, summarize, and cite the exact source rows...'}
          className="w-full resize-none bg-transparent px-5 py-3 text-[15px] outline-none placeholder:text-zinc-400 text-white"
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              void handleSubmit()
            }
          }}
        />
        <div className="flex items-center justify-between border-t border-zinc-800 px-4 py-3 bg-zinc-950/50 rounded-b-3xl">
          <div className="text-[11px] font-medium text-zinc-400 tracking-wide uppercase">
            {statusMsg ? (
              <span className={`flex items-center gap-2 ${error ? 'text-rose-400' : loading ? 'text-emerald-400' : 'text-zinc-300'}`}>
                <span className={`w-1.5 h-1.5 rounded-full ${error ? 'bg-rose-400' : loading ? 'bg-emerald-400 animate-pulse' : 'bg-zinc-400'}`} />
                {statusMsg}
              </span>
            ) : conversation.length > 0 ? (
              'Context preserved for follow-up.'
            ) : (
              'Semantic Search + MMR + Agent RAG'
            )}
          </div>
          <button onClick={handleSubmit} disabled={loading || !question.trim()} className="rounded-xl bg-zinc-800 px-5 py-2 text-sm font-semibold tracking-wide text-white disabled:opacity-40 hover:bg-zinc-700 transition-all shadow-sm">
            {loading ? 'Thinking...' : conversation.length > 0 ? 'Reply' : 'Search'}
          </button>
        </div>
      </div>

      {error && <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">{error}</div>}

      {response && (
        <>
          <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-5">
            <div className="mb-3 flex items-center justify-between">
              <div>
                <h2 className="text-lg font-semibold text-white">Answer</h2>
                <p className="text-xs text-zinc-400">
                  {response.elapsed_ms} ms · {response.debug.candidate_count} candidates · {response.debug.group_count} grouped issues
                </p>
              </div>
              {response.qc && (
                <div className={`rounded-full px-3 py-1 text-xs font-semibold ${
                  response.qc.status === 'pass'
                    ? 'bg-green-100 text-green-700'
                    : response.qc.status === 'warning'
                      ? 'bg-amber-100 text-amber-700'
                      : 'bg-red-100 text-red-700'
                }`}>
                  QC {response.qc.status}
                </div>
              )}
            </div>
            <div className="prose prose-invert max-w-none text-sm leading-7">
              <ReactMarkdown remarkPlugins={[remarkGfm]}>{response.answer}</ReactMarkdown>
            </div>
            {response.qc && response.qc.status !== 'pass' && (
              <details className="mt-4 rounded-xl border border-red-200 bg-red-50 p-4">
                <summary className="cursor-pointer text-sm font-semibold text-red-700">QC flagged this answer for human attention</summary>
                <div className="mt-3 space-y-2 text-sm text-red-700">
                  <p>{response.qc.summary}</p>
                  {response.qc.issues.map(issue => (
                    <div key={`${issue.type}-${issue.ref || issue.message}`}>
                      <span className="font-semibold">{issue.type}:</span> {issue.message}
                    </div>
                  ))}
                </div>
              </details>
            )}
          </section>

          <section className="space-y-3">
            <div className="text-xs font-semibold uppercase tracking-wide text-zinc-400">Evidence groups</div>
            {response.evidence_groups.map(group => (
              <EvidenceGroupCard
                key={group.group_id}
                group={group}
                open={Boolean(openGroups[group.group_id])}
                onToggle={() => setOpenGroups(current => ({ ...current, [group.group_id]: !current[group.group_id] }))}
              />
            ))}
          </section>
        </>
      )}
    </motion.div>
  )
}

function FilterRow({
  label,
  values,
  selected,
  onToggle,
  counts,
}: {
  label: string
  values: string[]
  selected: string[]
  onToggle: (value: string) => void
  counts: Record<string, number>
}) {
  if (!values.length) return null
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="w-20 text-xs font-semibold uppercase tracking-wide text-zinc-400">{label}</span>
      {values.map(value => (
        <button
          key={value}
          onClick={() => onToggle(value)}
          className={`rounded-full border px-3 py-1 text-xs ${
            selected.includes(value) ? 'border-blue-600 bg-emerald-500 text-white' : 'border-zinc-700 bg-zinc-900 text-zinc-400'
          }`}
        >
          {value} ({counts[value]})
        </button>
      ))}
    </div>
  )
}

function EvidenceGroupCard({
  group,
  open,
  onToggle,
}: {
  group: SimilarEvidenceGroup
  open: boolean
  onToggle: () => void
}) {
  return (
    <div className="rounded-2xl border border-zinc-800 bg-zinc-900 p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="text-sm font-semibold text-white">{group.label}</div>
          <div className="mt-1 text-xs text-zinc-400">
            Representative chunk [{group.representative.code}] · repeated {group.count} time{group.count === 1 ? '' : 's'}
          </div>
        </div>
        <button onClick={onToggle} className="text-xs text-emerald-500 hover:underline">
          {open ? 'Hide supporting evidence' : `Show ${group.supporting.length} supporting chunk${group.supporting.length === 1 ? '' : 's'}`}
        </button>
      </div>

      <div className="mt-3 rounded-xl bg-zinc-800 p-3">
        <div className="mb-1 text-xs font-semibold text-zinc-400">Representative evidence</div>
        <div className="text-xs text-zinc-400">{group.representative.title}</div>
        <div className="mt-2 whitespace-pre-wrap text-sm text-zinc-200">{group.representative.snippet}</div>
      </div>

      {open && group.supporting.length > 0 && (
        <div className="mt-3 space-y-2">
          {group.supporting.map(citation => (
            <div key={citation.chunk_id} className="rounded-xl border border-zinc-800 p-3">
              <div className="text-xs text-zinc-400">{citation.title} · [{citation.code}]</div>
              <div className="mt-1 whitespace-pre-wrap text-sm text-zinc-200">{citation.snippet}</div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
