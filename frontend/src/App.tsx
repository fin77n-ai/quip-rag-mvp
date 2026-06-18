import { Component, Suspense, lazy, useState, useEffect, type ErrorInfo, type ReactNode } from 'react'
import { DEMO_MODE, getStats, type Stats } from './api/client'
import { LayoutDashboard, Database, SlidersHorizontal, MessageSquare, Box } from 'lucide-react'

type Tab = 'dashboard' | 'preview' | 'manage' | 'query'

const PreviewTab = lazy(() => import('./components/preprocess/PreviewTab'))
const QueryTab = lazy(() => import('./components/query/QueryTab'))
const ManageTab = lazy(() => import('./components/manage/ManageTab'))
const DashboardTab = lazy(() => import('./components/dashboard/DashboardTab').then(module => ({ default: module.DashboardTab })))

function TabLoading() {
  return (
    <div className="mx-auto max-w-6xl p-8" aria-label="Loading workspace">
      <div className="h-8 w-48 animate-pulse rounded-lg bg-zinc-800" />
      <div className="mt-6 grid gap-4 md:grid-cols-3">
        {[0, 1, 2].map(item => <div key={item} className="h-32 animate-pulse rounded-2xl bg-zinc-900" />)}
      </div>
    </div>
  )
}

class TabErrorBoundary extends Component<
  { children: ReactNode; name: string },
  { error: Error | null }
> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`${this.props.name} menu crashed`, error, info)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div className="flex h-full items-center justify-center p-8">
        <div className="max-w-md rounded-lg border border-rose-500/30 bg-zinc-900 p-5">
          <h2 className="font-semibold text-white">{this.props.name} could not render</h2>
          <p className="mt-2 text-sm text-zinc-400">Your other menus and their records are still available.</p>
          <button
            type="button"
            onClick={() => this.setState({ error: null })}
            className="mt-4 rounded-lg bg-emerald-500 px-3 py-2 text-sm font-medium text-zinc-950 hover:bg-emerald-400"
          >
            Retry this menu
          </button>
        </div>
      </div>
    )
  }
}

export default function App() {
  const [tab, setTab] = useState<Tab>('dashboard')
  const [visitedTabs, setVisitedTabs] = useState<Set<Tab>>(() => new Set(['dashboard']))
  const [stats, setStats] = useState<Stats | null>(null)

  const refreshStats = () => getStats().then(setStats).catch(() => {})
  useEffect(() => { refreshStats() }, [])

  const openTab = (nextTab: Tab) => {
    setVisitedTabs(current => {
      if (current.has(nextTab)) return current
      const next = new Set(current)
      next.add(nextTab)
      return next
    })
    setTab(nextTab)
  }

  const navItems: { id: Tab; label: string; icon: React.ReactNode }[] = [
    { id: 'dashboard', label: 'Dashboard', icon: <LayoutDashboard className="w-4 h-4" /> },
    { id: 'preview', label: 'Ingest & Define', icon: <Box className="w-4 h-4" /> },
    { id: 'manage', label: 'Knowledge Base', icon: <SlidersHorizontal className="w-4 h-4" /> },
    { id: 'query', label: 'Ask AI', icon: <MessageSquare className="w-4 h-4" /> },
  ]

  return (
    <div className="flex h-[100dvh] bg-zinc-950 text-white font-sans selection:bg-emerald-500/30 selection:text-emerald-100">
      {/* Sidebar Navigation */}
      <aside className="w-20 lg:w-[260px] shrink-0 bg-zinc-950 border-r border-zinc-800 flex flex-col justify-between">
        <div>
          <div className="h-20 flex items-center px-4 lg:px-6 border-b border-zinc-800">
            <div className="flex items-center gap-3">
              <div className="bg-emerald-400 text-zinc-950 p-1.5 rounded-lg">
                <Database className="w-5 h-5" />
              </div>
              <div className="hidden lg:block min-w-0">
                <div className="font-bold text-lg tracking-tight text-white">IssueAtlas</div>
                <div className="text-[10px] uppercase tracking-[0.16em] text-zinc-500">Evidence-led delivery</div>
              </div>
            </div>
          </div>

          <nav className="p-4 space-y-1 relative z-10">
            <p className="hidden lg:block px-3 text-xs font-semibold text-zinc-500 tracking-wider uppercase mb-3 mt-2">Menu</p>
            {navItems.map(item => (
              <button
                key={item.id}
                onClick={() => openTab(item.id)}
                title={item.label}
                className={`w-full flex items-center justify-center lg:justify-start gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 ${
                  tab === item.id
                    ? 'bg-zinc-900 text-white shadow-sm ring-1 ring-zinc-800'
                    : 'text-zinc-400 hover:text-white hover:bg-zinc-900/50'
                }`}
              >
                <span className={tab === item.id ? 'text-emerald-400' : ''}>{item.icon}</span>
                <span className="hidden lg:inline">{item.label}</span>
              </button>
            ))}
          </nav>
        </div>

        {/* Global Stats Footer */}
        {stats && (
          <div className="hidden lg:block p-6 border-t border-zinc-800 relative z-10">
            {DEMO_MODE && <div className="mb-4 rounded-lg border border-emerald-400/20 bg-emerald-400/10 px-3 py-2 text-[11px] font-semibold text-emerald-300">Synthetic demo data</div>}
            <p className="text-xs font-semibold text-zinc-500 tracking-wider uppercase mb-3">Index Stats</p>
            <div className="space-y-3">
              <div className="flex justify-between items-center">
                <span className="text-sm text-zinc-400">Documents</span>
                <span className="text-sm font-medium text-white">{stats.total_docs}</span>
              </div>
              <div className="flex justify-between items-center">
                <span className="text-sm text-zinc-400">Chunks</span>
                <span className="text-sm font-medium text-white">{stats.total_chunks}</span>
              </div>

              {stats.by_sprint && Object.keys(stats.by_sprint).length > 0 && (
                <div className="pt-3 flex flex-wrap gap-2">
                  {Object.entries(stats.by_sprint).filter(([k]) => k !== '(unassigned)').slice(0, 3).map(([k, v]) => (
                    <div key={k} className="px-2 py-1 rounded-md bg-zinc-900 border border-zinc-800 flex items-center gap-1.5 text-xs">
                      <span className="font-semibold text-emerald-400">{k}</span>
                      <span className="text-zinc-700">|</span>
                      <span className="text-white font-medium">{v}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        )}
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 bg-zinc-950 relative overflow-hidden">
        <div className="absolute inset-0 z-10">
          {visitedTabs.has('dashboard') && (
            <div aria-hidden={tab !== 'dashboard'} className={`absolute inset-0 overflow-y-auto ${tab === 'dashboard' ? 'visible' : 'invisible pointer-events-none'}`}>
              <TabErrorBoundary name="Dashboard"><Suspense fallback={<TabLoading />}><DashboardTab /></Suspense></TabErrorBoundary>
            </div>
          )}
          {visitedTabs.has('preview') && (
            <div aria-hidden={tab !== 'preview'} className={`absolute inset-0 overflow-y-auto ${tab === 'preview' ? 'visible' : 'invisible pointer-events-none'}`}>
              <TabErrorBoundary name="Ingest & Define"><Suspense fallback={<TabLoading />}><PreviewTab onIngested={refreshStats} /></Suspense></TabErrorBoundary>
            </div>
          )}
          {visitedTabs.has('manage') && (
            <div aria-hidden={tab !== 'manage'} className={`absolute inset-0 overflow-y-auto ${tab === 'manage' ? 'visible' : 'invisible pointer-events-none'}`}>
              <TabErrorBoundary name="Knowledge Base"><Suspense fallback={<TabLoading />}><ManageTab onChanged={refreshStats} /></Suspense></TabErrorBoundary>
            </div>
          )}
          {visitedTabs.has('query') && (
            <div aria-hidden={tab !== 'query'} className={`absolute inset-0 overflow-y-auto ${tab === 'query' ? 'visible' : 'invisible pointer-events-none'}`}>
              <TabErrorBoundary name="Ask AI"><Suspense fallback={<TabLoading />}><QueryTab stats={stats} /></Suspense></TabErrorBoundary>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
