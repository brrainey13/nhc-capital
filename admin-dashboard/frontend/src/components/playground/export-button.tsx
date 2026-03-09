import { useState } from 'react'
import { cn } from '@/lib/utils'
import { API, type ActiveFilter, buildFilterParam, isNumericType } from './types'

function downloadCsv(columns: string[], rows: Record<string, unknown>[], filename: string) {
  const header = columns.map(c => `"${c.replace(/"/g, '""')}"`).join(',')
  const body = rows.map(row =>
    columns.map(c => {
      const v = row[c]
      if (v === null || v === undefined) return ''
      const s = String(v)
      return s.includes(',') || s.includes('"') || s.includes('\n') ? `"${s.replace(/"/g, '""')}"` : s
    }).join(','),
  ).join('\n')
  const blob = new Blob([header + '\n' + body], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url; a.download = filename; a.click()
  URL.revokeObjectURL(url)
}

export function ExportButton({ tableName, columns, rows, filters, typeMap, sortBy, sortDir }: {
  tableName: string
  columns: string[]
  rows: Record<string, unknown>[]
  filters: ActiveFilter[]
  typeMap: Record<string, string>
  sortBy: string | null
  sortDir: 'asc' | 'desc' | null
}) {
  const [exporting, setExporting] = useState(false)
  const [showMenu, setShowMenu] = useState(false)

  function exportLoaded() {
    downloadCsv(columns, rows, `${tableName}_loaded.csv`)
    setShowMenu(false)
  }

  async function exportAll() {
    setExporting(true); setShowMenu(false)
    try {
      const params = new URLSearchParams({ limit: '50000', offset: '0' })
      if (sortBy && sortDir) { params.set('sort_by', sortBy); params.set('sort_dir', sortDir) }
      const fp = buildFilterParam(filters, typeMap)
      if (fp) params.set('filters', fp)
      const r = await fetch(`${API}/tables/${tableName}/data?${params}`)
      const d = await r.json()
      downloadCsv(d.columns, d.rows, `${tableName}_export.csv`)
    } finally { setExporting(false) }
  }

  return (
    <div className="relative">
      <button onClick={() => setShowMenu(!showMenu)} disabled={exporting}
        className={cn(
          'px-2.5 py-1.5 bg-muted border border-border rounded-md text-[11px] font-medium cursor-pointer font-sans text-muted-foreground hover:text-foreground',
          exporting && 'opacity-50 cursor-wait',
        )}>
        {exporting ? 'Exporting…' : 'Export CSV'}
      </button>
      {showMenu && (
        <div className="absolute top-full right-0 mt-1 z-30 bg-card border border-border rounded-md shadow-xl min-w-[160px]">
          <button onClick={exportLoaded}
            className="w-full px-3 py-2 bg-transparent border-none text-xs text-foreground text-left cursor-pointer font-sans hover:bg-muted border-b border-border">
            Export loaded rows ({rows.length})
          </button>
          <button onClick={exportAll}
            className="w-full px-3 py-2 bg-transparent border-none text-xs text-foreground text-left cursor-pointer font-sans hover:bg-muted">
            Export all (up to 50K)
          </button>
        </div>
      )}
    </div>
  )
}
