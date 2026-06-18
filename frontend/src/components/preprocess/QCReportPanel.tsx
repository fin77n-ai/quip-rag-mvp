import { QCReport } from '../../api/client'

export function qcTextClass(status: QCReport['status']) {
  if (status === 'fail') return 'text-red-600'
  if (status === 'warning') return 'text-amber-600'
  return 'text-emerald-600'
}

export function qcBoxClass(status: QCReport['status']) {
  if (status === 'fail') return 'border-red-200 bg-red-50 text-red-800'
  if (status === 'warning') return 'border-amber-200 bg-amber-50 text-amber-800'
  return 'border-emerald-200 bg-emerald-50 text-emerald-800'
}

export default function QCReportPanel({ report }: { report: QCReport }) {
  return (
    <details open={report.status !== 'pass'} className={`rounded-lg border p-3 text-xs shadow-sm transition-all ${qcBoxClass(report.status)}`}>
      <summary className="cursor-pointer select-none font-semibold uppercase flex items-center outline-none">
        QC {report.status} · {report.summary || report.stage}
      </summary>
      {!!report.issues.length && (
        <div className="mt-3 space-y-2">
          {report.issues.slice(0, 8).map((issue, idx) => (
            <div key={idx} className="rounded-md border border-current/10 bg-zinc-900/60 p-2.5 shadow-sm">
              <div className="font-mono text-[11px] font-semibold opacity-90">{issue.severity} · {issue.type}{issue.ref ? ` · ${issue.ref}` : ''}</div>
              <div className="mt-1 text-zinc-200 text-xs">{issue.message}</div>
            </div>
          ))}
          {report.issues.length > 8 && <div className="text-[11px] opacity-70 font-medium">+{report.issues.length - 8} more issues</div>}
        </div>
      )}
      {report.metrics && (
        <div className="mt-3 flex gap-2 flex-wrap border-t border-current/10 pt-2">
          {Object.entries(report.metrics).slice(0, 8).map(([key, value]) => (
            <span key={key} className="font-mono rounded-md bg-zinc-900/70 px-2 py-1 shadow-sm">
              {key}: {String(value)}
            </span>
          ))}
        </div>
      )}
    </details>
  )
}
