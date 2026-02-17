import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'

const API = '/api'

/* ── Types ── */

interface TableInfo { name: string; row_count: number }
interface SchemaColumn { column_name: string; data_type: string; is_nullable: string }
interface SessionInfo {
  key: string; label: string; total_tokens: number; input_tokens: number
  output_tokens: number; context_window: number; model: string; updated_at: string | null
  age_hours?: number | null; share_pct?: number; burn_rate_24h_est?: number
}
interface UsageData {
  sessions: SessionInfo[]
  totals: { total_tokens: number; input_tokens: number; output_tokens: number; session_count: number }
  models: Array<{
    model: string
    total_tokens: number
    input_tokens: number
    output_tokens: number
    session_count: number
    top_sessions: Array<{ key: string; label: string; total_tokens: number; updated_at: string | null; share_within_model_pct: number }>
  }>
  claude_rate_limit: {
    status: 'active' | 'limited' | 'unknown'
    reset_at: string | null
    seconds_until_reset: number | null
    reason: string | null
    source: string
  }
  windows: Record<string, { hours: number; session_count: number; total_tokens: number; input_tokens: number; output_tokens: number; burn_rate_tokens_per_hour: number }>
  top_consumers: Array<{ key: string; label: string; total_tokens: number; share_pct: number; updated_at: string | null; burn_rate_24h_est: number }>
  trend: { window_hours: number; bucket_minutes: number; buckets: Array<{ start: string | null; end: string | null; session_count: number; total_tokens: number }> }
  freshness: { generated_at: string; latest_session_update_at: string | null; staleness_seconds: number | null }
}
interface GroupRow { value: unknown; count: number }
interface ActiveFilter { id: string; column: string; operator: string; value: string; value2?: string }

import ForeclosureMap from './ForeclosureMap'

type Page = 'home' | 'explorer' | 'query' | 'map'
type SortDir = 'asc' | 'desc' | null

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
  bg: '#0f1117',
  surface: '#181a20',
  surfaceHover: '#1e2028',
  surfaceActive: '#252830',
  border: '#2a2d37',
  borderLight: '#333642',
  text: '#e4e5e9',
  textSecondary: '#8b8f9a',
  textMuted: '#5f6370',
  accent: '#4f8cff',
  accentDim: '#3a6fd8',
  accentBg: 'rgba(79,140,255,0.08)',
  white: '#ffffff',
  danger: '#ef4444',
  dangerBg: 'rgba(239,68,68,0.1)',
  success: '#22c55e',
}

/* ── Table → Project grouping ── */

const PROJECT_GROUPS: { label: string; icon: string; match: (name: string) => boolean }[] = [
  { label: 'NHL Betting', icon: '🏒', match: (n) => ['games','game_team_stats','player_stats','players','teams','standings','schedules','injuries','injuries_live','lineup_absences','period_scores','goalie_advanced','goalie_saves_by_strength','goalie_starts','goalie_stats','saves_odds','sog_odds','predictions','model_runs','theses','live_game_snapshots','positions'].includes(n) },
  { label: 'Polymarket', icon: '📊', match: (n) => ['markets','market_snapshots'].includes(n) },
  { label: 'Real Estate', icon: '🏠', match: (n) => n.startsWith('cook_county_') || n.startsWith('ct_') || n === 'sf_rentals' || ['commercial_valuations','parcel_sales','parcel_universe','data_refresh_log'].includes(n) },
  { label: 'Crypto', icon: '₿', match: (n) => n.startsWith('crypto_') },
  { label: 'Dashboard', icon: '⚙️', match: (n) => ['kanban_events','kanban_tasks','agent_log','api_snapshots','human_notes'].includes(n) },
]

function groupTables(tables: TableInfo[]): { label: string; icon: string; tables: TableInfo[]; totalRows: number }[] {
  const groups = PROJECT_GROUPS.map(g => ({ label: g.label, icon: g.icon, tables: [] as TableInfo[], totalRows: 0 }))
  const other: TableInfo[] = []
  for (const t of tables) {
    const g = PROJECT_GROUPS.findIndex(g => g.match(t.name))
    if (g >= 0) groups[g].tables.push(t)
    else other.push(t)
  }
  if (other.length > 0) groups.push({ label: 'Other', icon: '📁', tables: other, totalRows: 0 })
  return groups.filter(g => g.tables.length > 0).map(g => ({ ...g, totalRows: g.tables.reduce((s, t) => s + t.row_count, 0) }))
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
function fmtAge(seconds: number | null | undefined): string {
  if (seconds == null) return '—'
  if (seconds < 60) return `${seconds}s ago`
  const mins = Math.floor(seconds / 60)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 48) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}
function fmtCountdown(seconds: number): string {
  const safe = Math.max(seconds, 0)
  const days = Math.floor(safe / 86400)
  const hours = Math.floor((safe % 86400) / 3600)
  const mins = Math.floor((safe % 3600) / 60)
  const secs = safe % 60
  if (days > 0) return `${days}d ${hours}h ${mins}m`
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

let filterId = 0
function nextFilterId() { return `f${++filterId}` }

/* ── Combo Box (dropdown + free text) ── */

function ComboBox({ value, onChange, tableName, column, placeholder, inputType, style: outerStyle }: {
  value: string; onChange: (v: string) => void; tableName: string; column: string
  placeholder?: string; inputType?: string; style?: React.CSSProperties
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
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  return (
    <div ref={ref} style={{ position: 'relative', ...outerStyle }}>
      <input type={inputType || 'text'} value={value} placeholder={placeholder || 'Value'}
        onFocus={() => setOpen(true)}
        onChange={e => { onChange(e.target.value); setOpen(true) }}
        style={{ ...inputDark, width: '100%', boxSizing: 'border-box' }} />
      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 2, zIndex: 30,
          background: C.surface, border: `1px solid ${C.border}`, borderRadius: 6,
          boxShadow: '0 6px 20px rgba(0,0,0,0.4)', maxHeight: 200, overflowY: 'auto',
        }}>
          {loading && <div style={{ padding: '8px 12px', fontSize: 11, color: C.textMuted }}>Loading…</div>}
          {!loading && options.length === 0 && <div style={{ padding: '8px 12px', fontSize: 11, color: C.textMuted }}>No values</div>}
          {options.map((opt, i) => (
            <button key={i} onClick={() => { onChange(opt); setOpen(false) }}
              style={{
                width: '100%', padding: '7px 12px', background: 'transparent', border: 'none',
                borderBottom: i < options.length - 1 ? `1px solid ${C.border}` : 'none',
                cursor: 'pointer', fontSize: 12, fontFamily: 'inherit', color: C.text, textAlign: 'left',
              }}
              onMouseEnter={e => (e.currentTarget.style.background = C.surfaceHover)}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {filters.map(f => {
        const dt = typeMap[f.column] || ''
        const ops = operatorsForType(dt)
        const isBetween = f.operator === 'between'
        const inputType = isNumericType(dt) ? 'number' : isDateType(dt) ? 'date' : 'text'
        return (
          <div key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <select value={f.column} onChange={e => updateFilter(f.id, { column: e.target.value })}
              style={{ ...selectDark, flex: mobile ? '1 1 40%' : undefined, minWidth: mobile ? 0 : undefined }}>
              {columns.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={f.operator} onChange={e => updateFilter(f.id, { operator: e.target.value })}
              style={{ ...selectDark, width: mobile ? 90 : 110 }}>
              {ops.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <ComboBox value={f.value} onChange={v => updateFilter(f.id, { value: v })}
              tableName={tableName} column={f.column} placeholder={isBetween ? 'Min' : 'Value'}
              inputType={inputType}
              style={{ flex: mobile ? '1 1 100%' : undefined, width: mobile ? 'auto' : isBetween ? 100 : 160 }} />
            {isBetween && (
              <>
                <span style={{ fontSize: 12, color: C.textMuted }}>to</span>
                <ComboBox value={f.value2 ?? ''} onChange={v => updateFilter(f.id, { value2: v })}
                  tableName={tableName} column={f.column} placeholder="Max"
                  inputType={inputType}
                  style={{ width: mobile ? '100%' : 100, flex: mobile ? '1 1 100%' : undefined }} />
              </>
            )}
            <button onClick={() => removeFilter(f.id)}
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 18, color: C.textMuted, padding: '4px 6px', lineHeight: 1 }}>×</button>
          </div>
        )
      })}
      <button onClick={addFilter} style={{ ...pillBtn, alignSelf: 'flex-start' }}>+ Add Filter</button>
    </div>
  )
}

/* ── Schema Panel ── */

function SchemaToggle({ tableName }: { tableName: string }) {
  const [open, setOpen] = useState(false)
  const [schema, setSchema] = useState<SchemaColumn[]>([])
  useEffect(() => { setOpen(false); setSchema([]) }, [tableName])
  useEffect(() => {
    if (open && schema.length === 0)
      fetch(`${API}/tables/${tableName}/schema`).then(r => r.json()).then(d => setSchema(d.columns))
  }, [open, tableName])

  return (
    <div style={{ position: 'relative' }}>
      <button onClick={() => setOpen(!open)}
        style={{ ...pillBtn, background: open ? C.accent : C.surfaceActive, color: open ? C.white : C.textSecondary, borderColor: open ? C.accent : C.borderLight }}>
        {open ? '▾' : '▸'} Schema
      </button>
      {open && schema.length > 0 && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, marginTop: 6, zIndex: 20,
          background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8,
          boxShadow: '0 8px 24px rgba(0,0,0,0.4)', minWidth: 300, maxWidth: '90vw',
          maxHeight: 400, overflowY: 'auto',
        }}>
          <div style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}`, fontSize: 11, fontWeight: 600, color: C.textSecondary, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {schema.length} columns
          </div>
          {schema.map((c, i) => (
            <div key={c.column_name} style={{
              display: 'flex', alignItems: 'center', gap: 10, padding: '8px 14px',
              borderBottom: i < schema.length - 1 ? `1px solid ${C.border}` : 'none', fontSize: 12,
            }}>
              <span style={{ fontFamily: 'monospace', color: C.text, flex: 1, fontSize: 11 }}>{c.column_name}</span>
              <span style={{
                padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 500, whiteSpace: 'nowrap',
                background: isNumericType(c.data_type) ? 'rgba(79,140,255,0.12)' : isDateType(c.data_type) ? 'rgba(168,85,247,0.12)' : 'rgba(255,255,255,0.06)',
                color: isNumericType(c.data_type) ? '#7ab0ff' : isDateType(c.data_type) ? '#c084fc' : C.textSecondary,
              }}>{c.data_type}</span>
              {c.is_nullable === 'YES' && <span style={{ fontSize: 10, color: C.textMuted }}>null</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Mobile Card View for rows ── */

function MobileCardList({ data, columns }: { data: Record<string, unknown>[]; columns: string[] }) {
  const containerRef = useRef<HTMLDivElement>(null)
  return (
    <div ref={containerRef} style={{ flex: 1, overflow: 'auto', display: 'flex', flexDirection: 'column', gap: 8 }}>
      {data.length === 0 && <div style={{ padding: 40, textAlign: 'center', color: C.textMuted }}>No data</div>}
      {data.slice(0, 200).map((row, i) => (
        <div key={i} style={{
          background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14,
        }}>
          {columns.map(col => {
            const v = row[col]
            return (
              <div key={col} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: `1px solid ${C.border}`, gap: 12 }}>
                <span style={{ fontSize: 11, color: C.textMuted, fontWeight: 500, flexShrink: 0 }}>{col}</span>
                <span style={{ fontSize: 12, color: v === null || v === undefined ? C.textMuted : C.text, textAlign: 'right', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontStyle: v === null || v === undefined ? 'italic' : 'normal' }}>
                  {v === null || v === undefined ? 'null' : String(v)}
                </span>
              </div>
            )
          })}
        </div>
      ))}
      {data.length > 200 && <div style={{ padding: 12, textAlign: 'center', color: C.textMuted, fontSize: 12 }}>Showing first 200 of {fmtNum(data.length)}</div>}
    </div>
  )
}

/* ── Virtualized Data Table ── */

function DataTable({ tableName, mobile }: { tableName: string; mobile: boolean }) {
  const [allData, setAllData] = useState<Record<string, unknown>[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [schema, setSchema] = useState<SchemaColumn[]>([])
  const [total, setTotal] = useState(0)
  const [filteredTotal, setFilteredTotal] = useState(0)
  const [sortBy, setSortBy] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>(null)
  const [filters, setFilters] = useState<ActiveFilter[]>([])
  const [groupBy, setGroupBy] = useState<string | null>(null)
  const [groupData, setGroupData] = useState<GroupRow[]>([])
  const [loading, setLoading] = useState(false)
  const [hasMore, setHasMore] = useState(true)
  const [quickSearch, setQuickSearch] = useState('')
  const [showFilters, setShowFilters] = useState(false)
  const BATCH = 200
  const tableContainerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const fetchingRef = useRef(false)

  useEffect(() => { fetch(`${API}/tables/${tableName}/schema`).then(r => r.json()).then(d => setSchema(d.columns)) }, [tableName])
  const typeMap = useMemo(() => { const m: Record<string, string> = {}; for (const c of schema) m[c.column_name] = c.data_type; return m }, [schema])

  useEffect(() => {
    setAllData([]); setSortBy(null); setSortDir(null); setFilters([])
    setGroupBy(null); setGroupData([]); setHasMore(true); setQuickSearch(''); setShowFilters(false)
  }, [tableName])

  const buildFilterParam = useCallback(() => {
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
  }, [filters, typeMap])

  const buildUrl = useCallback((offset: number) => {
    const params = new URLSearchParams({ limit: String(BATCH), offset: String(offset) })
    if (sortBy && sortDir) { params.set('sort_by', sortBy); params.set('sort_dir', sortDir) }
    const fp = buildFilterParam()
    if (fp) params.set('filters', fp)
    return `${API}/tables/${tableName}/data?${params}`
  }, [tableName, sortBy, sortDir, buildFilterParam])

  const fetchBatch = useCallback(async (offset: number, append: boolean) => {
    if (fetchingRef.current) return
    fetchingRef.current = true; setLoading(true)
    try {
      const r = await fetch(buildUrl(offset)); const d = await r.json()
      if (append) setAllData(prev => [...prev, ...d.rows])
      else { setAllData(d.rows); setColumns(d.columns) }
      setTotal(d.total); setFilteredTotal(d.filtered_total)
      setHasMore(offset + d.rows.length < d.filtered_total)
    } finally { fetchingRef.current = false; setLoading(false) }
  }, [buildUrl])

  useEffect(() => { setAllData([]); setHasMore(true); fetchBatch(0, false) }, [sortBy, sortDir, tableName, buildFilterParam])
  const onFiltersChange = useCallback((nf: ActiveFilter[]) => setFilters(nf), [])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => { setAllData([]); setHasMore(true); fetchBatch(0, false) }, 400)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [filters])

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

  const displayData = useMemo(() => {
    if (!quickSearch.trim()) return allData
    const q = quickSearch.toLowerCase()
    return allData.filter(row => Object.values(row).some(v => v != null && String(v).toLowerCase().includes(q)))
  }, [allData, quickSearch])

  const colDefs: ColumnDef<Record<string, unknown>, unknown>[] = useMemo(
    () => columns.map(c => ({
      accessorKey: c, header: c, size: 160,
      cell: (info: { getValue: () => unknown }) => {
        const v = info.getValue()
        if (v === null || v === undefined) return <span style={{ color: C.textMuted, fontStyle: 'italic' }}>null</span>
        if (typeof v === 'boolean') return <span style={{ color: v ? C.success : C.danger }}>{String(v)}</span>
        return String(v)
      },
    })), [columns])

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
      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <div style={{ position: 'relative', flex: mobile ? '1 1 100%' : '0 0 260px' }}>
          <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: C.textMuted, fontSize: 14, pointerEvents: 'none' }}>🔍</span>
          <input type="text" value={quickSearch} onChange={e => setQuickSearch(e.target.value)}
            placeholder="Search loaded rows…"
            style={{ ...inputDark, width: '100%', paddingLeft: 32, height: 36, boxSizing: 'border-box' }} />
        </div>
        <button onClick={() => setShowFilters(!showFilters)}
          style={{ ...pillBtn, height: 36, display: 'flex', alignItems: 'center', gap: 4, background: showFilters ? C.accentBg : C.surfaceActive, borderColor: showFilters ? C.accent + '40' : C.borderLight, color: showFilters ? C.accent : C.textSecondary }}>
          ⚙ Filters{activeFilterCount > 0 && <span style={{ background: C.accent, color: C.white, borderRadius: 10, padding: '1px 6px', fontSize: 10, fontWeight: 700 }}>{activeFilterCount}</span>}
        </button>
        {!mobile && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginLeft: 'auto' }}>
            <span style={{ fontSize: 12, color: C.textMuted }}>Group:</span>
            <select value={groupBy ?? ''} onChange={e => setGroupBy(e.target.value || null)} style={selectDark}>
              <option value="">None</option>
              {columns.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
          </div>
        )}
      </div>

      {/* Expandable filter panel */}
      {showFilters && (
        <div style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8, padding: 12 }}>
          <FilterBar columns={columns} typeMap={typeMap} filters={filters} onChange={onFiltersChange} mobile={mobile} tableName={tableName} />
          {mobile && (
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 10 }}>
              <span style={{ fontSize: 12, color: C.textMuted }}>Group:</span>
              <select value={groupBy ?? ''} onChange={e => setGroupBy(e.target.value || null)} style={{ ...selectDark, flex: 1 }}>
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
          {filteredTotal < total
            ? <><strong style={{ color: C.text }}>{fmtNum(filteredTotal)}</strong> of {fmtNum(total)} rows</>
            : <><strong style={{ color: C.text }}>{fmtNum(total)}</strong> rows</>}
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
              style={{ width: '100%', padding: '10px 14px', background: 'transparent', border: 'none', borderBottom: i < groupData.length - 1 ? `1px solid ${C.border}` : 'none', cursor: 'pointer', display: 'flex', justifyContent: 'space-between', fontSize: 13, fontFamily: 'inherit', color: C.text }}>
              <span>{String(g.value ?? 'NULL')}</span>
              <span style={{ color: C.textMuted, fontVariantNumeric: 'tabular-nums' }}>{fmtNum(g.count)}</span>
            </button>
          ))}
        </div>
      )}

      {/* Data: cards on mobile, table on desktop */}
      {mobile ? (
        <MobileCardList data={displayData} columns={columns} />
      ) : (
        <div ref={tableContainerRef} className="scroll-visible" style={{ flex: '1 1 0', overflow: 'auto', border: `1px solid ${C.border}`, borderRadius: 8, background: C.surface, minHeight: 0, marginBottom: 24 }}>
          <table style={{ minWidth: columns.length * 160, borderCollapse: 'collapse', fontSize: 12 }}>
            <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
              <tr>
                {table.getHeaderGroups()[0]?.headers.map(h => (
                  <th key={h.id} onClick={() => handleSort(h.column.id)}
                    style={{ ...thDark, cursor: 'pointer', userSelect: 'none', width: h.column.getSize() }}>
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

/* ── Query Page ── */

function QueryPage({ mobile }: { mobile: boolean }) {
  const [mode, setMode] = useState<'ask' | 'sql'>('ask')
  const [input, setInput] = useState('')
  const [generatedSql, setGeneratedSql] = useState<string | null>(null)
  const [summary, setSummary] = useState<string | null>(null)
  const [result, setResult] = useState<{ columns: string[]; rows: Record<string, unknown>[]; error?: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const [showSql, setShowSql] = useState(false)

  function runNL() {
    if (!input.trim()) return
    setLoading(true); setResult(null); setGeneratedSql(null); setSummary(null)
    fetch(`${API}/nl-query`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question: input }) })
      .then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.detail); return d })
      .then(d => { setGeneratedSql(d.sql); setSummary(d.summary || null); setResult({ columns: d.columns, rows: d.rows }) })
      .catch(e => setResult({ columns: [], rows: [], error: e.message }))
      .finally(() => setLoading(false))
  }
  function runSQL() {
    if (!input.trim()) return
    setLoading(true); setResult(null); setGeneratedSql(null)
    fetch(`${API}/query`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sql: input }) })
      .then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.detail); return d })
      .then(d => setResult({ columns: d.columns, rows: d.rows }))
      .catch(e => setResult({ columns: [], rows: [], error: e.message }))
      .finally(() => setLoading(false))
  }
  function handleSubmit() { mode === 'ask' ? runNL() : runSQL() }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 12, overflow: 'auto' }}>
      <div style={{ display: 'flex', gap: 0 }}>
        <button onClick={() => { setMode('ask'); setInput(''); setResult(null) }}
          style={{ ...modeBtn, borderRadius: '8px 0 0 8px', flex: mobile ? 1 : undefined, ...(mode === 'ask' ? modeBtnActive : {}) }}>Ask in English</button>
        <button onClick={() => { setMode('sql'); setInput(''); setResult(null) }}
          style={{ ...modeBtn, borderRadius: '0 8px 8px 0', flex: mobile ? 1 : undefined, ...(mode === 'sql' ? modeBtnActive : {}) }}>Raw SQL</button>
      </div>
      <div style={{ display: 'flex', gap: 8, flexDirection: mobile && mode === 'sql' ? 'column' : 'row' }}>
        {mode === 'sql' ? (
          <textarea value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit() }}
            placeholder="SELECT * FROM teams LIMIT 10"
            style={{ ...inputDark, flex: 1, fontFamily: 'monospace', resize: 'vertical', minHeight: 100, padding: 12 }} />
        ) : (
          <input type="text" value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleSubmit() }}
            placeholder="e.g. Show me all goalies with more than 30 saves"
            style={{ ...inputDark, flex: 1, padding: '10px 14px', fontSize: 14, height: 44 }} />
        )}
        <button onClick={handleSubmit} disabled={loading || !input.trim()}
          style={{ padding: mobile ? '12px 20px' : '10px 24px', background: C.accent, color: C.white, border: 'none', borderRadius: 8, cursor: loading ? 'wait' : 'pointer', fontSize: 14, fontWeight: 600, fontFamily: 'inherit', opacity: loading || !input.trim() ? 0.5 : 1 }}>
          {loading ? '…' : 'Run'}
        </button>
      </div>
      {summary && <div style={{ padding: '12px 16px', background: C.accentBg, border: `1px solid ${C.accentDim}30`, borderRadius: 8, fontSize: 13, color: C.accent }}>{summary}</div>}
      {generatedSql && (
        <div>
          <button onClick={() => setShowSql(!showSql)} style={{ ...pillBtn, fontSize: 12 }}>{showSql ? '▾' : '▸'} Generated SQL</button>
          {showSql && <pre style={{ margin: '8px 0 0', padding: 12, background: C.surfaceActive, borderRadius: 8, fontSize: 12, overflow: 'auto', fontFamily: 'monospace', color: C.text, border: `1px solid ${C.border}` }}>{generatedSql}</pre>}
        </div>
      )}
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

/* ── Mobile Sidebar Drawer ── */

function SidebarDrawer({ open, onClose, children }: { open: boolean; onClose: () => void; children: React.ReactNode }) {
  if (!open) return null
  return (
    <div style={{ position: 'fixed', inset: 0, zIndex: 100, display: 'flex' }}>
      <div onClick={onClose} style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.6)' }} />
      <div style={{ position: 'relative', width: 280, maxWidth: '80vw', background: C.surface, height: '100%', overflowY: 'auto', borderRight: `1px solid ${C.border}`, boxShadow: '4px 0 20px rgba(0,0,0,0.3)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '14px 16px', borderBottom: `1px solid ${C.border}` }}>
          <span style={{ fontWeight: 700, color: C.white, fontSize: 15 }}>Tables</span>
          <button onClick={onClose} style={{ background: 'none', border: 'none', color: C.textSecondary, fontSize: 20, cursor: 'pointer', padding: 4 }}>×</button>
        </div>
        {children}
      </div>
    </div>
  )
}

/* ── Main App ── */

export default function App() {
  const mobile = useIsMobile()
  const [page, setPage] = useState<Page>('home')
  const [tables, setTables] = useState<TableInfo[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [usage, setUsage] = useState<UsageData | null>(null)
  const [usageLoadFailed, setUsageLoadFailed] = useState(false)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [sidebarSearch, setSidebarSearch] = useState('')
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [nowMs, setNowMs] = useState(Date.now())

  const grouped = useMemo(() => groupTables(tables), [tables])
  const filteredGroups = useMemo(() => {
    if (!sidebarSearch.trim()) return grouped
    const q = sidebarSearch.toLowerCase()
    return grouped.map(g => ({ ...g, tables: g.tables.filter(t => t.name.toLowerCase().includes(q)) })).filter(g => g.tables.length > 0)
  }, [grouped, sidebarSearch])

  function toggleGroup(label: string) { setCollapsed(prev => ({ ...prev, [label]: !prev[label] })) }
  function selectTable(name: string) { setSelected(name); setDrawerOpen(false) }

  useEffect(() => {
    fetch(`${API}/tables`)
      .then(r => (r.ok ? r.json() : []))
      .then(data => setTables(Array.isArray(data) ? data : []))
      .catch(() => setTables([]))
  }, [])

  useEffect(() => {
    const t = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(t)
  }, [])

  useEffect(() => {
    fetch(`${API}/usage`)
      .then(r => (r.ok ? r.json() : null))
      .then(data => {
        if (data && data.freshness && data.totals) {
          setUsage(data as UsageData)
          setUsageLoadFailed(false)
        } else {
          setUsage(null)
          setUsageLoadFailed(true)
        }
      })
      .catch(() => {
        setUsage(null)
        setUsageLoadFailed(true)
      })
  }, [])

  const totalRows = useMemo(() => tables.reduce((s, t) => s + t.row_count, 0), [tables])

  /* Shared sidebar content */
  const sidebarContent = (
    <div style={{ padding: mobile ? '8px 10px' : '4px 6px 10px', display: 'flex', flexDirection: 'column', gap: 2 }}>
      <input type="text" value={sidebarSearch} onChange={e => setSidebarSearch(e.target.value)}
        placeholder="Search tables…"
        style={{ ...inputDark, width: '100%', height: 34, fontSize: 13, boxSizing: 'border-box', padding: '0 12px', marginBottom: 6 }} />
      {filteredGroups.map(g => {
        const isCollapsed = collapsed[g.label] ?? false
        return (
          <div key={g.label}>
            <button onClick={() => toggleGroup(g.label)}
              style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%', padding: '9px 10px', background: 'transparent', border: 'none', cursor: 'pointer', borderRadius: 6, fontSize: 13, fontFamily: 'inherit', fontWeight: 600, textAlign: 'left', color: C.text }}>
              <span>{isCollapsed ? '▸' : '▾'} {g.icon} {g.label}</span>
              <span style={{ fontSize: 10, color: C.textMuted, fontWeight: 400 }}>{fmtCompact(g.totalRows)}</span>
            </button>
            {!isCollapsed && g.tables.map(t => (
              <button key={t.name} onClick={() => selectTable(t.name)}
                style={{
                  display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%',
                  padding: '8px 10px 8px 30px', background: 'transparent', border: 'none', cursor: 'pointer',
                  borderRadius: 6, fontSize: 13, fontFamily: 'inherit', textAlign: 'left', color: C.textSecondary,
                  ...(selected === t.name ? { background: C.accentBg, color: C.accent, fontWeight: 600 } : {}),
                }}>
                <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.name}</span>
                <span style={{ fontSize: 10, color: C.textMuted, flexShrink: 0, marginLeft: 8 }}>{fmtCompact(t.row_count)}</span>
              </button>
            ))}
          </div>
        )
      })}
    </div>
  )

  return (
    <div style={{
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", sans-serif',
      color: C.text, height: '100vh', display: 'flex', flexDirection: 'column', background: C.bg,
      WebkitFontSmoothing: 'antialiased',
    }}>
      {/* Nav */}
      <nav style={{
        background: C.surface, borderBottom: `1px solid ${C.border}`,
        padding: mobile ? '0 12px' : '0 24px',
        paddingTop: 'env(safe-area-inset-top)',
        display: 'flex', alignItems: 'center', minHeight: mobile ? 48 : 52, flexShrink: 0, gap: mobile ? 2 : 4,
      }}>
        <span style={{ fontWeight: 700, fontSize: mobile ? 15 : 16, marginRight: mobile ? 12 : 28, color: C.white, letterSpacing: '-0.02em', whiteSpace: 'nowrap' }}>
          NHC{!mobile && <span style={{ fontWeight: 400, color: C.textMuted }}> Admin</span>}
        </span>
        {(['home', 'explorer', 'query', 'map'] as Page[]).map(p => {
          const labels = mobile
            ? { home: '🏠', explorer: '📋', query: '⚡', map: '🗺️' }
            : { home: '🏠 Home', explorer: '📋 Data', query: '⚡ Query', map: '🗺️ Map' }
          return (
            <button key={p} onClick={() => setPage(p)}
              style={{
                ...navBtnDark, padding: mobile ? '8px 10px' : '8px 14px',
                fontSize: mobile ? 14 : 13,
                ...(page === p ? { color: C.white, background: C.surfaceActive } : {}),
              }}>
              {labels[p]}
            </button>
          )
        })}
        {!mobile && (
          <>
            <div style={{ flex: 1 }} />
            <span style={{ fontSize: 11, color: C.textMuted }}>{fmtNum(tables.length)} tables · {fmtCompact(totalRows)} rows</span>
          </>
        )}
      </nav>

      {/* Content */}
      <div style={{ flex: 1, overflow: 'hidden', padding: mobile ? 12 : 20, paddingBottom: mobile ? 'max(12px, env(safe-area-inset-bottom))' : 20, minHeight: 0 }}>

        {/* HOME */}
        {page === 'home' && (
          <div style={{ overflow: 'auto', height: '100%' }}>
            <h2 style={{ fontSize: mobile ? 18 : 20, fontWeight: 700, margin: '0 0 8px', color: C.white }}>Dashboard</h2>
            {usage ? (
              <>
                <div style={{ fontSize: 12, color: C.textMuted, marginBottom: 14 }}>
                  Updated {fmtDate(usage.freshness.generated_at)} · latest session {fmtAge(usage.freshness.staleness_seconds)}
                </div>
                <div style={{ ...cardDark, marginBottom: 16 }}>
                  <div style={{ fontSize: 12, color: C.textSecondary, marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.04em' }}>Claude Rate Limit</div>
                  <div style={{ display: 'flex', alignItems: mobile ? 'flex-start' : 'center', justifyContent: 'space-between', gap: 10, flexDirection: mobile ? 'column' : 'row' }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <span style={{ fontSize: 12, color: C.textMuted }}>Status</span>
                      <span style={{
                        fontSize: 12, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.04em',
                        color: usage.claude_rate_limit.status === 'limited' ? C.danger : usage.claude_rate_limit.status === 'active' ? C.success : C.textMuted,
                      }}>
                        {usage.claude_rate_limit.status}
                      </span>
                    </div>
                    <div style={{ fontSize: 12, color: C.textSecondary }}>
                      {usage.claude_rate_limit.reset_at ? `Resets ${fmtDate(usage.claude_rate_limit.reset_at)}` : 'reset time unavailable from current telemetry'}
                    </div>
                  </div>
                  {usage.claude_rate_limit.reset_at ? (
                    <div style={{ marginTop: 8, fontSize: 20, fontWeight: 700, color: C.white, fontVariantNumeric: 'tabular-nums' }}>
                      {fmtCountdown(
                        Math.max(
                          Math.floor((new Date(usage.claude_rate_limit.reset_at).getTime() - nowMs) / 1000),
                          0
                        )
                      )}
                    </div>
                  ) : (
                    <div style={{ marginTop: 8, fontSize: 12, color: C.textMuted }}>
                      {usage.claude_rate_limit.reason || 'Reset time unavailable from current telemetry.'}
                    </div>
                  )}
                </div>
                <div style={{ display: 'grid', gap: 10, marginBottom: 16, gridTemplateColumns: mobile ? 'repeat(2, 1fr)' : 'repeat(auto-fill, minmax(180px, 1fr))' }}>
                  <StatCard label="Total Tokens" value={fmtCompact(usage.totals.total_tokens)} sub={mobile ? undefined : fmtNum(usage.totals.total_tokens)} />
                  <StatCard label="Input / Output" value={`${fmtCompact(usage.totals.input_tokens)} / ${fmtCompact(usage.totals.output_tokens)}`} />
                  <StatCard label="Active (24h)" value={String(usage.windows.last_24h?.session_count ?? 0)} />
                  <StatCard label="Burn Rate (24h)" value={`${fmtCompact(Math.round(usage.windows.last_24h?.burn_rate_tokens_per_hour ?? 0))}/h`} accent />
                </div>

                <div style={{ ...cardDark, marginBottom: 16 }}>
                  <div style={{ fontSize: 12, color: C.textSecondary, marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.04em' }}>24h Trend</div>
                  <div style={{ display: 'flex', alignItems: 'flex-end', gap: 6, height: 80 }}>
                    {usage.trend.buckets.map((b, i) => {
                      const max = Math.max(...usage.trend.buckets.map(x => x.total_tokens), 1)
                      const h = Math.max(6, Math.round((b.total_tokens / max) * 72))
                      return (
                        <div key={i} title={`${fmtDate(b.start)} · ${fmtNum(b.total_tokens)} tokens`} style={{ flex: 1, height: h, background: C.accentBg, border: `1px solid ${C.accentDim}50`, borderRadius: 4 }} />
                      )
                    })}
                  </div>
                </div>

                <h3 style={{ fontSize: 13, fontWeight: 600, color: C.textSecondary, margin: '0 0 10px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Top Consumers</h3>
                <div style={{ ...cardDark, padding: 0, overflow: 'hidden' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: mobile ? '1.4fr 1fr 1fr' : '1.8fr 1fr 1fr 1fr 1fr', padding: '10px 12px', fontSize: 11, color: C.textMuted, borderBottom: `1px solid ${C.border}` }}>
                    <div>Session</div><div>Total</div><div>Share</div>{!mobile && <><div>Burn/h</div><div>Updated</div></>}
                  </div>
                  {(usage.top_consumers.length ? usage.top_consumers : usage.sessions.slice(0, 10)).map(s => (
                    <div key={s.key} style={{ display: 'grid', gridTemplateColumns: mobile ? '1.4fr 1fr 1fr' : '1.8fr 1fr 1fr 1fr 1fr', padding: '10px 12px', fontSize: 12, borderBottom: `1px solid ${C.border}` }}>
                      <div style={{ color: C.white, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.label}</div>
                      <div>{fmtCompact(s.total_tokens)}</div>
                      <div>{(s.share_pct ?? 0).toFixed(1)}%</div>
                      {!mobile && <><div>{fmtCompact(Math.round(s.burn_rate_24h_est ?? 0))}</div><div style={{ color: C.textMuted }}>{fmtDate(s.updated_at)}</div></>}
                    </div>
                  ))}
                </div>

                <h3 style={{ fontSize: 13, fontWeight: 600, color: C.textSecondary, margin: '16px 0 10px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Model Usage</h3>
                <div style={{ ...cardDark, padding: 0, overflow: 'hidden' }}>
                  <div style={{ display: 'grid', gridTemplateColumns: mobile ? '1.6fr 1fr' : '1.8fr 1fr 1fr 1fr', padding: '10px 12px', fontSize: 11, color: C.textMuted, borderBottom: `1px solid ${C.border}` }}>
                    <div>Model</div><div>Total</div>{!mobile && <><div>Input / Output</div><div>Sessions</div></>}
                  </div>
                  {(usage.models ?? []).slice().sort((a, b) => b.total_tokens - a.total_tokens).map((m) => (
                    <div key={m.model} style={{ padding: '10px 12px', borderBottom: `1px solid ${C.border}` }}>
                      <div style={{ display: 'grid', gridTemplateColumns: mobile ? '1.6fr 1fr' : '1.8fr 1fr 1fr 1fr', fontSize: 12 }}>
                        <div style={{ color: C.white, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{m.model}</div>
                        <div>{fmtCompact(m.total_tokens)}</div>
                        {!mobile && <><div>{fmtCompact(m.input_tokens)} / {fmtCompact(m.output_tokens)}</div><div>{m.session_count}</div></>}
                      </div>
                      {m.top_sessions.length > 0 && (
                        <div style={{ marginTop: 6, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                          {m.top_sessions.map(ts => (
                            <span key={ts.key} style={{ fontSize: 11, color: C.textMuted }}>
                              {ts.label} {Math.round(ts.share_within_model_pct)}%
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  ))}
                  {(!usage.models || usage.models.length === 0) && (
                    <div style={{ padding: 12, fontSize: 12, color: C.textMuted }}>No model usage found in current telemetry.</div>
                  )}
                </div>
              </>
            ) : (
              <div style={{ ...cardDark }}>
                <div style={{ color: C.textMuted, fontSize: 13 }}>
                  {usageLoadFailed
                    ? 'Unable to load usage data. Your auth session may have expired — refresh and sign in again.'
                    : 'Loading usage data…'}
                </div>
              </div>
            )}
          </div>
        )}

        {/* DATA EXPLORER */}
        {page === 'explorer' && (
          <div style={{ display: 'flex', gap: 16, height: '100%', minHeight: 0 }}>
            {/* Desktop sidebar */}
            {!mobile && (
              <div style={{ width: 240, flexShrink: 0, display: 'flex', flexDirection: 'column', background: C.surface, borderRadius: 10, border: `1px solid ${C.border}`, overflow: 'hidden' }}>
                <div style={{ flex: 1, overflowY: 'auto' }}>{sidebarContent}</div>
              </div>
            )}

            {/* Mobile drawer */}
            {mobile && <SidebarDrawer open={drawerOpen} onClose={() => setDrawerOpen(false)}>{sidebarContent}</SidebarDrawer>}

            {/* Main area */}
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              {selected ? (
                <>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10, flexShrink: 0, flexWrap: 'wrap' }}>
                    {mobile && (
                      <button onClick={() => setDrawerOpen(true)}
                        style={{ ...pillBtn, height: 34, fontSize: 14, padding: '0 12px' }}>☰</button>
                    )}
                    <h2 style={{ fontSize: mobile ? 16 : 18, fontWeight: 700, margin: 0, color: C.white }}>{selected}</h2>
                    <SchemaToggle tableName={selected} />
                  </div>
                  <DataTable tableName={selected} mobile={mobile} />
                </>
              ) : (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '100%', color: C.textMuted, fontSize: 14, gap: 12 }}>
                  {mobile ? (
                    <button onClick={() => setDrawerOpen(true)}
                      style={{ ...pillBtn, fontSize: 14, padding: '12px 24px' }}>☰ Select a table</button>
                  ) : 'Select a table from the sidebar'}
                </div>
              )}
            </div>
          </div>
        )}

        {/* QUERY */}
        {page === 'query' && <QueryPage mobile={mobile} />}

        {/* MAP */}
        {page === 'map' && (
          <div style={{
            height: 'calc(100vh - 100px)',
            borderRadius: 10, overflow: 'hidden',
          }}>
            <ForeclosureMap />
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Small components ── */

function StatCard({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div style={{ ...cardDark, padding: 14 }}>
      <div style={{ fontSize: 10, color: C.textMuted, marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 24, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: accent ? C.accent : C.white, letterSpacing: '-0.02em' }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: C.textMuted, marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

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
