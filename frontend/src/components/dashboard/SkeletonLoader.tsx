export default function SkeletonLoader() {
  return (
    <div className="max-w-7xl mx-auto space-y-6 animate-pulse">
      {/* Header Skeleton */}
      <header className="flex flex-col md:flex-row md:items-end justify-between gap-6 border-b border-slate-200 pb-5">
        <div className="space-y-3">
          <div className="h-8 w-48 bg-slate-200 rounded"></div>
          <div className="h-4 w-64 bg-slate-100 rounded"></div>
        </div>
        <div className="flex items-center gap-5 text-right">
          <div className="space-y-2 flex flex-col items-end">
            <div className="h-3 w-24 bg-slate-200 rounded"></div>
            <div className="h-8 w-20 bg-slate-200 rounded"></div>
          </div>
          <div className="h-8 w-24 bg-slate-100 rounded-md"></div>
        </div>
      </header>

      {/* Metrics Row Skeleton */}
      <section className="grid grid-cols-2 md:grid-cols-4  rounded-2xl overflow-hidden glass-card shadow-sm divide-x divide-y md:divide-y-0 divide-slate-200">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="p-4 sm:p-5 flex flex-col justify-center space-y-3">
            <div className="h-4 w-24 bg-slate-100 rounded"></div>
            <div className="h-8 w-16 bg-slate-200 rounded"></div>
          </div>
        ))}
      </section>

      {/* Main Grid Skeleton */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 items-start">
        <div className="lg:col-span-2 space-y-6">
          <div className=" rounded-2xl glass-card p-5 h-[340px]">
            <div className="h-5 w-32 bg-slate-200 rounded mb-6"></div>
            <div className="h-[240px] w-full bg-slate-50 rounded"></div>
          </div>
          <div className=" rounded-2xl glass-card p-5">
            <div className="h-5 w-32 bg-slate-200 rounded mb-6"></div>
            <div className="space-y-6">
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="space-y-2">
                  <div className="flex justify-between">
                    <div className="h-4 w-24 bg-slate-200 rounded"></div>
                    <div className="h-4 w-8 bg-slate-100 rounded"></div>
                  </div>
                  <div className="h-2 w-full bg-slate-50 rounded-full"></div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="space-y-6">
          <div className=" rounded-2xl glass-card overflow-hidden shadow-sm">
            <div className="px-4 py-3 border-b border-slate-200 bg-slate-50">
              <div className="h-5 w-24 bg-slate-200 rounded"></div>
            </div>
            <div className="divide-y divide-slate-100 p-4 space-y-4">
              {[1, 2, 3, 4, 5].map((i) => (
                <div key={i} className="flex justify-between items-center pt-2">
                  <div className="h-4 w-32 bg-slate-100 rounded"></div>
                  <div className="h-4 w-8 bg-slate-200 rounded"></div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}
