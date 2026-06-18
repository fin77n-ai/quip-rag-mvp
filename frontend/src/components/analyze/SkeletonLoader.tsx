export default function SkeletonLoader() {
  return (
    <div className="max-w-6xl mx-auto space-y-6 animate-pulse">
      {/* Summary Cards Skeleton */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="bg-zinc-900 border border-gray-200 rounded-lg p-4">
            <div className="h-3 w-16 bg-slate-200 rounded"></div>
            <div className="h-6 w-24 bg-slate-200 rounded mt-2"></div>
          </div>
        ))}
      </div>

      {/* Tables Skeleton */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {[1, 2, 3].map((i) => (
          <div key={i} className="bg-zinc-900 border border-gray-200 rounded-lg overflow-hidden">
            <div className="px-3 py-2 border-b border-gray-200 bg-zinc-800\/50 h-8">
              <div className="h-4 w-24 bg-slate-200 rounded"></div>
            </div>
            <div className="divide-y divide-gray-100 p-3 space-y-3">
              {[1, 2, 3, 4, 5].map((j) => (
                <div key={j} className="flex justify-between">
                  <div className="h-3 w-32 bg-slate-200 rounded"></div>
                  <div className="h-3 w-8 bg-slate-200 rounded"></div>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* Issue Groups Skeleton */}
      <div className="space-y-4">
        <div className="h-4 w-48 bg-slate-200 rounded"></div>
        {[1, 2].map((i) => (
          <div key={i} className="bg-zinc-900 border border-gray-200 rounded-lg p-4">
            <div className="flex gap-2 mb-4">
              <div className="h-5 w-16 bg-slate-200 rounded"></div>
              <div className="h-5 w-20 bg-slate-200 rounded"></div>
            </div>
            <div className="h-4 w-3/4 bg-slate-200 rounded mb-2"></div>
            <div className="h-4 w-1/2 bg-slate-200 rounded"></div>

            <div className="mt-4 grid grid-cols-1 lg:grid-cols-[220px_1fr] gap-4">
              <div className="space-y-4">
                <div className="h-16 bg-slate-100 rounded"></div>
                <div className="h-16 bg-slate-100 rounded"></div>
              </div>
              <div className="h-32 bg-slate-100 rounded"></div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
