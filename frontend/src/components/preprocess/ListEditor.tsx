import { useState } from 'react'

export default function ListEditor({ label, value, onChange, placeholder }: {
  label: string; value: string[]; onChange: (v: string[]) => void; placeholder?: string
}) {
  const [input, setInput] = useState('')
  return (
    <div className="mb-2">
      <label className="block text-sm font-semibold text-white mb-2">{label}</label>
      <div className="flex flex-wrap gap-2 mb-2.5">
        {value.map((v, i) => (
          <span key={i} className="text-xs bg-zinc-800 text-zinc-300 border border-zinc-700 rounded-full px-2.5 py-1 flex items-center gap-1.5 transition-colors hover:border-zinc-500 hover:bg-zinc-700/50">
            <span className="font-medium tracking-tight">{v}</span>
            <button onClick={() => onChange(value.filter((_, j) => j !== i))}
              className="text-zinc-500 hover:text-white rounded-full w-4 h-4 flex items-center justify-center transition-colors font-bold">×</button>
          </span>
        ))}
      </div>
      <input type="text" value={input} onChange={e => setInput(e.target.value)}
        onKeyDown={e => {
          if (e.key === 'Enter' && input.trim()) {
            onChange([...value, input.trim()])
            setInput('')
          }
        }}
        placeholder={placeholder || 'type and press Enter'}
        className="w-full rounded-xl border border-zinc-800 px-3.5 py-2.5 text-sm text-white placeholder-zinc-600 focus:outline-none focus:ring-1 focus:ring-emerald-500 focus:border-emerald-500 transition-all bg-zinc-900" />
    </div>
  )
}
