import { useState, useEffect } from 'react'
import { cn } from '@/lib/utils'
import { type TableInfo, API, fmtNum, fmtCompact } from './components/playground/types'
import { TableExplorer } from './components/playground/table-explorer'
import { AnalyticsBuilder } from './components/playground/analytics-builder'
import { SqlEditor } from './components/playground/sql-editor'

type PlaygroundMode = 'explorer' | 'analytics' | 'sql'

const MODE_TABS: { key: PlaygroundMode; label: string; icon: string }[] = [
  { key: 'explorer', label: 'Table Explorer', icon: '' },
  { key: 'analytics', label: 'Analytics', icon: '' },
  { key: 'sql', label: 'SQL Editor', icon: '' },
]

export default function DataPlayground({ mobile, initialSql }: {
  mobile?: boolean
  initialSql?: string
}) {
  const [mode, setMode] = useState<PlaygroundMode>(initialSql ? 'sql' : 'explorer')
  const [tables, setTables] = useState<TableInfo[]>([])

  useEffect(() => {
    fetch(`${API}/tables`)
      .then(r => r.ok ? r.json() : [])
      .then(data => setTables(Array.isArray(data) ? data : []))
      .catch(() => setTables([]))
  }, [])

  useEffect(() => {
    if (initialSql) setMode('sql')
  }, [initialSql])

  const totalRows = tables.reduce((s, t) => s + t.row_count, 0)

  return (
    <div className="flex flex-col h-full">
      {/* Mode tabs */}
      <div className="flex items-center gap-1 border-b border-border pb-0 mb-3 shrink-0">
        {MODE_TABS.map(t => (
          <button key={t.key} onClick={() => setMode(t.key)}
            className={cn(
              'px-3.5 py-2 text-[13px] font-medium bg-transparent border-none cursor-pointer font-sans rounded-t-md transition-colors',
              mode === t.key
                ? 'text-foreground border-b-2 border-primary'
                : 'text-muted-foreground hover:text-foreground',
            )}>
            <span className="mr-1.5">{t.icon}</span>{t.label}
          </button>
        ))}
        <div className="flex-1" />
        <span className="text-[11px] text-muted-foreground pr-2">
          {fmtNum(tables.length)} tables · {fmtCompact(totalRows)} rows
        </span>
      </div>

      {/* Content */}
      <div className="flex-1 min-h-0">
        {mode === 'explorer' && <TableExplorer tables={tables} mobile={mobile} />}
        {mode === 'analytics' && <AnalyticsBuilder tables={tables} mobile={mobile} />}
        {mode === 'sql' && <SqlEditor tables={tables} mobile={mobile} initialSql={initialSql} />}
      </div>
    </div>
  )
}
