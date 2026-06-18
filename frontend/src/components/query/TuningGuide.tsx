interface Preset {
  emoji: string
  name: string
  desc: string
  example: string
  topK: number
  lambda: number
}

const PRESETS: Preset[] = [
  {
    emoji: '🎯',
    name: '查具体事实',
    desc: '问"某个按钮在哪""某个流程怎么走"这种有标准答案的问题',
    example: 'SOS 按钮在哪里？',
    topK: 3, lambda: 0.9,
  },
  {
    emoji: '📋',
    name: '总结某主题',
    desc: '汇总跨文档的某个话题，需要广度但不要太散',
    example: '总结所有 SOS 相关功能',
    topK: 10, lambda: 0.5,
  },
  {
    emoji: '🔄',
    name: '跨文档对比',
    desc: '对比多个文档/sprint 的差异，强制多样性',
    example: 'MS 和 VSD 流程有什么不同？',
    topK: 15, lambda: 0.3,
  },
  {
    emoji: '🌐',
    name: '中英混搭',
    desc: '问题和文档语言不一致，加大候选池让 reranker 多看几个',
    example: '紧急功能 emergency feature 是什么',
    topK: 8, lambda: 0.6,
  },
  {
    emoji: '🔬',
    name: '深挖单篇',
    desc: '只想从特定一篇里找信息（建议同时用 sprint/category 过滤）',
    example: 'MS0005 文档里写了什么注意事项？',
    topK: 8, lambda: 0.95,
  },
  {
    emoji: '🗺️',
    name: '探索性',
    desc: '不确定要问什么，先看库里有啥相关内容',
    example: '关于卫星通信的所有内容',
    topK: 12, lambda: 0.2,
  },
]


interface Props {
  open: boolean
  onClose: () => void
  onApply: (topK: number, lambda: number) => void
}

export default function TuningGuide({ open, onClose, onApply }: Props) {
  if (!open) return null

  return (
    <div className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4" onClick={onClose}>
      <div className="bg-zinc-900 rounded-xl shadow-2xl max-w-4xl w-full max-h-[90vh] flex flex-col" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
          <h2 className="font-bold text-lg">💡 调参指南 & 一键预设</h2>
          <button onClick={onClose} className="text-gray-500 hover:text-zinc-300">✕</button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-6">
          {/* Quick explanation */}
          <div className="bg-emerald-500\/10 border border-blue-200 rounded-lg p-4 text-sm space-y-2">
            <p><strong>Top-K</strong>：检索回来几块 chunk（不是几个文档！）。多 = 信息全但慢。</p>
            <p><strong>Diversity λ</strong>：1.0 = 纯相关性，0.0 = 纯多样性。低 = 强制覆盖多文档。</p>
            <p className="text-emerald-400"><strong>💡 不知道选啥？直接点下面对应场景的"Apply"按钮，自动调好。</strong></p>
          </div>

          {/* Presets grid */}
          <div className="grid grid-cols-2 gap-3">
            {PRESETS.map(p => (
              <div key={p.name} className="border border-gray-200 rounded-lg p-3 hover:border-blue-300 hover:bg-emerald-500\/10/30 transition-colors">
                <div className="flex items-center justify-between mb-2">
                  <span className="font-semibold text-sm">{p.emoji} {p.name}</span>
                  <button
                    onClick={() => { onApply(p.topK, p.lambda); onClose() }}
                    className="text-xs px-2.5 py-1 bg-emerald-500 text-white rounded hover:bg-emerald-400">
                    Apply
                  </button>
                </div>
                <p className="text-xs text-gray-600 mb-2">{p.desc}</p>
                <p className="text-xs text-gray-400 italic mb-2">例：{p.example}</p>
                <div className="flex gap-3 text-xs">
                  <span className="font-mono bg-zinc-800 px-1.5 py-0.5 rounded">Top-K: {p.topK}</span>
                  <span className="font-mono bg-zinc-800 px-1.5 py-0.5 rounded">λ: {p.lambda}</span>
                </div>
              </div>
            ))}
          </div>

          {/* Asking tips */}
          <div>
            <h3 className="font-semibold text-sm mb-2">🗣️ 提问技巧</h3>
            <ul className="text-sm text-zinc-300 space-y-1.5 list-disc pl-5">
              <li><strong>具体优于笼统</strong>："SOS 在卫星模式下怎么用" 比 "SOS 怎么用" 准</li>
              <li><strong>包含关键词</strong>：把文档里出现过的术语放进问题里（如 code <code className="bg-zinc-800 px-1 rounded text-xs">MS0005</code>、专有名词）</li>
              <li><strong>一次问一件事</strong>：复杂多步问题拆开问，比一次塞五个问题准得多</li>
              <li><strong>跨语言可以混搭</strong>：bge-m3 能跨中英匹配，问题"emergency 紧急功能"也行</li>
              <li><strong>先看引用再信答案</strong>：Gemini 偶尔会脑补，看引用列表对得上才放心</li>
            </ul>
          </div>

          {/* Troubleshooting */}
          <div>
            <h3 className="font-semibold text-sm mb-2">🚨 常见问题</h3>
            <table className="w-full text-sm border-collapse">
              <thead className="text-xs text-gray-500">
                <tr className="border-b">
                  <th className="text-left py-1.5 w-1/3">症状</th>
                  <th className="text-left py-1.5">怎么修</th>
                </tr>
              </thead>
              <tbody className="text-zinc-300">
                <tr className="border-b">
                  <td className="py-1.5">引用全来自一篇文档</td>
                  <td className="py-1.5">把 λ 调到 0.3-0.5（多样性）</td>
                </tr>
                <tr className="border-b">
                  <td className="py-1.5">答案空洞、抓不到细节</td>
                  <td className="py-1.5">增大 Top-K 到 10-15</td>
                </tr>
                <tr className="border-b">
                  <td className="py-1.5">完全找不到应该有的内容</td>
                  <td className="py-1.5">用更具体的关键词；或去 Manage Tab 确认文档已入库</td>
                </tr>
                <tr className="border-b">
                  <td className="py-1.5">529 Rate limit 错误</td>
                  <td className="py-1.5">等几分钟（Google 上游限流）；减小 Top-K</td>
                </tr>
                <tr>
                  <td className="py-1.5">中英问题答得不准</td>
                  <td className="py-1.5">问题里同时给中英文关键词；λ 调到 0.6</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* Footer */}
        <div className="px-6 py-3 border-t border-gray-200 bg-zinc-800\/50 text-xs text-gray-500 text-center">
          调参没有银弹 · 同一类问题多试 2 次找到甜区就好
        </div>
      </div>
    </div>
  )
}
