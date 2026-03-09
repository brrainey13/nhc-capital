import { useState, useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'
import { type TableInfo, type SchemaColumn, API, fmtCompact } from './types'
import { ResultsGrid } from './data-grid'

const HISTORY_KEY = 'nhc-sql-history'
const MAX_HISTORY = 20

interface HistoryEntry { sql: string; ts: number; rowCount?: number }

function loadHistory(): HistoryEntry[] {
  try { return JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]') }
  catch { return [] }
}

function saveHistory(entries: HistoryEntry[]) {
  localStorage.setItem(HISTORY_KEY, JSON.stringify(entries.slice(0, MAX_HISTORY)))
}

/* ── Schema Sidebar ── */

function SchemaSidebar({ tables }: { tables: TableInfo[] }) {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({})
  const [schemas, setSchemas] = useState<Record<string, SchemaColumn[]>>({})
  const [search, setSearch] = useState('')

  function toggle(name: string) {
    setExpanded(prev => ({ ...prev, [name]: !prev[name] }))
    if (!schemas[name]) {
      fetch(`${API}/tables/${name}/schema`)
        .then(r => r.json())
        .then(d => setSchemas(prev => ({ ...prev, [name]: d.columns || [] })))
        .catch(() => {})
    }
  }

  const filtered = tables.filter(t =>
    !search.trim() || t.name.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <div className="flex flex-col h-full border-r border-border bg-card">
      <div className="p-2.5 border-b border-border">
        <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">Schema</div>
        <input type="text" value={search} onChange={e => setSearch(e.target.value)}
          placeholder="Filter tables…"
          className="w-full rounded-md border border-border bg-muted px-2.5 py-1.5 text-xs text-foreground font-sans outline-none" />
      </div>
      <div className="flex-1 overflow-y-auto">
        {filtered.map(t => (
          <div key={t.name}>
            <button onClick={() => toggle(t.name)}
              className={cn(
                'flex items-center justify-between w-full bg-transparent border-none cursor-pointer font-sans text-left px-2.5 py-1.5 text-xs hover:bg-muted/50',
                expanded[t.name] ? 'text-foreground font-medium' : 'text-muted-foreground',
              )}>
              <span className="font-mono truncate">{expanded[t.name] ? '▾' : '▸'} {t.name}</span>
              <span className="text-[10px] text-muted-foreground ml-1 shrink-0">{fmtCompact(t.row_count)}</span>
            </button>
            {expanded[t.name] && schemas[t.name] && (
              <div className="pl-5 pr-2.5 pb-1">
                {schemas[t.name].map(c => (
                  <div key={c.column_name} className="flex items-center justify-between py-0.5 text-[11px]">
                    <span className="font-mono text-foreground truncate">{c.column_name}</span>
                    <span className="text-[10px] text-muted-foreground ml-1.5 shrink-0">{c.data_type.replace('without time zone', '')}</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── SQL Editor ── */

export function SqlEditor({ tables, mobile, initialSql }: {
  tables: TableInfo[]
  mobile?: boolean
  initialSql?: string
}) {
  const [input, setInput] = useState(initialSql || '')
  const [result, setResult] = useState<{ columns: string[]; rows: Record<string, unknown>[]; error?: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const [history, setHistory] = useState<HistoryEntry[]>(loadHistory)
  const [showHistory, setShowHistory] = useState(false)
  const [showSchema, setShowSchema] = useState(!mobile)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => { if (initialSql) setInput(initialSql) }, [initialSql])

  async function runSQL() {
    if (!input.trim()) return
    setLoading(true); setResult(null)
    try {
      const r = await fetch(`${API}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql: input }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail)
      setResult({ columns: d.columns, rows: d.rows })
      // Save to history
      const entry: HistoryEntry = { sql: input.trim(), ts: Date.now(), rowCount: d.rows.length }
      const newHistory = [entry, ...history.filter(h => h.sql !== entry.sql)].slice(0, MAX_HISTORY)
      setHistory(newHistory)
      saveHistory(newHistory)
    } catch (e) {
      setResult({ columns: [], rows: [], error: e instanceof Error ? e.message : 'Unknown error' })
    } finally { setLoading(false) }
  }

  function loadFromHistory(entry: HistoryEntry) {
    setInput(entry.sql)
    setShowHistory(false)
    textareaRef.current?.focus()
  }

  return (
    <div className={cn('flex h-full', mobile ? 'flex-col' : 'flex-row gap-0')}>
      {/* Schema sidebar */}
      {showSchema && !mobile && (
        <div className="w-[220px] shrink-0 h-full">
          <SchemaSidebar tables={tables} />
        </div>
      )}

      <div className="flex-1 flex flex-col gap-3 min-w-0 px-4 h-full overflow-auto">
        {/* Toolbar */}
        <div className="flex items-center gap-2 shrink-0">
          {!mobile && (
            <button onClick={() => setShowSchema(!showSchema)}
              className="px-2.5 py-1.5 bg-muted border border-border rounded-md text-[11px] text-muted-foreground cursor-pointer hover:text-foreground">
              {showSchema ? '◁ Schema' : '▷ Schema'}
            </button>
          )}
          <button onClick={() => setShowHistory(!showHistory)}
            className={cn(
              'px-2.5 py-1.5 border rounded-md text-[11px] font-medium cursor-pointer',
              showHistory ? 'bg-primary/10 border-primary/25 text-primary' : 'bg-muted border-border text-muted-foreground',
            )}>
            History ({history.length})
          </button>
          <div className="flex-1" />
          <span className="text-[11px] text-muted-foreground">Cmd+Enter to run · Read-only queries only</span>
        </div>

        {/* History panel */}
        {showHistory && history.length > 0 && (
          <div className="border border-border rounded-lg bg-card max-h-[200px] overflow-y-auto shrink-0">
            {history.map((h, i) => (
              <button key={i} onClick={() => loadFromHistory(h)}
                className="w-full px-3 py-2 bg-transparent border-none text-left cursor-pointer font-sans hover:bg-muted border-b border-border/50 flex items-center gap-2">
                <pre className="flex-1 m-0 text-[11px] font-mono text-foreground whitespace-nowrap overflow-hidden text-ellipsis">
                  {h.sql}
                </pre>
                <span className="text-[10px] text-muted-foreground shrink-0">
                  {h.rowCount != null && `${h.rowCount} rows · `}
                  {new Date(h.ts).toLocaleDateString()}
                </span>
              </button>
            ))}
          </div>
        )}

        {/* Editor */}
        <div className={cn('flex gap-2 shrink-0', mobile ? 'flex-col' : 'flex-row')}>
          <textarea ref={textareaRef} value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) runSQL() }}
            placeholder="SELECT * FROM teams LIMIT 10"
            className="flex-1 rounded-md border border-border bg-muted px-3 py-3 text-[13px] text-foreground font-mono resize-y min-h-[120px] outline-none" />
          <button onClick={runSQL} disabled={loading || !input.trim()}
            className={cn(
              'px-6 py-2.5 bg-primary text-primary-foreground rounded-lg text-sm font-semibold cursor-pointer font-sans disabled:opacity-50',
              mobile ? 'self-stretch' : 'self-start',
              loading && 'cursor-wait',
            )}>
            {loading ? '…' : 'Run SQL'}
          </button>
        </div>

        {/* Results */}
        {result && (result.error ? (
          <div className="p-3.5 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive text-[13px] shrink-0">
            {result.error}
          </div>
        ) : (
          <div className="flex-1 min-h-[200px]">
            <ResultsGrid columns={result.columns} rows={result.rows} mobile={mobile} />
          </div>
        ))}
      </div>
    </div>
  )
}
