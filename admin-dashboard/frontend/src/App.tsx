import React, { useEffect, useRef, useState } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'
import Dashboard from './Dashboard'

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

type Page = 'home' | 'explorer' | 'query' | 'realestate' | 'bankroll' | 'nhlmodel'
type SortDir = 'asc' | 'desc' | null
type ExplorerView = 'tree' | 'detail' | 'data'

/* ── Responsive hook ── */

function useIsMobile(breakpoint = 768) {
  const [mobile, setMobile] = useState(window.innerWidth < breakpoint)
  useEffect(() => {
    const handler = () => setMobile(window.innerWidth < breakpoint)
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [breakpoint])
  return mobile
}

/* ── Colors ── */

const C = {
  bg: '#0f1117', surface: '#181a20', surfaceHover: '#1e2028', surfaceActive: '#252830',
  border: '#2a2d37', borderLight: '#333642', text: '#e4e5e9', textSecondary: '#8b8f9a',
  textMuted: '#5f6370', accent: '#4f8cff', accentDim: '#3a6fd8', accentBg: 'rgba(79,140,255,0.08)',
  white: '#ffffff', danger: '#ef4444', dangerBg: 'rgba(239,68,68,0.1)', success: '#22c55e',
  purple: '#a855f7', purpleBg: 'rgba(168,85,247,0.08)',
}

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
  const bg = isNumericType(type) ? 'rgba(79,140,255,0.12)' : isDateType(type) ? 'rgba(168,85,247,0.12)' : 'rgba(255,255,255,0.06)'
  const color = isNumericType(type) ? '#7ab0ff' : isDateType(type) ? '#c084fc' : C.textSecondary
  return <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 500, whiteSpace: 'nowrap', background: bg, color }}>{type}</span>
}

/* ── Combo Box ── */

function ComboBox({ value, onChange, tableName, column, placeholder, inputType, style: outerStyle, mobile }: {
  value: string; onChange: (v: string) => void; tableName: string; column: string
  placeholder?: string; inputType?: string; style?: React.CSSProperties; mobile?: boolean
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
    <div ref={ref} style={{ position: 'relative', ...outerStyle }}>
      <input type={inputType || 'text'} value={value} placeholder={placeholder || 'Value'}
        onFocus={() => setOpen(true)} onChange={e => { onChange(e.target.value); setOpen(true) }}
        style={{ ...inputDark, width: '100%', boxSizing: 'border-box', height: mobile ? 44 : undefined }} />
      {open && (
        <div style={{ position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 2, zIndex: 30, background: C.surface, border: `1px solid ${C.border}`, borderRadius: 6, boxShadow: '0 6px 20px rgba(0,0,0,0.4)', maxHeight: mobile ? 260 : 200, overflowY: 'auto' }}>
          {loading && <div style={{ padding: '8px 12px', fontSize: 11, color: C.textMuted }}>Loading…</div>}
          {!loading && options.length === 0 && <div style={{ padding: '8px 12px', fontSize: 11, color: C.textMuted }}>No values</div>}
          {options.map((opt, i) => (
            <button key={i} onClick={() => { onChange(opt); setOpen(false) }}
              style={{ width: '100%', padding: mobile ? '12px 12px' : '7px 12px', minHeight: mobile ? 44 : undefined, background: 'transparent', border: 'none', borderBottom: i < options.length - 1 ? `1px solid ${C.border}` : 'none', cursor: 'pointer', fontSize: mobile ? 14 : 12, fontFamily: 'inherit', color: C.text, textAlign: 'left' }}
              onMouseEnter={e => (e.currentTarget.style.background = C.surfaceHover)}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>{opt}</button>
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: mobile ? 12 : 8 }}>
      {filters.map(f => {
        const dt = typeMap[f.column] || ''
        const ops = operatorsForType(dt)
        const isBetween = f.operator === 'between'
        const inputType = isNumericType(dt) ? 'number' : isDateType(dt) ? 'date' : 'text'
        return (
          <div key={f.id} style={{ display: 'flex', alignItems: mobile ? 'stretch' : 'center', gap: mobile ? 8 : 6, flexWrap: 'wrap', flexDirection: mobile ? 'column' : 'row' }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <select value={f.column} onChange={e => updateFilter(f.id, { column: e.target.value })} style={{ ...selectDark, flex: 1, height: mobile ? 44 : undefined, fontSize: mobile ? 14 : undefined }}>
                {columns.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
              <select value={f.operator} onChange={e => updateFilter(f.id, { operator: e.target.value })} style={{ ...selectDark, width: 110, height: mobile ? 44 : undefined, fontSize: mobile ? 14 : undefined }}>
                {ops.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
              <button onClick={() => removeFilter(f.id)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: mobile ? 22 : 18, color: C.textMuted, padding: '4px 6px', lineHeight: 1, minWidth: mobile ? 44 : undefined, minHeight: mobile ? 44 : undefined, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>×</button>
            </div>
            <ComboBox value={f.value} onChange={v => updateFilter(f.id, { value: v })} tableName={tableName} column={f.column} placeholder={isBetween ? 'Min' : 'Value'} inputType={inputType} mobile={mobile} style={{ width: mobile ? '100%' : isBetween ? 100 : 160 }} />
            {isBetween && (
              <>
                <span style={{ fontSize: 12, color: C.textMuted, textAlign: 'center' }}>to</span>
                <ComboBox value={f.value2 ?? ''} onChange={v => updateFilter(f.id, { value2: v })} tableName={tableName} column={f.column} placeholder="Max" inputType={inputType} mobile={mobile} style={{ width: mobile ? '100%' : 100 }} />
              </>
            )}
          </div>
        )
      })}
      <button onClick={addFilter} style={{ ...pillBtn, alignSelf: 'flex-start', minHeight: mobile ? 44 : undefined, fontSize: mobile ? 14 : 11, padding: mobile ? '10px 16px' : '5px 12px' }}>+ Add Filter</button>
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

  if (loading) return <div style={{ padding: 40, textAlign: 'center', color: C.textMuted }}>Loading…</div>
  if (!preview) return <div style={{ padding: 40, textAlign: 'center', color: C.textMuted }}>Failed to load</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, overflow: 'auto', height: '100%', paddingBottom: 24 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
        <div>
          <h2 style={{ fontSize: mobile ? 18 : 22, fontWeight: 700, margin: 0, color: C.white }}>{tableName}</h2>
          <div style={{ fontSize: 12, color: C.textMuted, marginTop: 4 }}>
            {preview.database} · {fmtNum(preview.row_count)} rows · {preview.column_count} columns
          </div>
        </div>
        <button onClick={onBrowse} style={{ ...pillBtn, background: C.accent, color: C.white, borderColor: C.accent, padding: '10px 20px', fontSize: 13, fontWeight: 600 }}>
          Browse Full Data
        </button>
      </div>

      {/* Schema */}
      <div style={{ ...cardDark }}>
        <div style={{ fontSize: 11, fontWeight: 600, color: C.textSecondary, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
          Schema ({preview.schema.length} columns)
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: mobile ? '1fr' : 'repeat(auto-fill, minmax(280px, 1fr))', gap: 4 }}>
          {preview.schema.map(c => (
            <div key={c.column_name} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 8px', borderRadius: 6, background: C.surfaceHover }}>
              <span style={{ fontFamily: 'monospace', fontSize: 12, color: C.text, flex: 1 }}>{c.column_name}</span>
              <TypeBadge type={c.data_type} />
              {c.is_nullable === 'YES' && <span style={{ fontSize: 9, color: C.textMuted }}>NULL</span>}
            </div>
          ))}
        </div>
      </div>

      {/* Sample Data */}
      {preview.sample_rows.length > 0 && (
        <div style={{ ...cardDark, padding: 0, overflow: 'hidden' }}>
          <div style={{ padding: '10px 14px', fontSize: 11, fontWeight: 600, color: C.textSecondary, textTransform: 'uppercase', letterSpacing: '0.05em', borderBottom: `1px solid ${C.border}` }}>
            Sample Data (first {preview.sample_rows.length} rows)
          </div>
          <div style={{ overflow: 'auto' }}>
            <table style={{ minWidth: preview.columns.length * 140, borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr>{preview.columns.map(c => <th key={c} style={thDark}>{c}</th>)}</tr>
              </thead>
              <tbody>
                {preview.sample_rows.map((row, i) => (
                  <tr key={i} style={{ borderBottom: `1px solid ${C.border}` }}>
                    {preview.columns.map(c => (
                      <td key={c} style={tdDark}>
                        {row[c] === null || row[c] === undefined
                          ? <span style={{ color: C.textMuted, fontStyle: 'italic' }}>null</span>
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
        <div style={{ ...cardDark }}>
          <div style={{ fontSize: 11, fontWeight: 600, color: C.textSecondary, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>
            Example Queries
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {examples.map((ex, i) => (
              <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '10px 12px', background: C.surfaceHover, borderRadius: 8, border: `1px solid ${C.border}` }}>
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: C.text, marginBottom: 4 }}>{ex.label}</div>
                  <pre style={{ margin: 0, fontSize: 11, fontFamily: 'monospace', color: C.textSecondary, whiteSpace: 'pre-wrap', wordBreak: 'break-all' }}>{ex.sql}</pre>
                </div>
                <button onClick={() => onRunQuery(ex.sql)} style={{ ...pillBtn, background: C.accentBg, color: C.accent, borderColor: C.accent + '40', padding: '8px 14px', flexShrink: 0, fontWeight: 600 }}>
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
    <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
      <div style={{ position: 'sticky', top: 0, zIndex: 5, background: C.bg, padding: '8px 0', display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8, flexShrink: 0 }}>
        <button onClick={() => setShowColPicker(!showColPicker)} style={{ ...pillBtn, minHeight: 44, fontSize: 13, padding: '8px 14px' }}>Columns ({displayCols.length}/{columns.length})</button>
      </div>
      {showColPicker && (
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12, marginBottom: 8, maxHeight: 200, overflowY: 'auto' }}>
          <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
            <button onClick={() => setVisibleCols(columns)} style={{ ...pillBtn, fontSize: 11 }}>All</button>
            <button onClick={() => setVisibleCols(columns.slice(0, 5))} style={{ ...pillBtn, fontSize: 11 }}>First 5</button>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {columns.map(col => {
              const active = displayCols.includes(col)
              return (
                <button key={col} onClick={() => setVisibleCols(prev => { const cur = prev.length > 0 ? prev : columns.slice(0, 5); return active ? cur.filter(c => c !== col) : [...cur, col] })}
                  style={{ ...pillBtn, fontSize: 12, minHeight: 44, padding: '8px 14px', background: active ? C.accentBg : C.surfaceActive, color: active ? C.accent : C.textSecondary, borderColor: active ? C.accent + '40' : C.borderLight }}>{col}</button>
              )
            })}
          </div>
        </div>
      )}
      <div ref={containerRef} style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
        {data.length === 0 && !loading && <div style={{ padding: 40, textAlign: 'center', color: C.textMuted }}>No data</div>}
        {data.map((row, i) => (
          <div key={i} style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14 }}>
            {displayCols.map(col => {
              const v = row[col]
              return (
                <div key={col} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0', borderBottom: `1px solid ${C.border}`, gap: 12, minHeight: 32 }}>
                  <span style={{ fontSize: 12, color: C.textMuted, fontWeight: 500, flexShrink: 0 }}>{col}</span>
                  <span style={{ fontSize: 13, color: v === null || v === undefined ? C.textMuted : C.text, textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontStyle: v === null || v === undefined ? 'italic' : 'normal' }}>
                    {v === null || v === undefined ? 'null' : String(v)}
                  </span>
                </div>
              )
            })}
          </div>
        ))}
        {loading && <div style={{ padding: 16, textAlign: 'center', color: C.accent, fontSize: 13 }}>Loading more…</div>}
        {!hasMore && data.length > 0 && <div style={{ padding: 12, textAlign: 'center', color: C.textMuted, fontSize: 12 }}>All rows loaded</div>}
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
        if (v === null || v === undefined) return <span style={{ color: C.textMuted, fontStyle: 'italic' }}>null</span>
        if (typeof v === 'boolean') return <span style={{ color: v ? C.success : C.danger }}>{String(v)}</span>
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
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: mobile ? 8 : 10 }}>
      {/* Back + toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', ...(mobile ? { position: 'sticky', top: 0, zIndex: 10, background: C.bg, paddingBottom: 4 } : {}) }}>
        <button onClick={onBack} style={{ ...pillBtn, display: 'flex', alignItems: 'center', gap: 4, height: mobile ? 44 : 36 }}>
          ← Back
        </button>
        <h3 style={{ margin: 0, fontSize: mobile ? 15 : 16, fontWeight: 700, color: C.white }}>{tableName}</h3>
        <div style={{ position: 'relative', flex: mobile ? '1 1 100%' : '0 0 220px', marginLeft: mobile ? 0 : 'auto' }}>
          <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: C.textMuted, fontSize: 14, pointerEvents: 'none' }}></span>
          <input type="text" value={quickSearch} onChange={e => setQuickSearch(e.target.value)} placeholder="Search loaded rows…"
            style={{ ...inputDark, width: '100%', paddingLeft: 32, height: mobile ? 44 : 36, fontSize: mobile ? 16 : 13, boxSizing: 'border-box' }} />
        </div>
        <button onClick={() => setShowFilters(!showFilters)}
          style={{ ...pillBtn, height: mobile ? 44 : 36, display: 'flex', alignItems: 'center', gap: 4, background: showFilters ? C.accentBg : C.surfaceActive, borderColor: showFilters ? C.accent + '40' : C.borderLight, color: showFilters ? C.accent : C.textSecondary }}>
          Filters{activeFilterCount > 0 && <span style={{ background: C.accent, color: C.white, borderRadius: 10, padding: '1px 6px', fontSize: 10, fontWeight: 700 }}>{activeFilterCount}</span>}
        </button>
        {!mobile && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 12, color: C.textMuted }}>Group:</span>
            <select value={groupBy ?? ''} onChange={e => setGroupBy(e.target.value || null)} style={selectDark}>
              <option value="">None</option>
              {columns.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
        )}
      </div>

      {showFilters && (
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12 }}>
          <FilterBar columns={columns} typeMap={typeMap} filters={filters} onChange={onFiltersChange} mobile={mobile} tableName={tableName} />
          {mobile && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 10 }}>
              <span style={{ fontSize: 12, color: C.textMuted }}>Group:</span>
              <select value={groupBy ?? ''} onChange={e => setGroupBy(e.target.value || null)} style={{ ...selectDark, flex: 1, height: 44, fontSize: 14 }}>
                <option value="">None</option>
                {columns.map(c => <option key={c} value={c}>{c}</option>)}
              </select>
            </div>
          )}
        </div>
      )}

      {/* Status */}
      <div style={{ fontSize: 12, color: C.textSecondary, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
        <span style={{ fontVariantNumeric: 'tabular-nums' }}>
          {filteredTotal < total ? <><strong style={{ color: C.text }}>{fmtNum(filteredTotal)}</strong> of {fmtNum(total)} rows</> : <><strong style={{ color: C.text }}>{fmtNum(total)}</strong> rows</>}
        </span>
        <span style={{ color: C.textMuted }}>·</span>
        <span>Showing {fmtNum(displayData.length)}</span>
        {loading && <span style={{ color: C.accent }}>● Loading…</span>}
      </div>

      {/* Group panels */}
      {groupBy && groupData.length > 0 && (
        <div style={{ maxHeight: 180, overflowY: 'auto', border: `1px solid ${C.border}`, borderRadius: 8, background: C.surface }}>
          {groupData.map((g, i) => (
            <button key={String(g.value ?? 'NULL')} onClick={() => filterByGroup(g.value)}
              style={{ width: '100%', padding: mobile ? '12px 14px' : '10px 14px', minHeight: mobile ? 44 : undefined, background: 'transparent', border: 'none', borderBottom: i < groupData.length - 1 ? `1px solid ${C.border}` : 'none', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', fontSize: 13, fontFamily: 'inherit', color: C.text }}>
              <span>{String(g.value ?? 'NULL')}</span>
              <span style={{ color: C.textMuted, fontVariantNumeric: 'tabular-nums' }}>{fmtNum(g.count)}</span>
            </button>
          ))}
        </div>
      )}

      {/* Data */}
      {mobile ? (
        <MobileCardList data={displayData} columns={columns} onLoadMore={loadMoreMobile} hasMore={hasMore} loading={loading} />
      ) : (
        <div ref={tableContainerRef} className="scroll-visible" style={{ flex: '1 1 0', overflow: 'auto', border: `1px solid ${C.border}`, borderRadius: 8, background: C.surface, minHeight: 0, marginBottom: 24 }}>
          <table style={{ minWidth: columns.length * 160, borderCollapse: 'collapse', fontSize: 12 }}>
            <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
              <tr>
                {table.getHeaderGroups()[0]?.headers.map(h => (
                  <th key={h.id} onClick={() => handleSort(h.column.id)} style={{ ...thDark, cursor: 'pointer', userSelect: 'none', width: h.column.getSize() }}>
                    <span>{flexRender(h.column.columnDef.header, h.getContext())}</span>
                    <span style={{ fontSize: 10, marginLeft: 4, color: sortBy === h.column.id ? C.accent : C.textMuted, opacity: sortBy === h.column.id ? 1 : 0.3 }}>
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
                  <tr key={row.id} style={{ height: 36, borderBottom: `1px solid ${C.border}` }}
                    onMouseEnter={e => (e.currentTarget.style.background = C.surfaceHover)}
                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                    {row.getVisibleCells().map(cell => (
                      <td key={cell.id} style={tdDark}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                    ))}
                  </tr>
                )
              })}
              {rowVirtualizer.getVirtualItems().length > 0 && (
                <tr><td style={{ height: (() => { const items = rowVirtualizer.getVirtualItems(); const last = items[items.length - 1]; return rowVirtualizer.getTotalSize() - (last?.end ?? 0) })(), padding: 0 }} colSpan={columns.length} /></tr>
              )}
            </tbody>
          </table>
          {displayData.length === 0 && !loading && <div style={{ padding: 40, textAlign: 'center', color: C.textMuted }}>No data</div>}
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
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 12, overflow: 'auto' }}>
      <div style={{ display: 'flex', gap: 8, flexDirection: mobile ? 'column' : 'row' }}>
        <textarea value={input} onChange={e => setInput(e.target.value)}
          onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) runSQL() }}
          placeholder="SELECT * FROM teams LIMIT 10"
          style={{ ...inputDark, flex: 1, fontFamily: 'monospace', resize: 'vertical', minHeight: 100, padding: 12 }} />
        <button onClick={runSQL} disabled={loading || !input.trim()}
          style={{ padding: mobile ? '12px 20px' : '10px 24px', minHeight: mobile ? 44 : undefined, background: C.accent, color: C.white, border: 'none', borderRadius: 8, cursor: loading ? 'wait' : 'pointer', fontSize: 14, fontWeight: 600, fontFamily: 'inherit', opacity: loading || !input.trim() ? 0.5 : 1, alignSelf: mobile ? 'stretch' : 'flex-start' }}>
          {loading ? '…' : 'Run SQL'}
        </button>
      </div>
      <div style={{ fontSize: 11, color: C.textMuted }}>⌘+Enter to run · Read-only queries only (SELECT, WITH)</div>
      {result && (result.error ? (
        <div style={{ padding: 14, background: C.dangerBg, border: `1px solid ${C.danger}30`, borderRadius: 8, color: C.danger, fontSize: 13 }}>{result.error}</div>
      ) : mobile ? (
        <MobileCardList data={result.rows} columns={result.columns} />
      ) : (
        <div className="scroll-visible" style={{ flex: 1, overflow: 'auto', border: `1px solid ${C.border}`, borderRadius: 8, minHeight: 0, background: C.surface }}>
          <table style={{ minWidth: result.columns.length * 160, borderCollapse: 'collapse', fontSize: 12 }}>
            <thead style={{ position: 'sticky', top: 0 }}>
              <tr>{result.columns.map(c => <th key={c} style={thDark}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {result.rows.map((r, i) => (
                <tr key={i} style={{ borderBottom: `1px solid ${C.border}` }}
                  onMouseEnter={e => (e.currentTarget.style.background = C.surfaceHover)}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                  {result!.columns.map(c => <td key={c} style={tdDark}>{String(r[c] ?? '')}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 12, color: C.textMuted, padding: '8px 12px', borderTop: `1px solid ${C.border}` }}>{result.rows.length} rows</div>
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
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 12 }}>
      <div style={{ display: 'flex', gap: 0, flexShrink: 0 }}>
        <button onClick={() => setSubView('listings')} style={{ ...modeBtn, borderRadius: '8px 0 0 8px', flex: mobile ? 1 : undefined, minHeight: mobile ? 44 : undefined, ...(subView === 'listings' ? modeBtnActive : {}) }}>Property Listings</button>
        <button onClick={() => setSubView('sales')} style={{ ...modeBtn, borderRadius: '0 8px 8px 0', flex: mobile ? 1 : undefined, minHeight: mobile ? 44 : undefined, ...(subView === 'sales' ? modeBtnActive : {}) }}>Sales Comps</button>
      </div>
      {subView === 'listings' && (
        <div style={{ flex: 1, borderRadius: 10, overflow: 'hidden', minHeight: 0 }}>
          <React.Suspense fallback={<div style={{ color: '#aaa', padding: 40 }}>Loading map...</div>}>
            <ForeclosureMap onOpenComps={(id) => { setSelectedForeclosureId(id); setSubView('sales') }} />
          </React.Suspense>
        </div>
      )}
      {subView === 'sales' && (
        <div style={{ flex: 1, overflow: 'auto', minHeight: 0 }}>
          <React.Suspense fallback={<div style={{ color: '#aaa', padding: 40 }}>Loading charts...</div>}>
            <SalesChart selectedForeclosureId={selectedForeclosureId} onSelectedForeclosure={(id) => setSelectedForeclosureId(id)} />
          </React.Suspense>
        </div>
      )}
    </div>
  )
}

/* ── Bottom Tab Bar (mobile) ── */

function BottomTabBar({ page, setPage }: { page: Page; setPage: (p: Page) => void }) {
  const tabs: { key: Page; icon: string; label: string }[] = [
    { key: 'home', icon: '', label: 'Home' },
    { key: 'nhlmodel', icon: '', label: 'Model' },
    { key: 'bankroll', icon: '', label: 'Bankroll' },
    { key: 'explorer', icon: '', label: 'Data' },
    { key: 'query', icon: '', label: 'Query' },
    { key: 'realestate', icon: '', label: 'Real Estate' },
  ]
  return (
    <nav style={{ display: 'flex', background: C.surface, borderTop: `1px solid ${C.border}`, paddingBottom: 'max(env(safe-area-inset-bottom), 8px)', flexShrink: 0, position: 'sticky', bottom: 0, zIndex: 20 }}>
      {tabs.map(t => (
        <button key={t.key} onClick={() => setPage(t.key)}
          style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: 2, padding: '10px 0 4px', minHeight: 52, background: 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit', color: page === t.key ? C.accent : C.textMuted, fontSize: 10, fontWeight: page === t.key ? 600 : 400, WebkitTapHighlightColor: 'transparent' }}>
          <span style={{ fontSize: 20 }}>{t.icon}</span><span>{t.label}</span>
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
    <div style={{ fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", sans-serif', color: C.text, height: '100vh', display: 'flex', flexDirection: 'column', background: C.bg, WebkitFontSmoothing: 'antialiased' }}>
      {/* Top Nav — desktop only */}
      {!mobile && (
        <nav style={{ background: C.surface, borderBottom: `1px solid ${C.border}`, padding: '0 24px', paddingTop: 'env(safe-area-inset-top)', display: 'flex', alignItems: 'center', minHeight: 52, flexShrink: 0, gap: 4 }}>
          <span style={{ fontWeight: 700, fontSize: 16, marginRight: 28, color: C.white, letterSpacing: '-0.02em', whiteSpace: 'nowrap' }}>
            NHC<span style={{ fontWeight: 400, color: C.textMuted }}> Admin</span>
          </span>
          {(['home', 'nhlmodel', 'bankroll', 'explorer', 'query', 'realestate'] as Page[]).map(p => {
            const labels: Record<Page, string> = { home: 'Home', nhlmodel: 'Model Outputs', bankroll: 'Bankroll', explorer: 'Data', query: 'Query', realestate: 'Real Estate' }
            return (
              <button key={p} onClick={() => { setPage(p); if (p === 'explorer') setExplorerView('tree') }}
                style={{ ...navBtnDark, padding: '8px 14px', fontSize: 13, ...(page === p ? { color: C.white, background: C.surfaceActive } : {}) }}>
                {labels[p]}
              </button>
            )
          })}
          <div style={{ flex: 1 }} />
          <span style={{ fontSize: 11, color: C.textMuted }}>{fmtNum(tables.length)} tables · {fmtCompact(totalRows)} rows</span>
        </nav>
      )}

      {/* Mobile top bar */}
      {mobile && (
        <div style={{ background: C.surface, borderBottom: `1px solid ${C.border}`, paddingTop: 'env(safe-area-inset-top)', display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: 44, flexShrink: 0 }}>
          <span style={{ fontWeight: 700, fontSize: 15, color: C.white, letterSpacing: '-0.02em' }}>NHC Admin</span>
        </div>
      )}

      {/* Content */}
      <div style={{ flex: 1, overflow: 'hidden', padding: mobile ? '12px 12px 0' : 20, minHeight: 0 }}>

        {/* HOME */}
        {page === 'home' && (
          <Dashboard mobile={mobile} />
        )}

        {/* DATA EXPLORER — Tree → Detail → Full Data */}
        {page === 'explorer' && (
          <div style={{ height: '100%', display: 'flex', flexDirection: 'column', minHeight: 0 }}>
            {explorerView === 'tree' && (
              <div style={{ overflow: 'auto', height: '100%' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 16 }}>
                  <h2 style={{ fontSize: mobile ? 18 : 20, fontWeight: 700, margin: 0, color: C.white }}>Data Explorer</h2>
                  <span style={{ fontSize: 12, color: C.textMuted }}>{fmtNum(tables.length)} tables · {fmtCompact(totalRows)} rows</span>
                </div>
                {/* Search */}
                <div style={{ position: 'relative', marginBottom: 16, maxWidth: 400 }}>
                  <span style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: C.textMuted, fontSize: 14, pointerEvents: 'none' }}></span>
                  <input type="text" value={sidebarSearch} onChange={e => setSidebarSearch(e.target.value)} placeholder="Search tables…"
                    style={{ ...inputDark, width: '100%', paddingLeft: 36, height: mobile ? 48 : 40, fontSize: mobile ? 16 : 14, boxSizing: 'border-box' }} />
                </div>
                {/* Groups */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {filteredGroups.map(g => {
                    const isExpanded = expandedGroups[g.label] ?? false
                    return (
                      <div key={g.label} style={{ ...cardDark, padding: 0, overflow: 'hidden' }}>
                        <button onClick={() => toggleGroup(g.label)}
                          style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', padding: mobile ? '16px 16px' : '14px 16px', background: 'transparent', border: 'none', cursor: 'pointer', fontFamily: 'inherit', fontSize: mobile ? 16 : 15, fontWeight: 600, color: C.white, textAlign: 'left' }}>
                          <span>{isExpanded ? '▾' : '▸'} {g.icon} {g.label}</span>
                          <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                            <span style={{ fontSize: 12, color: C.textMuted, fontWeight: 400 }}>{g.tables.length} tables</span>
                            <span style={{ fontSize: 12, color: C.accent, fontWeight: 500 }}>{fmtCompact(g.totalRows)} rows</span>
                          </span>
                        </button>
                        {isExpanded && (
                          <div style={{ borderTop: `1px solid ${C.border}` }}>
                            {/* Flat tables (no sub-groups) */}
                            {g.tables.sort((a, b) => b.row_count - a.row_count).map((t, i) => (
                              <button key={t.name} onClick={() => selectTable(t.name)}
                                style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', padding: mobile ? '14px 16px 14px 40px' : '11px 16px 11px 40px', minHeight: mobile ? 48 : undefined, background: 'transparent', border: 'none', cursor: 'pointer', fontFamily: 'inherit', fontSize: mobile ? 15 : 14, color: C.text, textAlign: 'left', borderBottom: i < g.tables.length - 1 ? `1px solid ${C.border}` : 'none' }}
                                onMouseEnter={e => (e.currentTarget.style.background = C.surfaceHover)}
                                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                                <span style={{ fontFamily: 'monospace', fontSize: mobile ? 14 : 13 }}>{t.name}</span>
                                <span style={{ fontSize: 12, color: C.textMuted, fontVariantNumeric: 'tabular-nums' }}>{fmtCompact(t.row_count)}</span>
                              </button>
                            ))}
                            {/* Sub-groups */}
                            {g.subGroups?.map(sg => {
                              const sgKey = `${g.label}::${sg.label}`
                              const sgExpanded = expandedGroups[sgKey] ?? false
                              return (
                                <div key={sg.label}>
                                  <button onClick={() => toggleGroup(sgKey)}
                                    style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', padding: mobile ? '14px 16px 14px 36px' : '11px 16px 11px 36px', background: C.surfaceHover, border: 'none', borderBottom: `1px solid ${C.border}`, cursor: 'pointer', fontFamily: 'inherit', fontSize: mobile ? 14 : 13, fontWeight: 600, color: C.textSecondary, textAlign: 'left' }}>
                                    <span>{sgExpanded ? '▾' : '▸'} {sg.label}</span>
                                    <span style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                      <span style={{ fontSize: 11, color: C.textMuted, fontWeight: 400 }}>{sg.tables.length} tables</span>
                                      <span style={{ fontSize: 11, color: C.accent, fontWeight: 500 }}>{fmtCompact(sg.totalRows)} rows</span>
                                    </span>
                                  </button>
                                  {sgExpanded && sg.tables.sort((a, b) => b.row_count - a.row_count).map((t, i) => (
                                    <button key={t.name} onClick={() => selectTable(t.name)}
                                      style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', width: '100%', padding: mobile ? '14px 16px 14px 56px' : '11px 16px 11px 56px', minHeight: mobile ? 48 : undefined, background: 'transparent', border: 'none', cursor: 'pointer', fontFamily: 'inherit', fontSize: mobile ? 15 : 14, color: C.text, textAlign: 'left', borderBottom: i < sg.tables.length - 1 ? `1px solid ${C.border}` : 'none' }}
                                      onMouseEnter={e => (e.currentTarget.style.background = C.surfaceHover)}
                                      onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                                      <span style={{ fontFamily: 'monospace', fontSize: mobile ? 14 : 13 }}>{t.name}</span>
                                      <span style={{ fontSize: 12, color: C.textMuted, fontVariantNumeric: 'tabular-nums' }}>{fmtCompact(t.row_count)}</span>
                                    </button>
                                  ))}
                                </div>
                              )
                            })}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {explorerView === 'detail' && selectedTable && (
              <div style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
                <button onClick={() => setExplorerView('tree')} style={{ ...pillBtn, alignSelf: 'flex-start', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 4, height: mobile ? 44 : 36 }}>← All Tables</button>
                <div style={{ flex: 1, minHeight: 0 }}>
                  <TableDetailPanel tableName={selectedTable} mobile={mobile}
                    onBrowse={() => setExplorerView('data')}
                    onRunQuery={handleRunQuery} />
                </div>
              </div>
            )}

            {explorerView === 'data' && selectedTable && (
              <DataTable tableName={selectedTable} mobile={mobile} onBack={() => setExplorerView('detail')} />
            )}
          </div>
        )}

        {/* QUERY */}
        {page === 'query' && <QueryPage mobile={mobile} initialSql={querySql} />}

        {/* NHL MODEL */}
        {page === 'nhlmodel' && (
          <React.Suspense fallback={<div style={{ color: '#aaa', padding: 40 }}>Loading model outputs...</div>}>
            <NHLModel mobile={mobile} />
          </React.Suspense>
        )}

        {/* BANKROLL */}
        {page === 'bankroll' && (
          <React.Suspense fallback={<div style={{ color: '#aaa', padding: 40 }}>Loading bankroll...</div>}>
            <BankrollTracker mobile={mobile} />
          </React.Suspense>
        )}

        {/* REAL ESTATE */}
        {page === 'realestate' && <RealEstatePage mobile={mobile} />}
      </div>

      {/* Bottom tab bar — mobile only */}
      {mobile && <BottomTabBar page={page} setPage={p => { setPage(p); if (p === 'explorer') setExplorerView('tree') }} />}
    </div>
  )
}

/* ── Small components ── */

/* ── Styles ── */

const cardDark: React.CSSProperties = { background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14 }
const navBtnDark: React.CSSProperties = { background: 'none', border: 'none', padding: '8px 14px', cursor: 'pointer', fontSize: 13, color: C.textSecondary, fontFamily: 'inherit', borderRadius: 6, fontWeight: 500 }
const pillBtn: React.CSSProperties = { padding: '5px 12px', background: C.surfaceActive, border: `1px solid ${C.borderLight}`, borderRadius: 6, cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', color: C.textSecondary, fontWeight: 500 }
const selectDark: React.CSSProperties = { fontSize: 13, padding: '6px 10px', border: `1px solid ${C.borderLight}`, borderRadius: 6, fontFamily: 'inherit', background: C.surfaceActive, color: C.text, outline: 'none' }
const inputDark: React.CSSProperties = { fontSize: 13, padding: '6px 10px', border: `1px solid ${C.borderLight}`, borderRadius: 6, fontFamily: 'inherit', boxSizing: 'border-box' as const, background: C.surfaceActive, color: C.text, outline: 'none' }
const modeBtn: React.CSSProperties = { padding: '10px 20px', border: `1px solid ${C.borderLight}`, background: C.surface, cursor: 'pointer', fontSize: 13, fontFamily: 'inherit', color: C.textSecondary, fontWeight: 500 }
const modeBtnActive: React.CSSProperties = { background: C.accent, color: C.white, borderColor: C.accent }
const thDark: React.CSSProperties = { padding: '8px 12px', textAlign: 'left', borderBottom: `2px solid ${C.border}`, fontSize: 11, fontWeight: 600, color: C.textSecondary, background: C.surface, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', textTransform: 'uppercase', letterSpacing: '0.04em' }
const tdDark: React.CSSProperties = { padding: '6px 12px', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontSize: 12, color: C.text }
