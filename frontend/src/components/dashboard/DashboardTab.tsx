import { useEffect, useState, useMemo } from 'react'
import { getSprintTrends, SprintTrend, VideoStat, VendorCategoryStat } from '../../api/client'
import {
  BarChart,
  Bar,
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  PieChart,
  Pie,
  Cell
} from 'recharts'
import { Target, Users, TrendingUp, TrendingDown, AlertTriangle, Activity, Video, ChevronDown, LayoutDashboard } from 'lucide-react'

// Custom tooltip for a premium dark mode look
const CustomTooltip = ({ active, payload, label }: any) => {
  if (active && payload && payload.length) {
    return (
      <div className="bg-zinc-900/95 backdrop-blur-xl border border-zinc-700 shadow-2xl p-4 rounded-xl min-w-[160px] z-50">
        {label && <p className="text-zinc-400 text-xs font-semibold uppercase tracking-wider mb-3 pb-2 border-b border-zinc-800">{label}</p>}
        <div className="space-y-2.5">
          {payload.map((entry: any, index: number) => (
            <div key={index} className="flex items-center justify-between gap-6">
              <div className="flex items-center gap-2.5">
                <div
                  className="w-2 h-2 rounded-full"
                  style={{ backgroundColor: entry.color || entry.fill, boxShadow: `0 0 8px ${entry.color || entry.fill}` }}
                />
                <span className="text-zinc-200 text-sm font-medium">{entry.name}</span>
              </div>
              <span className="text-white text-sm font-bold">{entry.value}</span>
            </div>
          ))}
        </div>
      </div>
    )
  }
  return null
}

export function DashboardTab() {
  const [activeView, setActiveView] = useState<'overall' | 'vendor' | 'video'>('overall')
  const [vendorMode, setVendorMode] = useState<'overall' | 'sprint'>('overall')
  const [vendorSprint, setVendorSprint] = useState<string>('')

  const [selectedVideo, setSelectedVideo] = useState('')
  const [isDropdownOpen, setIsDropdownOpen] = useState(false)
  const [videoStats, setVideoStats] = useState<VideoStat[]>([])
  const [vendorStats, setVendorStats] = useState<{ overall: VendorCategoryStat[]; by_sprint: VendorCategoryStat[] }>({ overall: [], by_sprint: [] })

  const [trends, setTrends] = useState<SprintTrend[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getSprintTrends()
      .then(res => {
        if (res.videos && res.videos.length > 0) {
          setVideoStats(res.videos);
          if (!selectedVideo) {
            setSelectedVideo(res.videos[0].video_name);
          }
        } else {
          setVideoStats([]);
        }
        setVendorStats(res.vendors || { overall: [], by_sprint: [] });

        if (!res.trends || res.trends.length === 0) {
          setTrends([]);
          return;
        }

        setTrends(res.trends);
        setVendorSprint(res.trends.length > 0 ? res.trends[res.trends.length - 1].sprint : '');
      })
      .catch(() => {
        // Do not inject mocks on error to prevent UI jumpiness
        setTrends([]);
        setVideoStats([]);
      })
      .finally(() => setLoading(false))
  }, [])

  // Calculate Metrics
  const metrics = useMemo(() => {
    if (!trends.length) return null;
    const latest = trends[trends.length - 1];
    const past = trends.slice(0, trends.length - 1);
    const pastLen = past.length || 1;

    // 1. Total Issues
    const pastAvgIssues = past.reduce((acc, t) => acc + t.total_issues, 0) / pastLen;
    const issuesDelta = ((latest.total_issues - pastAvgIssues) / pastAvgIssues) * 100;

    // 2. Vendor Deltas (Each vendor vs their own past avg)
    const vendorDeltas = Object.keys(latest.sources || {}).map(v => {
      const latVal = latest.sources[v] || 0;
      const pastAvg = past.reduce((acc, t) => acc + (t.sources?.[v] || 0), 0) / pastLen;
      const delta = pastAvg === 0 ? 0 : ((latVal - pastAvg) / pastAvg) * 100;
      return { name: v, delta, val: latVal };
    }).sort((a, b) => b.delta - a.delta);

    // 3. Top Category
    const latestCats = Object.entries(latest.categories || {});
    const topCat = latestCats.sort((a, b) => b[1] - a[1])[0] || ['None', 0];
    const pastCatAvg = past.reduce((acc, t) => acc + (t.categories?.[topCat[0]] || 0), 0) / pastLen;
    const catDelta = pastCatAvg === 0 ? 0 : ((topCat[1] - pastCatAvg) / pastCatAvg) * 100;

    // 4. Worst Trend (Biggest positive delta across categories & languages)
    const allSpikes: Array<{name: string, delta: number, val: number, type: string}> = [];
    ['categories', 'languages'].forEach(field => {
      const fieldKey = field as keyof SprintTrend;
      Object.keys(latest[fieldKey] || {}).forEach(k => {
        const dataMap = latest[fieldKey] as Record<string, number>;
        const latVal = dataMap[k] || 0;
        const pastAvg = past.reduce((acc, t) => {
          const tMap = t[fieldKey] as Record<string, number>;
          return acc + (tMap?.[k] || 0);
        }, 0) / pastLen;
        const delta = pastAvg === 0 ? 0 : ((latVal - pastAvg) / pastAvg) * 100;
        if (latVal > 5) { // Threshold to ignore noise
           allSpikes.push({ name: k, delta, val: latVal, type: field });
        }
      });
    });
    const worstTrend = allSpikes.sort((a, b) => b.delta - a.delta)[0] || { name: 'None', delta: 0, val: 0 };

    return {
      issues: { val: latest.total_issues, delta: issuesDelta, avg: pastAvgIssues },
      vendorDeltas,
      category: { name: topCat[0], val: topCat[1], delta: catDelta },
      worst: worstTrend
    }
  }, [trends])

  const chartData = useMemo(() => {
    return trends.map(t => ({
      sprint: t.sprint,
      total_issues: t.total_issues,
      ...t.sources,
      ...t.categories,
      ...t.languages // Fix: Ensure language data is flattened into the row for Recharts Area keys to match
    }))
  }, [trends])

  // Data for Latest MS Pie & Bar Charts
  const latestCategories = useMemo(() => {
    if (!trends.length) return [];
    return Object.entries(trends[trends.length - 1].categories || {})
      .map(([name, value]) => ({ name, value }))
      .sort((a, b) => b.value - a.value);
  }, [trends]);

  // Get ALL unique languages across all sprints for the Area chart
  const allLanguages = useMemo(() => {
    if (!trends.length) return [];
    const langs = new Set<string>();
    trends.forEach(t => {
      Object.keys(t.languages || {}).forEach(l => langs.add(l));
    });
    // Sort alphabetically for consistent legend/colors
    return Array.from(langs).sort();
  }, [trends]);

  // Restrained dark-mode chart palette for dense analytics.
  const VENDOR_COLORS = {
    RWS: '#ec4899',    // Pink 500 (Vivid & Distinct)
    LB: '#3b82f6',     // Blue 500 (Solid & Clear)
    Toin: '#eab308',   // Yellow 500 (Warm & Bright)
    BAL: '#8b5cf6',    // Purple 500
    Source: '#14b8a6'  // Teal 500 (Cool & Distinct)
  };
  const PIE_COLORS = ['#3b82f6', '#8b5cf6', '#14b8a6', '#f59e0b', '#ec4899'];

  const SUB_CAT_COLORS: Record<string, string[]> = {
    'Translation': ['#3b82f6', '#60a5fa', '#93c5fd'],  // Blue shades
    'Animation': ['#8b5cf6', '#a78bfa', '#c4b5fd'],    // Purple shades
    'Voice Over': ['#14b8a6', '#2dd4bf', '#5eead4']    // Teal shades
  };

  const getSubCatColor = (parent: string, idx: number) => {
    const palette = SUB_CAT_COLORS[parent] || PIE_COLORS;
    return palette[idx % palette.length];
  };

  const formatDelta = (val: number, isGoodWhenDown: boolean = true, compact: boolean = false) => {
    const isDown = val < 0;
    const isGood = isGoodWhenDown ? isDown : !isDown;
    const color = isGood ? 'text-emerald-400' : 'text-rose-400';
    const Icon = isDown ? TrendingDown : TrendingUp;
    const absVal = Math.abs(val).toFixed(0);
    return (
      <div className={`flex items-center gap-1 font-semibold ${color} ${compact ? 'text-sm' : 'text-xs'}`}>
        <Icon className="w-3.5 h-3.5" />
        {compact ? `${absVal}%` : `${absVal}% vs past avg`}
      </div>
    )
  }

  const vendorDistData = useMemo(() => {
    const rows = vendorMode === 'sprint'
      ? vendorStats.by_sprint.filter(row => row.sprint === vendorSprint)
      : vendorStats.overall
    return ['Translation', 'Voice Over', 'Animation', 'Source'].map(category => {
      const result: Record<string, string | number> = { category }
      rows.forEach(row => {
        result[row.vendor] = Number(row[category as keyof VendorCategoryStat] || 0)
      })
      return result
    })
  }, [vendorMode, vendorSprint, vendorStats]);

  // Generate stable mock video data based on actual video stats
  const activeVideoStats = useMemo(() => {
    if (!selectedVideo || !videoStats.length) return { vendors: [], languages: [] };

    // Find the actual stats for the selected video
    const stat = videoStats.find(v => v.video_name === selectedVideo);
    if (!stat) return { vendors: [], languages: [] };

    return {
      vendors: stat.vendors || [],
      languages: stat.languages || []
    };
  }, [selectedVideo, videoStats]);

  const activeVideoData = activeVideoStats.vendors;

  if (loading) return <div className="p-8 text-center text-zinc-500 font-medium">Loading analytics...</div>
  // Allow Video Insights tab to render even if overall trends are empty or metrics failed to compute.
  if (activeView === 'overall' && (!trends.length || !metrics)) return null;

  return (
    <div className="flex flex-col h-full bg-zinc-950 overflow-y-auto">
      <header className="px-10 pt-12 pb-8 flex flex-col md:flex-row md:items-center justify-between gap-4 shrink-0">
        <div className="flex-1">
          <h1 className="text-3xl font-semibold tracking-tight text-white">Milestone Dashboard</h1>
          <p className="text-zinc-400 mt-2 text-sm">Real-time issue drifts and vendor accountability across sprints</p>
        </div>
        <div className="flex bg-zinc-900 border border-zinc-800 rounded-lg p-1 shrink-0">
          <button
            onClick={() => setActiveView('overall')}
            className={`px-4 py-2 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${activeView === 'overall' ? 'bg-zinc-800 text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200'}`}
          >
            <LayoutDashboard className="w-4 h-4" /> Overall View
          </button>
          <button
            onClick={() => setActiveView('vendor')}
            className={`px-4 py-2 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${activeView === 'vendor' ? 'bg-zinc-800 text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200'}`}
          >
            <Users className="w-4 h-4" /> Vendor Distribution
          </button>
          <button
            onClick={() => setActiveView('video')}
            className={`px-4 py-2 text-sm font-medium rounded-md transition-colors flex items-center gap-2 ${activeView === 'video' ? 'bg-zinc-800 text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200'}`}
          >
            <Video className="w-4 h-4" /> Video Insights
          </button>
        </div>
      </header>

      <div className="px-10 pb-20 space-y-8 max-w-[1400px] w-full">
        {activeView === 'vendor' && (
          <div className="bg-zinc-900 p-8 rounded-2xl border border-zinc-800 shadow-[0_8px_32px_rgba(0,0,0,0.4)]">
            <div className="mb-8 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
              <div>
                <h2 className="text-xl font-semibold text-white">Vendor Distribution by Category</h2>
                <p className="text-sm text-zinc-400 mt-1">Comparing issue types across RWS, LB, Toin, and BAL.</p>
              </div>
              <div className="flex bg-zinc-800 border border-zinc-700 rounded-lg p-1">
                <button
                  onClick={() => setVendorMode('overall')}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${vendorMode === 'overall' ? 'bg-zinc-700 text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200'}`}
                >
                  Overall
                </button>
                <button
                  onClick={() => setVendorMode('sprint')}
                  className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${vendorMode === 'sprint' ? 'bg-zinc-700 text-white shadow-sm' : 'text-zinc-400 hover:text-zinc-200'}`}
                >
                  By Sprint
                </button>
              </div>
            </div>

            {vendorMode === 'sprint' && (
              <div className="mb-6 flex gap-2 flex-wrap">
                {trends.map(t => (
                  <button
                    key={t.sprint}
                    onClick={() => setVendorSprint(t.sprint)}
                    className={`px-3 py-1 text-xs rounded-full border transition-colors ${vendorSprint === t.sprint ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/50' : 'bg-transparent text-zinc-400 border-zinc-700 hover:border-zinc-500'}`}
                  >
                    {t.sprint}
                  </button>
                ))}
              </div>
            )}

            <div className="h-[400px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={vendorDistData} margin={{ top: 10, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="4 4" vertical={false} stroke="#27272a" />
                  <XAxis dataKey="category" axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 13, fontWeight: 500 }} dy={10} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 12 }} />
                  <Tooltip content={<CustomTooltip />} cursor={{ fill: '#27272a', opacity: 0.4 }} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: '13px', paddingTop: '20px' }} />
                  <Bar dataKey="RWS" fill={VENDOR_COLORS.RWS} radius={[4, 4, 0, 0]} name="RWS" />
                  <Bar dataKey="LB" fill={VENDOR_COLORS.LB} radius={[4, 4, 0, 0]} name="LB" />
                  <Bar dataKey="Toin" fill={VENDOR_COLORS.Toin} radius={[4, 4, 0, 0]} name="Toin" />
                  <Bar dataKey="BAL" fill={VENDOR_COLORS.BAL} radius={[4, 4, 0, 0]} name="BAL" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        )}

        {activeView === 'video' && (
          <div className="bg-zinc-900 p-8 rounded-2xl border border-zinc-800 shadow-[0_8px_32px_rgba(0,0,0,0.4)] relative">
            <div className="mb-8 flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
              <div>
                <h2 className="text-xl font-semibold text-white">Single Video Insights</h2>
                <p className="text-sm text-zinc-400 mt-1">Vendor performance on the selected video asset.</p>
              </div>

              <div className="relative w-full sm:w-[300px]">
                <button
                  onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                  className="w-full flex items-center justify-between gap-3 bg-zinc-800 hover:bg-zinc-700/80 border border-zinc-700 hover:border-zinc-600 transition-all text-white rounded-xl px-4 py-3 text-sm focus:outline-none focus:ring-2 focus:ring-emerald-500/50 shadow-sm"
                >
                  <div className="flex items-center gap-3 truncate">
                    <div className="p-1.5 bg-emerald-500/10 rounded-md shrink-0">
                      <Video className="w-4 h-4 text-emerald-400" />
                    </div>
                    <span className="truncate font-medium">{selectedVideo || 'Select a video'}</span>
                  </div>
                  <ChevronDown className={`w-4 h-4 text-zinc-400 shrink-0 transition-transform duration-200 ${isDropdownOpen ? 'rotate-180' : ''}`} />
                </button>

                {isDropdownOpen && (
                  <div className="absolute top-full mt-2 w-full max-h-[320px] overflow-y-auto bg-zinc-800 border border-zinc-700 rounded-xl shadow-2xl z-50 py-2 scrollbar-thin scrollbar-thumb-zinc-600 scrollbar-track-transparent">
                    {videoStats.map(v => (
                      <button
                        key={v.video_name}
                        onClick={() => {
                          setSelectedVideo(v.video_name);
                          setIsDropdownOpen(false);
                        }}
                        className={`w-full text-left px-4 py-2.5 text-sm transition-colors flex items-center justify-between ${
                          selectedVideo === v.video_name
                            ? 'bg-zinc-700/50 text-white font-medium'
                            : 'text-zinc-400 hover:bg-zinc-700/30 hover:text-zinc-200'
                        }`}
                      >
                        <span className="truncate pr-4">{v.video_name}</span>
                        <span className="shrink-0 text-xs px-2 py-0.5 rounded-full bg-zinc-900 border border-zinc-700 text-zinc-400">
                          {v.total_issues}
                        </span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="h-[400px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={activeVideoData} layout="vertical" margin={{ top: 10, right: 30, left: 10, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="4 4" horizontal={false} stroke="#27272a" />
                  <XAxis type="number" axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 12 }} />
                  <YAxis dataKey="vendor" type="category" axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 13, fontWeight: 500 }} dx={-10} />
                  <Tooltip content={<CustomTooltip />} cursor={{ fill: '#27272a', opacity: 0.4 }} />
                  <Bar dataKey="issues" radius={[0, 4, 4, 0]} barSize={40}>
                    {
                      activeVideoData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.fill} />
                      ))
                    }
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>

            {activeVideoData && activeVideoData.length > 0 && (
              <>
                <div className="mt-6 flex flex-wrap gap-4 pt-6 border-t border-zinc-800">
                  <span className="text-sm font-medium text-zinc-400 py-1.5">Issue Distribution:</span>
                  {activeVideoData.map(v => (
                    <div key={v.vendor} className="flex items-center gap-2 bg-zinc-800/50 px-3 py-1.5 rounded-lg border border-zinc-700/50">
                      <div className="w-2 h-2 rounded-full" style={{ backgroundColor: v.fill, boxShadow: `0 0 6px ${v.fill}80` }} />
                      <span className="text-zinc-300 text-sm font-medium">{v.vendor}</span>
                      <span className="text-white text-sm font-bold">{v.issues}</span>
                      <span className="text-zinc-500 text-xs ml-1">
                        ({Math.round((v.issues / activeVideoData.reduce((acc, curr) => acc + curr.issues, 0)) * 100)}%)
                      </span>
                    </div>
                  ))}
                </div>

                {/* Vendor Category Breakdown (Pie Charts) */}
                <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 pt-6 border-t border-zinc-800">
                  {activeVideoData.map(v => (
                    <div key={`pie-vendor-${v.vendor}`} className="bg-zinc-800/20 p-5 rounded-2xl border border-zinc-800/50 flex flex-col items-center hover:border-zinc-700/50 transition-colors">
                      <h3 className="text-sm font-semibold text-white mb-0.5">{v.vendor} Breakdown</h3>
                      <p className="text-xs text-zinc-500 mb-4">{v.issues} Total Issues</p>

                      <div className="h-[140px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart>
                            <Pie
                              data={v.categories || []}
                              innerRadius={45}
                              outerRadius={65}
                              paddingAngle={3}
                              dataKey="value"
                              stroke="none"
                            >
                              {(v.categories || []).map((c, idx) => (
                                <Cell key={`cell-${idx}`} fill={getSubCatColor(c.parent || 'Translation', idx)} />
                              ))}
                            </Pie>
                            <Tooltip content={<CustomTooltip />} />
                          </PieChart>
                        </ResponsiveContainer>
                      </div>

                      <div className="mt-4 flex flex-col w-full gap-2 px-2">
                        {(v.categories || []).map((c, idx) => (
                          <div key={c.name} className="flex items-center justify-between">
                            <div className="flex items-center gap-2">
                              <div className="w-2 h-2 rounded-full" style={{ backgroundColor: getSubCatColor(c.parent || 'Translation', idx) }} />
                              <span className="text-xs text-zinc-300">{c.name}</span>
                            </div>
                            <span className="text-xs font-semibold text-white">{c.value}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>

                {/* Language Category Breakdown (Pie Charts) */}
                {activeVideoStats.languages && activeVideoStats.languages.length > 0 && (
                  <div className="mt-8 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6 pt-6 border-t border-zinc-800">
                    {activeVideoStats.languages.map(l => (
                      <div key={`pie-lang-${l.language}`} className="bg-zinc-800/20 p-5 rounded-2xl border border-zinc-800/50 flex flex-col items-center hover:border-zinc-700/50 transition-colors">
                        <h3 className="text-sm font-semibold text-white mb-0.5">{l.language} Breakdown</h3>
                        <p className="text-xs text-zinc-500 mb-4">{l.issues} Total Issues</p>

                        <div className="h-[140px] w-full">
                          <ResponsiveContainer width="100%" height="100%">
                            <PieChart>
                              <Pie
                                data={l.categories || []}
                                innerRadius={45}
                                outerRadius={65}
                                paddingAngle={3}
                                dataKey="value"
                                stroke="none"
                              >
                                {(l.categories || []).map((c, idx) => (
                                  <Cell key={`cell-${idx}`} fill={getSubCatColor(c.parent || 'Translation', idx)} />
                                ))}
                              </Pie>
                              <Tooltip content={<CustomTooltip />} />
                            </PieChart>
                          </ResponsiveContainer>
                        </div>

                        <div className="mt-4 flex flex-col w-full gap-2 px-2">
                          {(l.categories || []).map((c, idx) => (
                            <div key={c.name} className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <div className="w-2 h-2 rounded-full" style={{ backgroundColor: getSubCatColor(c.parent || 'Translation', idx) }} />
                                <span className="text-xs text-zinc-300">{c.name}</span>
                              </div>
                              <span className="text-xs font-semibold text-white">{c.value}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
          </div>
        )}

        {activeView === 'overall' && metrics && chartData && chartData.length > 0 && latestCategories && allLanguages && (
          <>
        {/* Top Bento Metrics */}
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
          {/* 1. Total Issues */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 shadow-sm hover:border-zinc-700 transition-colors">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-zinc-400">Latest MS Issues</h3>
              <div className="p-2 bg-zinc-800 rounded-md"><Target className="w-4 h-4 text-emerald-500" /></div>
            </div>
            <div className="flex items-baseline gap-4 mb-2">
              <span className="text-4xl font-bold text-white">{metrics.issues.val}</span>
            </div>
            <div className="flex items-center gap-2">
              {formatDelta(metrics.issues.delta, true)}
              <span className="text-zinc-500 text-xs">(avg: {Math.round(metrics.issues.avg)})</span>
            </div>
          </div>

          {/* 2. Vendor Deltas */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 shadow-sm hover:border-zinc-700 transition-colors flex flex-col">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium text-zinc-400">Vendor Deltas</h3>
              <div className="p-2 bg-zinc-800 rounded-md"><Users className="w-4 h-4 text-indigo-400" /></div>
            </div>
            <div className="flex-1 grid grid-cols-2 gap-y-2 gap-x-4">
              {metrics.vendorDeltas.slice(0, 4).map(v => (
                <div key={v.name} className="flex items-center justify-between">
                  <span className="text-zinc-300 text-sm font-medium">{v.name}</span>
                  {formatDelta(v.delta, true, true)}
                </div>
              ))}
            </div>
          </div>

          {/* 3. Top Category */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 shadow-sm hover:border-zinc-700 transition-colors flex flex-col justify-center">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-zinc-400">Leading Category</h3>
              <div className="p-2 bg-zinc-800 rounded-md"><Activity className="w-4 h-4 text-amber-500" /></div>
            </div>
            <div className="flex items-baseline gap-4 mb-2">
              {/* Removed truncate, allowed to break words, responsive text size */}
              <span className="text-2xl sm:text-3xl font-bold text-white leading-tight break-words">{metrics.category.name}</span>
            </div>
            {formatDelta(metrics.category.delta, true)}
          </div>

          {/* 4. Worst Spike (Pain Point) */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-6 shadow-sm hover:border-zinc-700 transition-colors">
            <div className="flex items-center justify-between mb-4">
              <h3 className="text-sm font-medium text-zinc-400">Worst Spike (Pain Point)</h3>
              <div className="p-2 bg-zinc-800 rounded-md"><AlertTriangle className="w-4 h-4 text-rose-500" /></div>
            </div>
            <div className="flex items-baseline gap-4 mb-2">
              <span className="text-2xl sm:text-3xl font-bold text-white leading-tight break-words">{metrics.worst.name}</span>
            </div>
            <div className="flex items-center gap-2">
              {formatDelta(metrics.worst.delta, true)}
              <span className="text-zinc-500 text-xs">({metrics.worst.val} issues)</span>
            </div>
          </div>
        </div>

        {/* --- ROW 1: Trend Charts --- */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Vendor Stacked Bar Chart (Premium Colors) */}
          <div className="bg-zinc-900 p-8 rounded-2xl border border-zinc-800 shadow-[0_8px_32px_rgba(0,0,0,0.4)]">
            <div className="mb-8">
              <h2 className="text-base font-semibold text-white">Vendor Quality Contributions</h2>
              <p className="text-xs text-zinc-400 mt-0.5">Stacked issue count by source vendor across milestones</p>
            </div>
            <div className="h-[300px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 10, right: 0, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="4 4" vertical={false} stroke="#27272a" />
                  <XAxis dataKey="sprint" axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 12, fontWeight: 500 }} dy={10} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 12 }} />
                  <Tooltip content={<CustomTooltip />} cursor={{ fill: '#27272a', opacity: 0.4 }} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
                  <Bar dataKey="RWS" stackId="a" fill={VENDOR_COLORS.RWS} stroke="#18181b" strokeWidth={2} radius={[0, 0, 4, 4]} name="RWS (Vendor)" />
                  <Bar dataKey="LB" stackId="a" fill={VENDOR_COLORS.LB} stroke="#18181b" strokeWidth={2} name="LB (Vendor)" />
                  <Bar dataKey="Toin" stackId="a" fill={VENDOR_COLORS.Toin} stroke="#18181b" strokeWidth={2} name="Toin (Vendor)" />
                  <Bar dataKey="BAL" stackId="a" fill={VENDOR_COLORS.BAL} stroke="#18181b" strokeWidth={2} name="BAL (Vendor)" />
                  <Bar dataKey="Source" stackId="a" fill={VENDOR_COLORS.Source} stroke="#18181b" strokeWidth={2} radius={[4, 4, 0, 0]} name="Source Asset" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Category Drift Line Chart */}
          <div className="bg-zinc-900 p-8 rounded-2xl border border-zinc-800 shadow-[0_8px_32px_rgba(0,0,0,0.4)]">
            <div className="mb-8">
              <h2 className="text-base font-semibold text-white">Issue Category Drift</h2>
              <p className="text-xs text-zinc-400 mt-0.5">Trends of major bug categories across milestones</p>
            </div>
            <div className="h-[300px] w-full">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="4 4" vertical={false} stroke="#27272a" />
                  <XAxis dataKey="sprint" axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 12, fontWeight: 500 }} dy={10} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 12 }} />
                  <Tooltip content={<CustomTooltip />} cursor={{ stroke: '#3f3f46', strokeWidth: 1, strokeDasharray: '4 4' }} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
                  <Line type="monotone" dataKey="Translation" stroke="#22d3ee" strokeWidth={3} dot={{ r: 4, strokeWidth: 2 }} activeDot={{ r: 6 }} name="Translation" />
                  <Line type="monotone" dataKey="Animation" stroke="#a78bfa" strokeWidth={3} dot={{ r: 4, strokeWidth: 2 }} activeDot={{ r: 6 }} name="Animation" />
                  <Line type="monotone" dataKey="Voice Over" stroke="#fbbf24" strokeWidth={3} dot={{ r: 4, strokeWidth: 2 }} activeDot={{ r: 6 }} name="Voice Over" />
                  <Line type="monotone" dataKey="Source" stroke="#34d399" strokeWidth={3} dot={{ r: 4, strokeWidth: 2 }} activeDot={{ r: 6 }} name="Source" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>

        {/* --- ROW 2: Deep Dives (Pie & Lang Bar) --- */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Latest MS Categories (Donut Pie) */}
          <div className="bg-zinc-900 p-8 rounded-2xl border border-zinc-800 shadow-[0_8px_32px_rgba(0,0,0,0.4)] flex flex-col">
            <div className="mb-4 shrink-0">
              <h2 className="text-base font-semibold text-white">Latest Breakdown (Current MS)</h2>
              <p className="text-xs text-zinc-400 mt-0.5">Distribution of issue categories in the latest milestone</p>
            </div>
            <div className="flex-1 min-h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={latestCategories}
                    innerRadius={70}
                    outerRadius={100}
                    paddingAngle={4}
                    dataKey="value"
                    stroke="none"
                  >
                    {latestCategories.map((_, index) => <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />)}
                  </Pie>
                  <Tooltip content={<CustomTooltip />} />
                  <Legend
                    layout="vertical"
                    verticalAlign="middle"
                    align="right"
                    iconType="circle"
                    wrapperStyle={{ fontSize: '13px', color: '#e4e4e7' }}
                  />
                </PieChart>
              </ResponsiveContainer>
            </div>
          </div>

          {/* Top Problematic Languages (Bar Trend) */}
          <div className="bg-zinc-900 p-8 rounded-2xl border border-zinc-800 shadow-[0_8px_32px_rgba(0,0,0,0.4)] flex flex-col">
            <div className="mb-4 shrink-0">
              <h2 className="text-base font-semibold text-white">Language Issue Trends</h2>
              <p className="text-xs text-zinc-400 mt-0.5">Stacked bar trend of all languages across milestones</p>
            </div>
            <div className="flex-1 min-h-[280px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <CartesianGrid strokeDasharray="4 4" vertical={false} stroke="#27272a" />
                  <XAxis dataKey="sprint" axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 12, fontWeight: 500 }} dy={10} />
                  <YAxis axisLine={false} tickLine={false} tick={{ fill: '#71717a', fontSize: 12 }} />
                  <Tooltip content={<CustomTooltip />} cursor={{ fill: '#27272a', opacity: 0.4 }} />
                  <Legend iconType="circle" wrapperStyle={{ fontSize: '12px', paddingTop: '10px' }} />
                  {allLanguages.map((lang, index) => {
                    // A larger, distinct color palette for when there are many languages
                    const colors = [
                      '#f43f5e', '#a855f7', '#0ea5e9', '#10b981', '#f59e0b',
                      '#6366f1', '#ec4899', '#14b8a6', '#f97316', '#8b5cf6',
                      '#2dd4bf', '#ef4444', '#3b82f6', '#84cc16', '#eab308'
                    ];
                    const color = colors[index % colors.length];
                    const isFirst = index === 0;
                    const isLast = index === allLanguages.length - 1;
                    return (
                      <Bar
                        key={lang}
                        dataKey={lang}
                        stackId="1"
                        fill={color}
                        stroke="#18181b"
                        strokeWidth={1}
                        radius={[isLast ? 4 : 0, isLast ? 4 : 0, isFirst ? 4 : 0, isFirst ? 4 : 0]}
                        name={lang}
                      />
                    );
                  })}
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
        </div>
        </>
        )}

      </div>
    </div>
  )
}
