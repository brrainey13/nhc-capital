import React, { useEffect, useRef, useState } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'
import Dashboard from './Dashboard'
import { ThemeToggle } from '@/components/ui/theme-toggle'
import { cn, useIsMobile } from '@/lib/utils'

const API = '/api'

/* ── Types ── */

interface TableInfo { name: string; row_count: number; database?: string }
interface SchemaColumn { column_name: string; data_type: string; is_nullable: string }
interface ExampleQuery { label: string; sql: string }
interface PreviewData {
  table: string; database: string; row_count: number; column_count: number
  schema: SchemaColumn[]; columns: string[]; sample_rows: Record<string, unknown>[]
}
interface ActiveFilter { id: string; column: string; operator: string; value: string; value2?: string }

const ForeclosureMap = React.lazy(() => import('./ForeclosureMap'))
const SalesChart = React.lazy(() => import('./SalesChart'))
const BankrollTracker = React.lazy(() => import('./BankrollTracker'))
const NHLModel = React.lazy(() => import('./NHLModel'))
const DataPlayground = React.lazy(() => import('./DataPlayground'))
const OwnershipTracker = React.lazy(() => import('./OwnershipTracker'))

type Page = 'home' | 'explorer' | 'query' | 'playground' | 'realestate' | 'bankroll' | 'nhlmodel' | 'ownership'
type SortDir = 'asc' | 'desc' | null
type ExplorerView = 'tree' | 'detail' | 'data'

/* ── Table → Project grouping ── */

interface SubGroup { label: string; match: (name: string) => boolean }
interface ProjectGroup { label: string; icon: string; match: (name: string) => boolean; subGroups?: SubGroup[] }

const PROJECT_GROUPS: ProjectGroup[] = [
  { label: 'NHL Betting', icon: '', match: (n) => ['games','game_team_stats','player_stats','players','teams','standings','schedules','injuries','injuries_live','lineup_absences','period_scores','goalie_advanced','goalie_saves_by_strength','goalie_starts','goalie_stats','saves_odds','sog_odds','predictions','model_runs','theses','live_game_snapshots','positions','player_odds','team_odds'].includes(n) },
  { label: 'Polymarket', icon: '', match: (n) => ['markets','market_snapshots'].includes(n) },
  { label: 'Real Estate', icon: '', match: (n) => n.startsWith('cook_county_') || n.startsWith('ct_') || n.startsWith('whitney_glen_') || n === 'sf_rentals' || ['commercial_valuations','parcel_sales','parcel_universe','data_refresh_log'].includes(n),
    subGroups: [
      { label: 'Illinois Data', match: (n) => ['parcel_sales','parcel_universe','commercial_valuations'].includes(n) || n.startsWith('cook_county_') },
      { label: 'Connecticut Data', match: (n) => n.startsWith('ct_') || n.startsWith('whitney_glen_') || ['data_refresh_log','sf_rentals'].includes(n) },
    ],
  },
  { label: 'Crypto', icon: '₿', match: (n) => n.startsWith('crypto_') },
  { label: 'Dashboard', icon: '', match: (n) => ['kanban_events','kanban_tasks','agent_log','api_snapshots','human_notes'].includes(n) },
]

interface TableGroup {
  label: string; icon: string; tables: TableInfo[]; totalRows: number
  subGroups?: { label: string; tables: TableInfo[]; totalRows: number }[]
}

function groupTables(tables: TableInfo[]): TableGroup[] {
  const groups: TableGroup[] = PROJECT_GROUPS.map(g => ({ label: g.label, icon: g.icon, tables: [] as TableInfo[], totalRows: 0 }))
  const other: TableInfo[] = []
  for (const t of tables) {
    const g = PROJECT_GROUPS.findIndex(g => g.match(t.name))
    if (g >= 0) groups[g].tables.push(t)
    else other.push(t)
  }
  if (other.length > 0) groups.push({ label: 'Other', icon: '', tables: [], totalRows: 0, subGroups: undefined })
  // Handle sub-groups
  for (let i = 0; i < PROJECT_GROUPS.length; i++) {
    const pg = PROJECT_GROUPS[i]
    if (pg.subGroups && groups[i].tables.length > 0) {
      const subs: { label: string; tables: TableInfo[]; totalRows: number }[] = pg.subGroups.map(sg => ({ label: sg.label, tables: [] as TableInfo[], totalRows: 0 }))
      const ungrouped: TableInfo[] = []
      for (const t of groups[i].tables) {
        const si = pg.subGroups.findIndex(sg => sg.match(t.name))
        if (si >= 0) subs[si].tables.push(t)
        else ungrouped.push(t)
      }
      groups[i].subGroups = subs.filter(s => s.tables.length > 0).map(s => ({ ...s, totalRows: s.tables.reduce((sum, t) => sum + t.row_count, 0) }))
      if (ungrouped.length > 0) {
        if (!groups[i].subGroups) groups[i].subGroups = []
        groups[i].subGroups!.push({ label: 'Other', tables: ungrouped, totalRows: ungrouped.reduce((s, t) => s + t.row_count, 0) })
      }
      // Clear flat tables since we use subGroups now
      groups[i].tables = []
    }
  }
  // Re-add "Other" ungrouped tables
  if (other.length > 0) {
    const otherGroup = groups[groups.length - 1]
    otherGroup.tables = other
  }
  return groups.filter(g => g.tables.length > 0 || (g.subGroups && g.subGroups.length > 0)).map(g => ({ ...g, totalRows: g.tables.reduce((s, t) => s + t.row_count, 0) + (g.subGroups?.reduce((s, sg) => s + sg.totalRows, 0) ?? 0) }))
}

const NUMERIC_TYPES = new Set(['integer','bigint','smallint','numeric','real','double precision'])
const DATE_TYPES = new Set(['date','timestamp without time zone','timestamp with time zone'])
function isNumericType(dt: string) { return NUMERIC_TYPES.has(dt) }
function isDateType(dt: string) { return DATE_TYPES.has(dt) }

function operatorsForType(dt: string): { value: string; label: string }[] {
  if (isNumericType(dt)) return [
    { value: 'eq', label: '=' }, { value: 'ne', label: '≠' }, { value: 'gt', label: '>' },
    { value: 'lt', label: '<' }, { value: 'gte', label: '≥' }, { value: 'lte', label: '≤' },
    { value: 'between', label: 'between' },
  ]
  if (isDateType(dt)) return [
    { value: 'before', label: 'before' }, { value: 'after', label: 'after' }, { value: 'between', label: 'between' },
  ]
  return [
    { value: 'contains', label: 'contains' }, { value: 'equals', label: 'equals' },
    { value: 'starts_with', label: 'starts with' }, { value: 'ends_with', label: 'ends with' },
  ]
}

/* ── Helpers ── */

function fmtNum(n: number): string { return n.toLocaleString() }
function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}
function fmtCompact(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

let filterId = 0
function nextFilterId() { return `f${++filterId}` }

/* ── Type Badge ── */

function TypeBadge({ type }: { type: string }) {
  return (
    <span className={cn(
      'px-2 py-0.5 rounded text-[10px] font-medium whitespace-nowrap',
      isNumericType(type) && 'bg-primary/10 text-primary',
      isDateType(type) && 'bg-[hsl(var(--chart-3))]/10 text-[hsl(var(--chart-3))]',
      !isNumericType(type) && !isDateType(type) && 'bg-foreground/5 text-muted-foreground',
    )}>
      {type}
    </span>
  )
}

/* ── Combo Box ── */

function ComboBox({ value, onChange, tableName, column, placeholder, inputType, className: outerClassName, mobile }: {
  value: string; onChange: (v: string) => void; tableName: string; column: string
  placeholder?: string; inputType?: string; className?: string; mobile?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [options, setOptions] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  function fetchOptions(q: string) {
    setLoading(true)
    const params = new URLSearchParams({ column, limit: '50' })
    if (q.trim()) params.set('q', q)
    fetch(`${API}/tables/${tableName}/distinct?${params}`)
      .then(r => r.ok ? r.json() : [])
      .then(data => setOptions((data as unknown[]).map(v => String(v ?? 'NULL'))))
      .catch(() => setOptions([]))
      .finally(() => setLoading(false))
  }

  useEffect(() => {
    if (!open) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => fetchOptions(value), 200)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [open, value, column, tableName])

  useEffect(() => {
    function handleClick(e: MouseEvent) { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  return (
    <div ref={ref} className={cn('relative', outerClassName)}>
      <input type={inputType || 'text'} value={value} placeholder={placeholder || 'Value'}
        onFocus={() => setOpen(true)} onChange={e => { onChange(e.target.value); setOpen(true) }}
        className={cn('w-full rounded-md border border-border bg-muted px-2.5 py-1.5 text-[13px] text-foreground font-sans outline-none', mobile && 'h-11')} />
      {open && (
        <div className={cn('absolute top-full left-0 right-0 mt-0.5 z-30 bg-card border border-border rounded-md shadow-xl overflow-y-auto', mobile ? 'max-h-[260px]' : 'max-h-[200px]')}>
          {loading && <div className="px-3 py-2 text-[11px] text-muted-foreground">Loading…</div>}
          {!loading && options.length === 0 && <div className="px-3 py-2 text-[11px] text-muted-foreground">No values</div>}
          {options.map((opt, i) => (
            <button key={i} onClick={() => { onChange(opt); setOpen(false) }}
              className={cn(
                'w-full px-3 py-1.5 bg-transparent border-none text-xs text-foreground text-left cursor-pointer font-sans hover:bg-muted',
                mobile && 'py-3 min-h-[44px] text-sm',
                i < options.length - 1 && 'border-b border-border',
              )}>
              {opt}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Filter Bar ── */

function FilterBar({ columns, typeMap, filters, onChange, mobile, tableName }: {
  columns: string[]; typeMap: Record<string, string>; filters: ActiveFilter[]
  onChange: (filters: ActiveFilter[]) => void; mobile?: boolean; tableName: string
}) {
  function addFilter() {
    const col = columns[0] || ''
    const dt = typeMap[col] || ''
    const ops = operatorsForType(dt)
    onChange([...filters, { id: nextFilterId(), column: col, operator: ops[0].value, value: '' }])
  }
  function updateFilter(id: string, patch: Partial<ActiveFilter>) {
    onChange(filters.map(f => {
      if (f.id !== id) return f
      const updated = { ...f, ...patch }
      if (patch.column && patch.column !== f.column) {
        const dt = typeMap[patch.column] || ''
        updated.operator = operatorsForType(dt)[0].value
        updated.value = ''; updated.value2 = undefined
      }
      return updated
    }))
  }
  function removeFilter(id: string) { onChange(filters.filter(f => f.id !== id)) }

  return (
    <div className={cn('flex flex-col', mobile ? 'gap-3' : 'gap-2')}>
      {filters.map(f => {
        const dt = typeMap[f.column] || ''
        const ops = operatorsForType(dt)
        const isBetween = f.operator === 'between'
        const inputType = isNumericType(dt) ? 'number' : isDateType(dt) ? 'date' : 'text'
        return (
          <div key={f.id} className={cn('flex gap-1.5 flex-wrap', mobile ? 'flex-col items-stretch gap-2' : 'flex-row items-center')}>
            <div className="flex gap-2">
              <select value={f.column} onChange={e => updateFilter(f.id, { column: e.target.value })}
                className={cn('rounded-md border border-border bg-muted px-2.5 py-1.5 text-[13px] text-foreground font-sans outline-none flex-1', mobile && 'h-11 text-sm')}>
                {columns.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              <select value={f.operator} onChange={e => updateFilter(f.id, { operator: e.target.value })}
                className={cn('rounded-md border border-border bg-muted px-2.5 py-1.5 text-[13px] text-foreground font-sans outline-none w-[110px]', mobile && 'h-11 text-sm')}>
                {ops.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <button onClick={() => removeFilter(f.id)}
                className={cn('bg-transparent border-none cursor-pointer text-muted-foreground leading-none flex items-center justify-center', mobile ? 'text-[22px] p-1 min-w-[44px] min-h-[44px]' : 'text-lg px-1.5 py-1')}>
                ×
              </button>
            </div>
            <ComboBox value={f.value} onChange={v => updateFilter(f.id, { value: v })} tableName={tableName} column={f.column} placeholder={isBetween ? 'Min' : 'Value'} inputType={inputType} mobile={mobile}
              className={cn(mobile ? 'w-full' : isBetween ? 'w-[100px]' : 'w-[160px]')} />
            {isBetween && (
              <>
                <span className="text-xs text-muted-foreground text-center">to</span>
                <ComboBox value={f.value2 ?? ''} onChange={v => updateFilter(f.id, { value2: v })} tableName={tableName} column={f.column} placeholder="Max" inputType={inputType} mobile={mobile}
                  className={cn(mobile ? 'w-full' : 'w-[100px]')} />
              </>
            )}
          </div>
        )
      })}
      <button onClick={addFilter}
        className={cn('px-3 py-1 bg-muted border border-border rounded-md text-[11px] text-muted-foreground font-medium cursor-pointer font-sans self-start', mobile && 'min-h-[44px] text-sm px-4 py-2.5')}>
        + Add Filter
      </button>
    </div>
  )
}

/* ── Table Detail Panel (the new tree detail view) ── */

function TableDetailPanel({ tableName, onBrowse, onRunQuery, mobile }: {
  tableName: string; onBrowse: () => void; onRunQuery: (sql: string) => void; mobile: boolean
}) {
  const [preview, setPreview] = useState<PreviewData | null>(null)
  const [examples, setExamples] = useState<ExampleQuery[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    Promise.all([
      fetch(`${API}/tables/${tableName}/preview?rows=5`).then(r => r.json()),
      fetch(`${API}/tables/${tableName}/examples`).then(r => r.json()),
    ]).then(([prev, ex]) => {
      setPreview(prev)
      setExamples(ex)
    }).finally(() => setLoading(false))
  }, [tableName])

  if (loading) return <div className="p-10 text-center text-muted-foreground">Loading…</div>
  if (!preview) return <div className="p-10 text-center text-muted-foreground">Failed to load</div>

  return (
    <div className="flex flex-col gap-4 overflow-auto h-full pb-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-2.5">
        <div>
          <h2 className={cn('font-bold text-foreground m-0', mobile ? 'text-lg' : 'text-[22px]')}>{tableName}</h2>
          <div className="text-xs text-muted-foreground mt-1">
            {preview.database} · {fmtNum(preview.row_count)} rows · {preview.column_count} columns
          </div>
        </div>
        <button onClick={onBrowse} className="bg-primary text-primary-foreground px-5 py-2.5 rounded-md border-none text-[13px] font-semibold cursor-pointer">
          Browse Full Data
        </button>
      </div>

      {/* Schema */}
      <div className="rounded-lg border border-border bg-card p-3.5">
        <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2.5">
          Schema ({preview.schema.length} columns)
        </div>
        <div className={cn('grid gap-1', mobile ? 'grid-cols-1' : 'grid-cols-[repeat(auto-fill,minmax(280px,1fr))]')}>
          {preview.schema.map(c => (
            <div key={c.column_name} className="flex items-center gap-2 px-2 py-1.5 rounded-md bg-muted">
              <span className="font-mono text-xs text-foreground flex-1">{c.column_name}</span>
              <TypeBadge type={c.data_type} />
              {c.is_nullable === 'YES' && <span className="text-[9px] text-muted-foreground">NULL</span>}
            </div>
          ))}
        </div>
      </div>

      {/* Sample Data */}
      {preview.sample_rows.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-0 overflow-hidden">
          <div className="px-3.5 py-2.5 text-[11px] font-semibold text-muted-foreground uppercase tracking-wider border-b border-border">
            Sample Data (first {preview.sample_rows.length} rows)
          </div>
          <div className="overflow-auto">
            <table style={{ minWidth: preview.columns.length * 140 }} className="border-collapse text-xs">
              <thead>
                <tr>{preview.columns.map(c => <th key={c} className="px-3 py-2 text-left border-b-2 border-border text-[11px] font-semibold text-muted-foreground bg-card whitespace-nowrap overflow-hidden text-ellipsis uppercase tracking-wider">{c}</th>)}</tr>
              </thead>
              <tbody>
                {preview.sample_rows.map((row, i) => (
                  <tr key={i} className="border-b border-border">
                    {preview.columns.map(c => (
                      <td key={c} className="px-3 py-1.5 max-w-[220px] overflow-hidden text-ellipsis whitespace-nowrap text-xs text-foreground">
                        {row[c] === null || row[c] === undefined
                          ? <span className="text-muted-foreground italic">null</span>
                          : String(row[c])}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Example Queries */}
      {examples.length > 0 && (
        <div className="rounded-lg border border-border bg-card p-3.5">
          <div className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider mb-2.5">
            Example Queries
          </div>
          <div className="flex flex-col gap-2">
            {examples.map((ex, i) => (
              <div key={i} className="flex items-center gap-2.5 px-3 py-2.5 bg-muted rounded-lg border border-border">
                <div className="flex-1 min-w-0">
                  <div className="text-[13px] font-medium text-foreground mb-1">{ex.label}</div>
                  <pre className="m-0 text-[11px] font-mono text-muted-foreground whitespace-pre-wrap break-all">{ex.sql}</pre>
                </div>
                <button onClick={() => onRunQuery(ex.sql)} className="bg-primary/10 text-primary border border-primary/25 px-3.5 py-2 rounded-md font-semibold cursor-pointer shrink-0">
                  ▶ Run
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Mobile Card View ── */

function MobileCardList({ data, columns, onLoadMore, hasMore, loading }: {
  data: Record<string, unknown>[]; columns: string[]
  onLoadMore?: () => void; hasMore?: boolean; loading?: boolean
}) {
  const [visibleCols, setVisibleCols] = useState<string[]>([])
  const [showColPicker, setShowColPicker] = useState(false)
  const containerRef = useRef<HTMLDivElement>(null)

  useEffect(() => { setVisibleCols(columns.slice(0, 5)) }, [columns.join(',')])
  const displayCols = visibleCols.length > 0 ? visibleCols : columns.slice(0, 5)

  useEffect(() => {
    const el = containerRef.current
    if (!el || !onLoadMore) return
    function onScroll() { if (!el || !hasMore || loading) return; if (el.scrollTop + el.clientHeight >= el.scrollHeight - 200) onLoadMore!() }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [hasMore, loading, onLoadMore])

  return (
    <div className="flex-1 flex flex-col min-h-0">
      <div className="sticky top-0 z-[5] bg-background py-2 flex items-center justify-end gap-2 shrink-0">
        <button onClick={() => setShowColPicker(!showColPicker)} className="px-3 py-1 bg-muted border border-border rounded-md text-[11px] text-muted-foreground font-medium cursor-pointer font-sans min-h-[44px] text-[13px] px-3.5 py-2">Columns ({displayCols.length}/{columns.length})</button>
      </div>
      {showColPicker && (
        <div className="bg-card border border-border rounded-lg p-3 mb-2 max-h-[200px] overflow-y-auto">
          <div className="flex gap-1.5 mb-2">
            <button onClick={() => setVisibleCols(columns)} className="px-3 py-1 bg-muted border border-border rounded-md text-[11px] text-muted-foreground font-medium cursor-pointer font-sans">All</button>
            <button onClick={() => setVisibleCols(columns.slice(0, 5))} className="px-3 py-1 bg-muted border border-border rounded-md text-[11px] text-muted-foreground font-medium cursor-pointer font-sans">First 5</button>
          </div>
          <div className="flex flex-wrap gap-1.5">
            {columns.map(col => {
              const active = displayCols.includes(col)
              return (
                <button key={col} onClick={() => setVisibleCols(prev => { const cur = prev.length > 0 ? prev : columns.slice(0, 5); return active ? cur.filter(c => c !== col) : [...cur, col] })}
                  className={cn(
                    'px-3 py-1 border rounded-md text-xs cursor-pointer font-sans min-h-[44px] px-3.5 py-2',
                    active ? 'bg-primary/10 text-primary border-primary/25' : 'bg-muted text-muted-foreground border-border',
                  )}>
                  {col}
                </button>
              )
            })}
          </div>
        </div>
      )}
      <div ref={containerRef} className="flex-1 overflow-auto flex flex-col gap-2">
        {data.length === 0 && !loading && <div className="p-10 text-center text-muted-foreground">No data</div>}
        {data.map((row, i) => (
          <div key={i} className="bg-card border border-border rounded-lg p-3.5">
            {displayCols.map(col => {
              const v = row[col]
              return (
                <div key={col} className="flex justify-between py-1.5 border-b border-border gap-3 min-h-[32px]">
                  <span className="text-xs text-muted-foreground font-medium shrink-0">{col}</span>
                  <span className={cn(
                    'text-[13px] text-right overflow-hidden text-ellipsis whitespace-nowrap',
                    v === null || v === undefined ? 'text-muted-foreground italic' : 'text-foreground',
                  )}>
                    {v === null || v === undefined ? 'null' : String(v)}
                  </span>
                </div>
              )
            })}
          </div>
        ))}
        {loading && <div className="p-4 text-center text-primary text-[13px]">Loading more…</div>}
        {!hasMore && data.length > 0 && <div className="p-3 text-center text-muted-foreground text-xs">All rows loaded</div>}
      </div>
    </div>
  )
}

/* ── Virtualized Data Table ── */

function DataTable({ tableName, mobile, onBack }: { tableName: string; mobile: boolean; onBack: () => void }) {
  const [allData, setAllData] = useState<Record<string, unknown>[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [schema, setSchema] = useState<SchemaColumn[]>([])
  const [total, setTotal] = useState(0)
  const [filteredTotal, setFilteredTotal] = useState(0)
  const [sortBy, setSortBy] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>(null)
  const [filters, setFilters] = useState<ActiveFilter[]>([])
  const [groupBy, setGroupBy] = useState<string | null>(null)
  const [groupData, setGroupData] = useState<{ value: unknown; count: number }[]>([])
  const [loading, setLoading] = useState(false)
  const [hasMore, setHasMore] = useState(true)
  const [quickSearch, setQuickSearch] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const BATCH = 200
  const tableContainerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const fetchingRef = useRef(false)

  useEffect(() => { fetch(`${API}/tables/${tableName}/schema`).then(r => r.json()).then(d => setSchema(d.columns)) }, [tableName])
  const typeMap = (() => { const m: Record<string, string> = {}; for (const c of schema) m[c.column_name] = c.data_type; return m })()

  useEffect(() => {
    setAllData([]); setSortBy(null); setSortDir(null); setFilters([])
    setGroupBy(null); setGroupData([]); setHasMore(true); setQuickSearch(''); setShowFilters(false)
  }, [tableName])

  const buildFilterParam = () => {
    const active = filters.filter(f => f.value.trim() !== '')
    if (active.length === 0) return null
    return JSON.stringify(active.map(f => {
      const dt = typeMap[f.column] || ''
      if (f.operator === 'between') {
        const vals = isNumericType(dt) ? [Number(f.value), Number(f.value2 ?? f.value)] : [f.value, f.value2 ?? f.value]
        return { column: f.column, operator: f.operator, value: vals }
      }
      return { column: f.column, operator: f.operator, value: isNumericType(dt) ? Number(f.value) : f.value }
    }))
  }

  const buildUrl = (offset: number) => {
    const params = new URLSearchParams({ limit: String(BATCH), offset: String(offset) })
    if (sortBy && sortDir) { params.set('sort_by', sortBy); params.set('sort_dir', sortDir) }
    const fp = buildFilterParam()
    if (fp) params.set('filters', fp)
    return `${API}/tables/${tableName}/data?${params}`
  }

  const fetchBatch = async (offset: number, append: boolean) => {
    if (fetchingRef.current) return
    fetchingRef.current = true; setLoading(true)
    try {
      const r = await fetch(buildUrl(offset)); const d = await r.json()
      if (append) setAllData(prev => [...prev, ...d.rows])
      else { setAllData(d.rows); setColumns(d.columns) }
      setTotal(d.total); setFilteredTotal(d.filtered_total)
      setHasMore(offset + d.rows.length < d.filtered_total)
    } finally { fetchingRef.current = false; setLoading(false) }
  }

  // Refetch on sort/table change (NOT on filters — that's handled by the debounced effect below)
  useEffect(() => { setAllData([]); setHasMore(true); fetchBatch(0, false) }, [sortBy, sortDir, tableName])
  const onFiltersChange = (nf: ActiveFilter[]) => setFilters(nf)

  // Debounced refetch on filter changes
  const filterKey = JSON.stringify(filters.map(f => ({ c: f.column, o: f.operator, v: f.value, v2: f.value2 })))
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => { setAllData([]); setHasMore(true); fetchBatch(0, false) }, 400)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [filterKey])

  useEffect(() => {
    if (!groupBy) { setGroupData([]); return }
    fetch(`${API}/tables/${tableName}/grouped?group_by=${groupBy}`).then(r => r.json()).then(setGroupData)
  }, [tableName, groupBy])

  function handleSort(col: string) {
    if (sortBy !== col) { setSortBy(col); setSortDir('asc') }
    else if (sortDir === 'asc') setSortDir('desc')
    else { setSortBy(null); setSortDir(null) }
  }

  function filterByGroup(value: unknown) {
    if (!groupBy) return
    const dt = typeMap[groupBy] || ''
    setFilters(prev => [...prev, { id: nextFilterId(), column: groupBy, operator: isNumericType(dt) ? 'eq' : 'equals', value: String(value ?? '') }])
    setGroupBy(null)
  }

  const displayData = (() => {
    if (!quickSearch.trim()) return allData
    const q = quickSearch.toLowerCase()
    return allData.filter(row => Object.values(row).some(v => v != null && String(v).toLowerCase().includes(q)))
  })()

  const loadMoreMobile = () => {
    if (hasMore && !fetchingRef.current) fetchBatch(allData.length, true)
  }

  const colDefs: ColumnDef<Record<string, unknown>, unknown>[] = columns.map(c => ({
      accessorKey: c, header: c, size: 160,
      cell: (info: { getValue: () => unknown }) => {
        const v = info.getValue()
        if (v === null || v === undefined) return <span className="text-muted-foreground italic">null</span>
        if (typeof v === 'boolean') return <span className={v ? 'text-success' : 'text-destructive'}>{String(v)}</span>
        return String(v)
      },
    }))

  const table = useReactTable({ data: displayData, columns: colDefs, getCoreRowModel: getCoreRowModel(), manualSorting: true, manualFiltering: true })
  const { rows: tableRows } = table.getRowModel()
  const rowVirtualizer = useVirtualizer({ count: tableRows.length, getScrollElement: () => tableContainerRef.current, estimateSize: () => 36, overscan: 20 })

  useEffect(() => {
    const el = tableContainerRef.current
    if (!el) return
    function onScroll() { if (!el || !hasMore || fetchingRef.current) return; if (el.scrollTop + el.clientHeight >= el.scrollHeight - 200) fetchBatch(allData.length, true) }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [hasMore, allData.length, fetchBatch])

  const activeFilterCount = filters.filter(f => f.value.trim()).length

  return (
    <div className={cn('flex flex-col h-full', mobile ? 'gap-2' : 'gap-2.5')}>
      {/* Back + toolbar */}
      <div className={cn('flex items-center gap-2 flex-wrap', mobile && 'sticky top-0 z-10 bg-background pb-1')}>
        <button onClick={onBack} className={cn('px-3 py-1 bg-muted border border-border rounded-md text-[11px] text-muted-foreground font-medium cursor-pointer font-sans flex items-center gap-1', mobile ? 'h-11' : 'h-9')}>
          ← Back
        </button>
        <h3 className={cn('m-0 font-bold text-foreground', mobile ? 'text-[15px]' : 'text-base')}>{tableName}</h3>
        <div className={cn('relative', mobile ? 'flex-[1_1_100%]' : 'flex-[0_0_220px] ml-auto')}>
          <span className="absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground text-sm pointer-events-none"></span>
          <input type="text" value={quickSearch} onChange={e => setQuickSearch(e.target.value)} placeholder="Search loaded rows…"
            className={cn('w-full rounded-md border border-border bg-muted pl-8 pr-2.5 py-1.5 text-foreground font-sans outline-none', mobile ? 'h-11 text-base' : 'h-9 text-[13px]')} />
        </div>
        <button onClick={() => setShowFilters(!showFilters)}
          className={cn(
            'px-3 py-1 border rounded-md text-[11px] font-medium cursor-pointer font-sans flex items-center gap-1',
            mobile ? 'h-11' : 'h-9',
            showFilters ? 'bg-primary/10 border-primary/25 text-primary' : 'bg-muted border-border text-muted-foreground',
          )}>
          Filters{activeFilterCount > 0 && <span className="bg-primary text-primary-foreground rounded-full px-1.5 text-[10px] font-bold">{activeFilterCount}</span>}
        </button>
        {!mobile && (
          <div className="flex items-center gap-1.5">
            <span className="text-xs text-muted-foreground">Group:</span>
            <select value={groupBy ?? ''} onChange={e => setGroupBy(e.target.value || null)} className="rounded-md border border-border bg-muted px-2.5 py-1.5 text-[13px] text-foreground font-sans outline-none">
              <option value="">None</option>
              {columns.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
        )}
      </div>

      {showFilters && (
        <div className="bg-card border border-border rounded-lg p-3">
          <FilterBar columns={columns} typeMap={typeMap} filters={filters} onChange={onFiltersChange} mobile={mobile} tableName={tableName} />
          {mobile && (
            <div className="flex items-center gap-1.5 mt-2.5">
              <span className="text-xs text-muted-foreground">Group:</span>
              <select value={groupBy ?? ''} onChange={e => setGroupBy(e.target.value || null)} className="rounded-md border border-border bg-muted px-2.5 py-1.5 text-[13px] text-foreground font-sans outline-none flex-1 h-11 text-sm">
                <option value="">None</option>
                {columns.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          )}
        </div>
      )}

      {/* Status */}
      <div className="text-xs text-muted-foreground flex gap-3 items-center flex-wrap">
        <span className="tabular-nums">
          {filteredTotal < total ? <><strong className="text-foreground">{fmtNum(filteredTotal)}</strong> of {fmtNum(total)} rows</> : <><strong className="text-foreground">{fmtNum(total)}</strong> rows</>}
        </span>
        <span className="text-muted-foreground">·</span>
        <span>Showing {fmtNum(displayData.length)}</span>
        {loading && <span className="text-primary">● Loading…</span>}
      </div>

      {/* Group panels */}
      {groupBy && groupData.length > 0 && (
        <div className="max-h-[180px] overflow-y-auto border border-border rounded-lg bg-card">
          {groupData.map((g, i) => (
            <button key={String(g.value ?? 'NULL')} onClick={() => filterByGroup(g.value)}
              className={cn(
                'w-full px-3.5 py-2.5 bg-transparent border-none cursor-pointer flex justify-between text-[13px] font-sans text-foreground',
                mobile && 'py-3 min-h-[44px]',
                i < groupData.length - 1 && 'border-b border-border',
              )}>
              <span>{String(g.value ?? 'NULL')}</span>
              <span className="text-muted-foreground tabular-nums">{fmtNum(g.count)}</span>
            </button>
          ))}
        </div>
      )}

      {/* Data */}
      {mobile ? (
        <MobileCardList data={displayData} columns={columns} onLoadMore={loadMoreMobile} hasMore={hasMore} loading={loading} />
      ) : (
        <div ref={tableContainerRef} className="scroll-visible flex-[1_1_0] overflow-auto border border-border rounded-lg bg-card min-h-0 mb-6">
          <table style={{ minWidth: columns.length * 160 }} className="border-collapse text-xs">
            <thead className="sticky top-0 z-[1]">
              <tr>
                {table.getHeaderGroups()[0]?.headers.map(h => (
                  <th key={h.id} onClick={() => handleSort(h.column.id)}
                    className="px-3 py-2 text-left border-b-2 border-border text-[11px] font-semibold text-muted-foreground bg-card whitespace-nowrap overflow-hidden text-ellipsis uppercase tracking-wider cursor-pointer select-none"
                    style={{ width: h.column.getSize() }}>
                    <span>{flexRender(h.column.columnDef.header, h.getContext())}</span>
                    <span className={cn('text-[10px] ml-1', sortBy === h.column.id ? 'text-primary opacity-100' : 'text-muted-foreground opacity-30')}>
                      {sortBy === h.column.id ? (sortDir === 'asc' ? '↑' : '↓') : '↕'}
                    </span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rowVirtualizer.getVirtualItems().length > 0 && (
                <tr><td style={{ height: rowVirtualizer.getVirtualItems()[0]?.start ?? 0, padding: 0 }} colSpan={columns.length} /></tr>
              )}
              {rowVirtualizer.getVirtualItems().map(vr => {
                const row = tableRows[vr.index]
                return (
                  <tr key={row.id} className="h-9 border-b border-border"
                    onMouseEnter={e => (e.currentTarget.style.background = 'hsl(var(--muted))')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                    {row.getVisibleCells().map(cell => (
                      <td key={cell.id} className="px-3 py-1.5 max-w-[220px] overflow-hidden text-ellipsis whitespace-nowrap text-xs text-foreground">{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                    ))}
                  </tr>
                )
              })}
              {rowVirtualizer.getVirtualItems().length > 0 && (
                <tr><td style={{ height: (() => { const items = rowVirtualizer.getVirtualItems(); const last = items[items.length - 1]; return rowVirtualizer.getTotalSize() - (last?.end ?? 0) })(), padding: 0 }} colSpan={columns.length} /></tr>
              )}
            </tbody>
          </table>
          {displayData.length === 0 && !loading && <div className="p-10 text-center text-muted-foreground">No data</div>}
        </div>
      )}
    </div>
  )
}

/* ── Query Page (SQL only — NL removed) ── */

function QueryPage({ mobile, initialSql }: { mobile: boolean; initialSql?: string }) {
  const [input, setInput] = useState(initialSql || '')
  const [result, setResult] = useState<{ columns: string[]; rows: Record<string, unknown>[]; error?: string } | null>(null)
  const [loading, setLoading] = useState(false)

  useEffect(() => { if (initialSql) setInput(initialSql) }, [initialSql])

  function runSQL() {
    if (!input.trim()) return
    setLoading(true); setResult(null)
    fetch(`${API}/query`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sql: input }) })
      .then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.detail); return d })
      .then(d => setResult({ columns: d.columns, rows: d.rows }))
      .catch(e => setResult({ columns: [], rows: [], error: e.message }))
      .finally(() => setLoading(false))
  }

  return (
    <div className="flex flex-col h-full gap-3 overflow-auto">
      <div className={cn('flex gap-2', mobile ? 'flex-col' : 'flex-row')}>
        <textarea value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) runSQL() }}
          placeholder="SELECT * FROM teams LIMIT 10"
          className="flex-1 rounded-md border border-border bg-muted px-3 py-3 text-[13px] text-foreground font-mono resize-y min-h-[100px] outline-none" />
        <button onClick={runSQL} disabled={loading || !input.trim()}
          className={cn('px-6 py-2.5 bg-primary text-primary-foreground rounded-lg text-sm font-semibold cursor-pointer font-sans disabled:opacity-50', mobile ? 'min-h-[44px] self-stretch' : 'self-start', loading && 'cursor-wait')}>
          {loading ? '…' : 'Run SQL'}
        </button>
      </div>
      <div className="text-[11px] text-muted-foreground">⌘+Enter to run · Read-only queries only (SELECT, WITH)</div>
      {result && (result.error ? (
        <div className="p-3.5 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive text-[13px]">{result.error}</div>
      ) : mobile ? (
        <MobileCardList data={result.rows} columns={result.columns} />
      ) : (
        <div className="scroll-visible flex-1 overflow-auto border border-border rounded-lg min-h-0 bg-card">
          <table style={{ minWidth: result.columns.length * 160 }} className="border-collapse text-xs">
            <thead className="sticky top-0">
              <tr>{result.columns.map(c => <th key={c} className="px-3 py-2 text-left border-b-2 border-border text-[11px] font-semibold text-muted-foreground bg-card whitespace-nowrap overflow-hidden text-ellipsis uppercase tracking-wider">{c}</th>)}</tr>
            </thead>
            <tbody>
              {result.rows.map((r, i) => (
                <tr key={i} className="border-b border-border"
                  onMouseEnter={e => (e.currentTarget.style.background = 'hsl(var(--muted))')}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                  {result!.columns.map(c => <td key={c} className="px-3 py-1.5 max-w-[220px] overflow-hidden text-ellipsis whitespace-nowrap text-xs text-foreground">{String(r[c] ?? '')}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          <div className="text-xs text-muted-foreground px-3 py-2 border-t border-border">{result.rows.length} rows</div>
        </div>
      ))}
    </div>
  )
}

/* ── Real Estate Page ── */

function RealEstatePage({ mobile }: { mobile: boolean }) {
  const [subView, setSubView] = useState<'listings' | 'sales'>('listings')
  const [selectedForeclosureId, setSelectedForeclosureId] = useState<number | null>(null)

  return (
    <div className="flex flex-col h-full gap-3">
      <div className="flex gap-0 shrink-0">
        <button onClick={() => setSubView('listings')}
          className={cn(
            'px-5 py-2.5 border border-border text-[13px] font-medium cursor-pointer font-sans rounded-l-lg',
            mobile && 'flex-1 min-h-[44px]',
            subView === 'listings' ? 'bg-primary text-primary-foreground border-primary' : 'bg-card text-muted-foreground',
          )}>
          Property Listings
        </button>
        <button onClick={() => setSubView('sales')}
          className={cn(
            'px-5 py-2.5 border border-border text-[13px] font-medium cursor-pointer font-sans rounded-r-lg',
            mobile && 'flex-1 min-h-[44px]',
            subView === 'sales' ? 'bg-primary text-primary-foreground border-primary' : 'bg-card text-muted-foreground',
          )}>
          Sales Comps
        </button>
      </div>
      {subView === 'listings' && (
        <div className="flex-1 rounded-lg overflow-hidden min-h-0">
          <React.Suspense fallback={<div className="text-muted-foreground p-10">Loading map...</div>}>
            <ForeclosureMap onOpenComps={(id) => { setSelectedForeclosureId(id); setSubView('sales') }} />
          </React.Suspense>
        </div>
      )}
      {subView === 'sales' && (
        <div className="flex-1 overflow-auto min-h-0">
          <React.Suspense fallback={<div className="text-muted-foreground p-10">Loading charts...</div>}>
            <SalesChart selectedForeclosureId={selectedForeclosureId} onSelectedForeclosure={(id) => setSelectedForeclosureId(id)} />
          </React.Suspense>
        </div>
      )}
    </div>
  )
}

/* ── Mobile Loading Fallback ── */

function MobileLoadingFallback({ label }: { label: string }) {
  return (
    <div className="flex h-full items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <div className="flex gap-1.5">
          <div className="h-2 w-2 rounded-full bg-primary mobile-loading-dot" />
          <div className="h-2 w-2 rounded-full bg-primary mobile-loading-dot" />
          <div className="h-2 w-2 rounded-full bg-primary mobile-loading-dot" />
        </div>
        <span className="text-sm text-muted-foreground">{label}…</span>
      </div>
    </div>
  )
}

/* ── Bottom Tab Bar (mobile) ── */

function BottomTabBar({ page, setPage }: { page: Page; setPage: (p: Page) => void }) {
  const tabs: { key: Page; icon: string; label: string }[] = [
    { key: 'home', icon: '', label: 'Home' },
    { key: 'nhlmodel', icon: '', label: 'Model' },
    { key: 'bankroll', icon: '', label: 'Bankroll' },
    { key: 'ownership', icon: '', label: 'Ownership' },
    { key: 'playground', icon: '', label: 'Data' },
  ]
  return (
    <nav className="flex bg-card border-t border-border pb-[max(env(safe-area-inset-bottom),8px)] shrink-0 sticky bottom-0 z-20">
      {tabs.map(t => (
        <button key={t.key} onClick={() => setPage(t.key)}
          className={cn(
            'flex-1 flex flex-col items-center justify-center gap-0.5 pt-2.5 pb-1 min-h-[56px] bg-transparent border-none cursor-pointer font-sans text-[10px] transition-colors',
            page === t.key ? 'text-primary font-semibold' : 'text-muted-foreground font-normal',
          )}
          style={{ WebkitTapHighlightColor: 'transparent' }}>
          <span className="text-[22px] leading-none">{t.icon}</span><span>{t.label}</span>
        </button>
      ))}
    </nav>
  )
}

/* ── Main App ── */

export default function App() {
  const mobile = useIsMobile()
  const [page, setPage] = useState<Page>('home')
  const [tables, setTables] = useState<TableInfo[]>([])

  // Explorer state: tree → detail → data
  const [explorerView, setExplorerView] = useState<ExplorerView>('tree')
  const [selectedTable, setSelectedTable] = useState<string | null>(null)
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({})
  const [sidebarSearch, setSidebarSearch] = useState('')
  const [querySql, setQuerySql] = useState('')

  const grouped = groupTables(tables)
  const filteredGroups = (() => {
    if (!sidebarSearch.trim()) return grouped
    const q = sidebarSearch.toLowerCase()
    return grouped.map(g => ({
      ...g,
      tables: g.tables.filter(t => t.name.toLowerCase().includes(q)),
      subGroups: g.subGroups?.map(sg => ({ ...sg, tables: sg.tables.filter(t => t.name.toLowerCase().includes(q)) })).filter(sg => sg.tables.length > 0),
    })).filter(g => g.tables.length > 0 || (g.subGroups && g.subGroups.length > 0))
  })()

  function selectTable(name: string) {
    setSelectedTable(name)
    setExplorerView('detail')
  }

  function toggleGroup(label: string) {
    setExpandedGroups(prev => ({ ...prev, [label]: !prev[label] }))
  }

  function handleRunQuery(sql: string) {
    setQuerySql(sql)
    setPage('query')
  }

  useEffect(() => {
    fetch(`${API}/tables`).then(r => r.ok ? r.json() : []).then(data => setTables(Array.isArray(data) ? data : [])).catch(() => setTables([]))
  }, [])

  const totalRows = tables.reduce((s, t) => s + t.row_count, 0)

  return (
    <div className="text-foreground bg-background h-screen flex flex-col antialiased font-sans">
      {/* Top Nav — desktop only */}
      {!mobile && (
        <nav className="sticky top-0 z-50 flex items-center gap-1 border-b border-border bg-card px-6 pt-[env(safe-area-inset-top)] min-h-[52px] shrink-0">
          <span className="text-base font-bold text-foreground tracking-tight whitespace-nowrap mr-7">
            NHC<span className="font-normal text-muted-foreground"> Admin</span>
          </span>
          {(['home', 'nhlmodel', 'bankroll', 'ownership', 'playground', 'realestate'] as Page[]).map(p => {
            const labels: Record<Page, string> = { home: 'Home', nhlmodel: 'Model Outputs', bankroll: 'Bankroll', ownership: 'Ownership', playground: 'Playground', explorer: 'Data', query: 'Query', realestate: 'Real Estate' }
            return (
              <button key={p} onClick={() => { setPage(p) }}
                className={cn('rounded-md px-3.5 py-2 text-[13px] font-medium text-muted-foreground bg-transparent border-none cursor-pointer font-sans', page === p && 'text-foreground bg-muted')}>
                {labels[p]}
              </button>
            )
          })}
          <div className="flex-1" />
          <span className="text-[11px] text-muted-foreground">{fmtNum(tables.length)} tables · {fmtCompact(totalRows)} rows</span>
          <ThemeToggle />
        </nav>
      )}

      {/* Mobile top bar */}
      {mobile && (
        <div className="flex items-center justify-center border-b border-border bg-card pt-[env(safe-area-inset-top)] min-h-[44px] shrink-0">
          <span className="font-bold text-[15px] text-foreground tracking-tight">NHC Admin</span>
        </div>
      )}

      {/* Content */}
      <div className={cn('flex-1 overflow-hidden min-h-0', mobile ? 'p-3 pt-3 pb-0' : 'p-5')}>

        {/* HOME */}
        {page === 'home' && (
          <Dashboard mobile={mobile} />
        )}

        {/* DATA PLAYGROUND — replaces old explorer + query */}
        {(page === 'playground' || page === 'explorer' || page === 'query') && (
          <React.Suspense fallback={<MobileLoadingFallback label="Loading playground" />}>
            <DataPlayground mobile={mobile} initialSql={page === 'query' ? querySql : undefined} />
          </React.Suspense>
        )}

        {/* NHL MODEL */}
        {page === 'nhlmodel' && (
          <React.Suspense fallback={<MobileLoadingFallback label="Loading model outputs" />}>
            <NHLModel mobile={mobile} />
          </React.Suspense>
        )}

        {/* BANKROLL */}
        {page === 'bankroll' && (
          <React.Suspense fallback={<MobileLoadingFallback label="Loading bankroll" />}>
            <BankrollTracker mobile={mobile} />
          </React.Suspense>
        )}

        {/* OWNERSHIP */}
        {page === 'ownership' && (
          <React.Suspense fallback={<MobileLoadingFallback label="Loading ownership" />}>
            <OwnershipTracker mobile={mobile} />
          </React.Suspense>
        )}

        {/* REAL ESTATE */}
        {page === 'realestate' && <RealEstatePage mobile={mobile} />}
      </div>

      {/* Bottom tab bar — mobile only */}
      {mobile && <BottomTabBar page={page} setPage={p => setPage(p)} />}
    </div>
  )
}
