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
}
interface UsageData { sessions: SessionInfo[]; totals: { total_tokens: number; input_tokens: number; output_tokens: number } }
interface GroupRow { value: unknown; count: number }
interface ActiveFilter { id: string; column: string; operator: string; value: string; value2?: string }

type Page = 'home' | 'explorer' | 'query'
type SortDir = 'asc' | 'desc' | null

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
  successBg: 'rgba(34,197,94,0.08)',
}

/* ── Table → Project grouping ── */

const PROJECT_GROUPS: { label: string; icon: string; match: (name: string) => boolean }[] = [
  {
    label: 'NHL Betting', icon: '🏒',
    match: (n) => [
      'games', 'game_team_stats', 'player_stats', 'players', 'teams', 'standings',
      'schedules', 'injuries', 'injuries_live', 'lineup_absences', 'period_scores',
      'goalie_advanced', 'goalie_saves_by_strength', 'goalie_starts', 'goalie_stats',
      'saves_odds', 'sog_odds', 'predictions', 'model_runs', 'theses',
      'live_game_snapshots', 'positions',
    ].includes(n),
  },
  {
    label: 'Polymarket', icon: '📊',
    match: (n) => ['markets', 'market_snapshots'].includes(n),
  },
  {
    label: 'Real Estate', icon: '🏠',
    match: (n) => n.startsWith('cook_county_') || n === 'sf_rentals',
  },
  {
    label: 'Crypto', icon: '₿',
    match: (n) => n.startsWith('crypto_'),
  },
  {
    label: 'Dashboard', icon: '⚙️',
    match: (n) => ['kanban_events', 'kanban_tasks', 'agent_log', 'api_snapshots', 'human_notes'].includes(n),
  },
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

const NUMERIC_TYPES = new Set(['integer', 'bigint', 'smallint', 'numeric', 'real', 'double precision'])
const DATE_TYPES = new Set(['date', 'timestamp without time zone', 'timestamp with time zone'])

function isNumericType(dt: string) { return NUMERIC_TYPES.has(dt) }
function isDateType(dt: string) { return DATE_TYPES.has(dt) }

function operatorsForType(dt: string): { value: string; label: string }[] {
  if (isNumericType(dt)) return [
    { value: 'eq', label: '=' }, { value: 'ne', label: '≠' },
    { value: 'gt', label: '>' }, { value: 'lt', label: '<' },
    { value: 'gte', label: '≥' }, { value: 'lte', label: '≤' },
    { value: 'between', label: 'between' },
  ]
  if (isDateType(dt)) return [
    { value: 'before', label: 'before' }, { value: 'after', label: 'after' },
    { value: 'between', label: 'between' },
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

/* ── Filter Bar Component ── */

function FilterBar({ columns, typeMap, filters, onChange }: {
  columns: string[]
  typeMap: Record<string, string>
  filters: ActiveFilter[]
  onChange: (filters: ActiveFilter[]) => void
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
        const ops = operatorsForType(dt)
        updated.operator = ops[0].value
        updated.value = ''
        updated.value2 = undefined
      }
      return updated
    }))
  }

  function removeFilter(id: string) {
    onChange(filters.filter(f => f.id !== id))
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {filters.map(f => {
        const dt = typeMap[f.column] || ''
        const ops = operatorsForType(dt)
        const isBetween = f.operator === 'between'
        const inputType = isNumericType(dt) ? 'number' : isDateType(dt) ? 'date' : 'text'
        return (
          <div key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <select value={f.column} onChange={e => updateFilter(f.id, { column: e.target.value })}
              style={selectDark}>
              {columns.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={f.operator} onChange={e => updateFilter(f.id, { operator: e.target.value })}
              style={{ ...selectDark, width: 110 }}>
              {ops.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <input type={inputType} value={f.value} placeholder={isBetween ? 'Min' : 'Value'}
              onChange={e => updateFilter(f.id, { value: e.target.value })}
              style={{ ...inputDark, width: isBetween ? 100 : 160 }} />
            {isBetween && (
              <>
                <span style={{ fontSize: 12, color: C.textMuted }}>to</span>
                <input type={inputType} value={f.value2 ?? ''} placeholder="Max"
                  onChange={e => updateFilter(f.id, { value2: e.target.value })}
                  style={{ ...inputDark, width: 100 }} />
              </>
            )}
            <button onClick={() => removeFilter(f.id)}
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: C.textMuted, padding: '0 4px', lineHeight: 1 }}
              onMouseEnter={e => (e.currentTarget.style.color = C.danger)}
              onMouseLeave={e => (e.currentTarget.style.color = C.textMuted)}>
              ×
            </button>
          </div>
        )
      })}
      <button onClick={addFilter}
        style={{
          ...pillBtn, alignSelf: 'flex-start',
          marginTop: filters.length > 0 ? 2 : 0,
        }}>
        + Add Filter
      </button>
    </div>
  )
}

/* ── Schema Panel ── */

function SchemaToggle({ tableName }: { tableName: string }) {
  const [open, setOpen] = useState(false)
  const [schema, setSchema] = useState<SchemaColumn[]>([])

  useEffect(() => { setOpen(false); setSchema([]) }, [tableName])

  useEffect(() => {
    if (open && schema.length === 0) {
      fetch(`${API}/tables/${tableName}/schema`).then(r => r.json()).then(d => setSchema(d.columns))
    }
  }, [open, tableName])

  return (
    <div style={{ position: 'relative' }}>
      <button onClick={() => setOpen(!open)}
        style={{
          ...pillBtn,
          background: open ? C.accent : C.surfaceActive,
          color: open ? C.white : C.textSecondary,
          borderColor: open ? C.accent : C.borderLight,
        }}>
        {open ? '▾' : '▸'} Schema
      </button>
      {open && schema.length > 0 && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, marginTop: 6, zIndex: 20,
          background: C.surface, border: `1px solid ${C.border}`, borderRadius: 8,
          boxShadow: '0 8px 24px rgba(0,0,0,0.4)', padding: 0, minWidth: 360, maxHeight: 400, overflowY: 'auto',
        }}>
          <div style={{ padding: '10px 14px', borderBottom: `1px solid ${C.border}`, fontSize: 11, fontWeight: 600, color: C.textSecondary, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {schema.length} columns
          </div>
          {schema.map((c, i) => (
            <div key={c.column_name} style={{
              display: 'flex', alignItems: 'center', gap: 12, padding: '8px 14px',
              borderBottom: i < schema.length - 1 ? `1px solid ${C.border}` : 'none',
              fontSize: 12,
            }}>
              <span style={{ fontFamily: 'monospace', color: C.text, flex: 1 }}>{c.column_name}</span>
              <span style={{
                padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 500,
                background: isNumericType(c.data_type) ? 'rgba(79,140,255,0.12)' : isDateType(c.data_type) ? 'rgba(168,85,247,0.12)' : 'rgba(255,255,255,0.06)',
                color: isNumericType(c.data_type) ? '#7ab0ff' : isDateType(c.data_type) ? '#c084fc' : C.textSecondary,
              }}>{c.data_type}</span>
              {c.is_nullable === 'YES' && (
                <span style={{ fontSize: 10, color: C.textMuted }}>null</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ── Virtualized Data Table ── */

function DataTable({ tableName }: { tableName: string }) {
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
  const BATCH = 200
  const tableContainerRef = useRef<HTMLDivElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const fetchingRef = useRef(false)

  useEffect(() => {
    fetch(`${API}/tables/${tableName}/schema`).then(r => r.json()).then(d => setSchema(d.columns))
  }, [tableName])

  const typeMap = useMemo(() => {
    const m: Record<string, string> = {}
    for (const c of schema) m[c.column_name] = c.data_type
    return m
  }, [schema])

  useEffect(() => {
    setAllData([]); setSortBy(null); setSortDir(null); setFilters([])
    setGroupBy(null); setGroupData([]); setHasMore(true); setQuickSearch('')
  }, [tableName])

  const buildFilterParam = useCallback(() => {
    const active = filters.filter(f => f.value.trim() !== '')
    if (active.length === 0) return null
    return JSON.stringify(active.map(f => {
      const dt = typeMap[f.column] || ''
      if (f.operator === 'between') {
        const vals: (string | number)[] = []
        if (isNumericType(dt)) vals.push(Number(f.value), Number(f.value2 ?? f.value))
        else vals.push(f.value, f.value2 ?? f.value)
        return { column: f.column, operator: f.operator, value: vals }
      }
      const val = isNumericType(dt) ? Number(f.value) : f.value
      return { column: f.column, operator: f.operator, value: val }
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

  const onFiltersChange = useCallback((newFilters: ActiveFilter[]) => setFilters(newFilters), [])

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

  function sortIcon(col: string) {
    if (sortBy !== col) return <span style={{ opacity: 0.3 }}>↕</span>
    return <span style={{ color: C.accent }}>{sortDir === 'asc' ? '↑' : '↓'}</span>
  }

  function filterByGroup(value: unknown) {
    if (!groupBy) return
    const dt = typeMap[groupBy] || ''
    const op = isNumericType(dt) ? 'eq' : 'equals'
    setFilters(prev => [...prev, { id: nextFilterId(), column: groupBy, operator: op, value: String(value ?? '') }])
    setGroupBy(null)
  }

  // Quick search: client-side filter on visible data
  const displayData = useMemo(() => {
    if (!quickSearch.trim()) return allData
    const q = quickSearch.toLowerCase()
    return allData.filter(row =>
      Object.values(row).some(v => v !== null && v !== undefined && String(v).toLowerCase().includes(q))
    )
  }, [allData, quickSearch])

  const colDefs: ColumnDef<Record<string, unknown>, unknown>[] = useMemo(
    () => columns.map(c => ({
      accessorKey: c,
      header: c,
      size: 160,
      cell: (info: { getValue: () => unknown }) => {
        const v = info.getValue()
        if (v === null || v === undefined) return <span style={{ color: C.textMuted, fontStyle: 'italic' }}>null</span>
        if (typeof v === 'boolean') return <span style={{ color: v ? C.success : C.danger }}>{String(v)}</span>
        return String(v)
      },
    })),
    [columns]
  )

  const table = useReactTable({ data: displayData, columns: colDefs, getCoreRowModel: getCoreRowModel(), manualSorting: true, manualFiltering: true })
  const { rows: tableRows } = table.getRowModel()

  const rowVirtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => tableContainerRef.current,
    estimateSize: () => 36,
    overscan: 20,
  })

  useEffect(() => {
    const el = tableContainerRef.current
    if (!el) return
    function onScroll() {
      if (!el || !hasMore || fetchingRef.current) return
      if (el.scrollTop + el.clientHeight >= el.scrollHeight - 200) fetchBatch(allData.length, true)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [hasMore, allData.length, fetchBatch])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 10 }}>
      {/* Toolbar row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        {/* Quick search */}
        <div style={{ position: 'relative', width: 260, flexShrink: 0 }}>
          <span style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: C.textMuted, fontSize: 14, pointerEvents: 'none' }}>🔍</span>
          <input
            type="text" value={quickSearch} onChange={e => setQuickSearch(e.target.value)}
            placeholder="Quick search loaded rows…"
            style={{ ...inputDark, width: '100%', paddingLeft: 32, height: 32, boxSizing: 'border-box' }}
          />
        </div>
        <div style={{ flex: 1, minWidth: 200 }}>
          <FilterBar columns={columns} typeMap={typeMap} filters={filters} onChange={onFiltersChange} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          <span style={{ fontSize: 12, color: C.textMuted }}>Group:</span>
          <select value={groupBy ?? ''} onChange={e => setGroupBy(e.target.value || null)} style={selectDark}>
            <option value="">None</option>
            {columns.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      </div>

      {/* Status bar */}
      <div style={{ fontSize: 12, color: C.textSecondary, display: 'flex', gap: 16, alignItems: 'center' }}>
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
        <div style={{ maxHeight: 200, overflowY: 'auto', border: `1px solid ${C.border}`, borderRadius: 8, background: C.surface }}>
          {groupData.map((g, i) => {
            const key = String(g.value ?? 'NULL')
            return (
              <button key={key} onClick={() => filterByGroup(g.value)}
                style={{
                  width: '100%', padding: '8px 14px', background: 'transparent',
                  border: 'none', borderBottom: i < groupData.length - 1 ? `1px solid ${C.border}` : 'none',
                  cursor: 'pointer', display: 'flex', justifyContent: 'space-between', fontSize: 12,
                  fontFamily: 'inherit', color: C.text, transition: 'background 0.15s',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = C.surfaceHover)}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                <span>{key}</span>
                <span style={{ color: C.textMuted, fontVariantNumeric: 'tabular-nums' }}>{fmtNum(g.count)}</span>
              </button>
            )
          })}
        </div>
      )}

      {/* Table */}
      <div ref={tableContainerRef}
        style={{
          flex: 1, overflow: 'auto', border: `1px solid ${C.border}`, borderRadius: 8,
          background: C.surface, minHeight: 0,
        }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, tableLayout: 'fixed' }}>
          <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
            <tr>
              {table.getHeaderGroups()[0]?.headers.map(h => {
                const col = h.column.id
                return (
                  <th key={h.id} onClick={() => handleSort(col)}
                    style={{ ...thDark, cursor: 'pointer', userSelect: 'none', width: h.column.getSize() }}>
                    <span>{flexRender(h.column.columnDef.header, h.getContext())}</span>
                    <span style={{ fontSize: 10, marginLeft: 4 }}>{sortIcon(col)}</span>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {rowVirtualizer.getVirtualItems().length > 0 && (
              <tr><td style={{ height: rowVirtualizer.getVirtualItems()[0]?.start ?? 0, padding: 0 }} colSpan={columns.length} /></tr>
            )}
            {rowVirtualizer.getVirtualItems().map(virtualRow => {
              const row = tableRows[virtualRow.index]
              return (
                <tr key={row.id} style={{ height: 36, borderBottom: `1px solid ${C.border}` }}
                  onMouseEnter={e => (e.currentTarget.style.background = C.surfaceHover)}
                  onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                  {row.getVisibleCells().map(cell => (
                    <td key={cell.id} style={tdDark}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              )
            })}
            {rowVirtualizer.getVirtualItems().length > 0 && (
              <tr><td style={{
                height: (() => {
                  const items = rowVirtualizer.getVirtualItems()
                  const last = items[items.length - 1]
                  return rowVirtualizer.getTotalSize() - (last?.end ?? 0)
                })(), padding: 0,
              }} colSpan={columns.length} /></tr>
            )}
          </tbody>
        </table>
        {displayData.length === 0 && !loading && (
          <div style={{ padding: 40, textAlign: 'center', color: C.textMuted }}>No data to display</div>
        )}
      </div>
    </div>
  )
}

/* ── Query Page ── */

function QueryPage() {
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
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', gap: 14 }}>
      {/* Mode toggle */}
      <div style={{ display: 'flex', gap: 0 }}>
        <button onClick={() => { setMode('ask'); setInput(''); setResult(null) }}
          style={{ ...modeBtn, borderRadius: '8px 0 0 8px', ...(mode === 'ask' ? modeBtnActive : {}) }}>
          Ask in English
        </button>
        <button onClick={() => { setMode('sql'); setInput(''); setResult(null) }}
          style={{ ...modeBtn, borderRadius: '0 8px 8px 0', ...(mode === 'sql' ? modeBtnActive : {}) }}>
          Raw SQL
        </button>
      </div>

      {/* Input */}
      <div style={{ display: 'flex', gap: 10 }}>
        {mode === 'sql' ? (
          <textarea value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit() }}
            placeholder="SELECT * FROM teams LIMIT 10"
            style={{ ...inputDark, flex: 1, fontFamily: 'monospace', resize: 'vertical', minHeight: 100, padding: 12 }} />
        ) : (
          <input type="text" value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleSubmit() }}
            placeholder="e.g. Show me all goalies with more than 30 saves"
            style={{ ...inputDark, flex: 1, padding: '10px 14px', fontSize: 14, height: 42 }} />
        )}
        <button onClick={handleSubmit} disabled={loading || !input.trim()}
          style={{
            padding: '10px 24px', background: C.accent, color: C.white, border: 'none',
            borderRadius: 8, cursor: loading ? 'wait' : 'pointer', fontSize: 14, fontWeight: 600,
            fontFamily: 'inherit', opacity: loading || !input.trim() ? 0.5 : 1,
            transition: 'opacity 0.15s',
          }}>
          {loading ? '…' : 'Run'}
        </button>
      </div>

      {summary && (
        <div style={{ padding: '12px 16px', background: C.accentBg, border: `1px solid ${C.accentDim}30`, borderRadius: 8, fontSize: 13, lineHeight: 1.5, color: C.accent }}>
          {summary}
        </div>
      )}

      {generatedSql && (
        <div>
          <button onClick={() => setShowSql(!showSql)} style={{ ...pillBtn, fontSize: 12 }}>
            {showSql ? '▾' : '▸'} Generated SQL
          </button>
          {showSql && (
            <pre style={{ margin: '8px 0 0', padding: 12, background: C.surfaceActive, borderRadius: 8, fontSize: 12, overflow: 'auto', fontFamily: 'monospace', color: C.text, border: `1px solid ${C.border}` }}>
              {generatedSql}
            </pre>
          )}
        </div>
      )}

      {result && (result.error ? (
        <div style={{ padding: 14, background: C.dangerBg, border: `1px solid ${C.danger}30`, borderRadius: 8, color: C.danger, fontSize: 13 }}>
          {result.error}
        </div>
      ) : (
        <div style={{ flex: 1, overflow: 'auto', border: `1px solid ${C.border}`, borderRadius: 8, minHeight: 0, background: C.surface }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
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
          <div style={{ fontSize: 12, color: C.textMuted, padding: '8px 12px', borderTop: `1px solid ${C.border}` }}>{result.rows.length} rows returned</div>
        </div>
      ))}
    </div>
  )
}

/* ── Main App ── */

export default function App() {
  const [page, setPage] = useState<Page>('home')
  const [tables, setTables] = useState<TableInfo[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [usage, setUsage] = useState<UsageData | null>(null)
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({})
  const [sidebarSearch, setSidebarSearch] = useState('')

  const grouped = useMemo(() => groupTables(tables), [tables])

  // Filter sidebar tables by search
  const filteredGroups = useMemo(() => {
    if (!sidebarSearch.trim()) return grouped
    const q = sidebarSearch.toLowerCase()
    return grouped.map(g => ({
      ...g,
      tables: g.tables.filter(t => t.name.toLowerCase().includes(q)),
    })).filter(g => g.tables.length > 0)
  }, [grouped, sidebarSearch])

  function toggleGroup(label: string) {
    setCollapsed(prev => ({ ...prev, [label]: !prev[label] }))
  }

  useEffect(() => { fetch(`${API}/tables`).then(r => r.json()).then(setTables) }, [])
  useEffect(() => { fetch(`${API}/usage`).then(r => r.json()).then(setUsage) }, [])

  const totalRows = useMemo(() => tables.reduce((s, t) => s + t.row_count, 0), [tables])

  return (
    <div style={{
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Inter", sans-serif',
      color: C.text, height: '100vh', display: 'flex', flexDirection: 'column', background: C.bg,
      WebkitFontSmoothing: 'antialiased',
    }}>
      {/* Nav */}
      <nav style={{
        background: C.surface, borderBottom: `1px solid ${C.border}`, padding: '0 24px',
        display: 'flex', alignItems: 'center', height: 52, flexShrink: 0, gap: 4,
      }}>
        <span style={{ fontWeight: 700, fontSize: 16, marginRight: 28, color: C.white, letterSpacing: '-0.02em' }}>
          NHC <span style={{ fontWeight: 400, color: C.textMuted }}>Admin</span>
        </span>
        {(['home', 'explorer', 'query'] as Page[]).map(p => (
          <button key={p} onClick={() => setPage(p)}
            style={{
              ...navBtnDark,
              ...(page === p ? { color: C.white, background: C.surfaceActive } : {}),
            }}>
            {p === 'home' ? '🏠 Home' : p === 'explorer' ? '📋 Data Explorer' : '⚡ Query'}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: 11, color: C.textMuted }}>
          {fmtNum(tables.length)} tables · {fmtCompact(totalRows)} rows
        </span>
      </nav>

      {/* Content */}
      <div style={{ flex: 1, overflow: 'hidden', padding: 20, minHeight: 0 }}>

        {/* HOME */}
        {page === 'home' && (
          <div style={{ overflow: 'auto', height: '100%', maxWidth: 1100 }}>
            <h2 style={{ fontSize: 20, fontWeight: 700, margin: '0 0 20px', color: C.white }}>Dashboard</h2>
            {usage ? (
              <>
                <div style={{ display: 'grid', gap: 14, marginBottom: 24, gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))' }}>
                  <StatCard label="Total Tokens" value={fmtCompact(usage.totals.total_tokens)} sub={fmtNum(usage.totals.total_tokens)} />
                  <StatCard label="Input Tokens" value={fmtCompact(usage.totals.input_tokens)} sub={fmtNum(usage.totals.input_tokens)} />
                  <StatCard label="Output Tokens" value={fmtCompact(usage.totals.output_tokens)} sub={fmtNum(usage.totals.output_tokens)} />
                  <StatCard label="Active Sessions" value={String(usage.sessions.length)} accent />
                </div>
                <h3 style={{ fontSize: 14, fontWeight: 600, color: C.textSecondary, margin: '0 0 12px', textTransform: 'uppercase', letterSpacing: '0.04em' }}>Sessions</h3>
                <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
                  {usage.sessions.map(s => (
                    <div key={s.key} style={cardDark}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                        <div style={{ fontSize: 13, fontWeight: 600, color: C.white, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '70%' }}>
                          {s.label}
                        </div>
                        <span style={{ fontSize: 10, color: C.textMuted, fontVariantNumeric: 'tabular-nums', flexShrink: 0 }}>
                          {fmtDate(s.updated_at)}
                        </span>
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 8, fontSize: 11 }}>
                        <div>
                          <div style={{ color: C.textMuted, marginBottom: 2 }}>Total</div>
                          <div style={{ color: C.text, fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>{fmtCompact(s.total_tokens)}</div>
                        </div>
                        <div>
                          <div style={{ color: C.textMuted, marginBottom: 2 }}>In / Out</div>
                          <div style={{ color: C.text, fontVariantNumeric: 'tabular-nums', fontWeight: 500 }}>{fmtCompact(s.input_tokens)} / {fmtCompact(s.output_tokens)}</div>
                        </div>
                        <div>
                          <div style={{ color: C.textMuted, marginBottom: 2 }}>Model</div>
                          <div style={{ color: C.accent, fontSize: 10, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{s.model || '—'}</div>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : <p style={{ color: C.textMuted }}>Loading…</p>}
          </div>
        )}

        {/* DATA EXPLORER */}
        {page === 'explorer' && (
          <div style={{ display: 'flex', gap: 16, height: '100%', minHeight: 0 }}>
            {/* Sidebar */}
            <div style={{
              width: 240, flexShrink: 0, display: 'flex', flexDirection: 'column',
              background: C.surface, borderRadius: 10, border: `1px solid ${C.border}`,
              overflow: 'hidden',
            }}>
              {/* Sidebar search */}
              <div style={{ padding: '10px 10px 6px' }}>
                <input
                  type="text" value={sidebarSearch} onChange={e => setSidebarSearch(e.target.value)}
                  placeholder="Search tables…"
                  style={{ ...inputDark, width: '100%', height: 30, fontSize: 12, boxSizing: 'border-box', padding: '0 10px' }}
                />
              </div>
              <div style={{ flex: 1, overflowY: 'auto', padding: '4px 6px 10px' }}>
                {filteredGroups.map(g => {
                  const isCollapsed = collapsed[g.label] ?? false
                  return (
                    <div key={g.label} style={{ marginBottom: 2 }}>
                      <button onClick={() => toggleGroup(g.label)}
                        style={{
                          display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                          width: '100%', padding: '7px 8px', background: 'transparent', border: 'none',
                          cursor: 'pointer', borderRadius: 6, fontSize: 12, fontFamily: 'inherit',
                          fontWeight: 600, textAlign: 'left', color: C.text,
                          transition: 'background 0.12s',
                        }}
                        onMouseEnter={e => (e.currentTarget.style.background = C.surfaceHover)}
                        onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                        <span>{isCollapsed ? '▸' : '▾'} {g.icon} {g.label}</span>
                        <span style={{ fontSize: 10, color: C.textMuted, fontWeight: 400, fontVariantNumeric: 'tabular-nums' }}>{fmtCompact(g.totalRows)}</span>
                      </button>
                      {!isCollapsed && g.tables.map(t => (
                        <button key={t.name} onClick={() => setSelected(t.name)}
                          style={{
                            display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                            width: '100%', padding: '6px 8px 6px 28px', background: 'transparent',
                            border: 'none', cursor: 'pointer', borderRadius: 6, fontSize: 12,
                            fontFamily: 'inherit', textAlign: 'left', color: C.textSecondary,
                            transition: 'all 0.12s',
                            ...(selected === t.name ? { background: C.accentBg, color: C.accent, fontWeight: 600 } : {}),
                          }}
                          onMouseEnter={e => { if (selected !== t.name) e.currentTarget.style.background = C.surfaceHover }}
                          onMouseLeave={e => { if (selected !== t.name) e.currentTarget.style.background = 'transparent' }}>
                          <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{t.name}</span>
                          <span style={{ fontSize: 10, color: C.textMuted, fontVariantNumeric: 'tabular-nums', flexShrink: 0, marginLeft: 8 }}>{fmtCompact(t.row_count)}</span>
                        </button>
                      ))}
                    </div>
                  )
                })}
              </div>
            </div>

            {/* Table area */}
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              {selected ? (
                <>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 10, flexShrink: 0 }}>
                    <h2 style={{ fontSize: 18, fontWeight: 700, margin: 0, color: C.white }}>{selected}</h2>
                    <SchemaToggle tableName={selected} />
                  </div>
                  <DataTable tableName={selected} />
                </>
              ) : (
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', color: C.textMuted, fontSize: 14 }}>
                  Select a table from the sidebar
                </div>
              )}
            </div>
          </div>
        )}

        {/* QUERY */}
        {page === 'query' && <QueryPage />}
      </div>
    </div>
  )
}

/* ── Small components ── */

function StatCard({ label, value, sub, accent }: { label: string; value: string; sub?: string; accent?: boolean }) {
  return (
    <div style={{ ...cardDark, padding: 16 }}>
      <div style={{ fontSize: 11, color: C.textMuted, marginBottom: 6, textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 500 }}>{label}</div>
      <div style={{ fontSize: 26, fontWeight: 700, fontVariantNumeric: 'tabular-nums', color: accent ? C.accent : C.white, letterSpacing: '-0.02em' }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: C.textMuted, marginTop: 2, fontVariantNumeric: 'tabular-nums' }}>{sub}</div>}
    </div>
  )
}

/* ── Styles ── */

const cardDark: React.CSSProperties = {
  background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14,
}

const navBtnDark: React.CSSProperties = {
  background: 'none', border: 'none',
  padding: '8px 14px', cursor: 'pointer', fontSize: 13, color: C.textSecondary,
  fontFamily: 'inherit', borderRadius: 6, transition: 'all 0.12s', fontWeight: 500,
}

const pillBtn: React.CSSProperties = {
  padding: '5px 12px', background: C.surfaceActive, border: `1px solid ${C.borderLight}`,
  borderRadius: 6, cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', color: C.textSecondary,
  fontWeight: 500, transition: 'all 0.12s',
}

const selectDark: React.CSSProperties = {
  fontSize: 12, padding: '5px 8px', border: `1px solid ${C.borderLight}`, borderRadius: 6,
  fontFamily: 'inherit', background: C.surfaceActive, color: C.text, outline: 'none',
}

const inputDark: React.CSSProperties = {
  fontSize: 12, padding: '5px 10px', border: `1px solid ${C.borderLight}`, borderRadius: 6,
  fontFamily: 'inherit', boxSizing: 'border-box' as const, background: C.surfaceActive,
  color: C.text, outline: 'none',
}

const modeBtn: React.CSSProperties = {
  padding: '9px 20px', border: `1px solid ${C.borderLight}`, background: C.surface,
  cursor: 'pointer', fontSize: 13, fontFamily: 'inherit', color: C.textSecondary, fontWeight: 500,
  transition: 'all 0.12s',
}

const modeBtnActive: React.CSSProperties = {
  background: C.accent, color: C.white, borderColor: C.accent,
}

const thDark: React.CSSProperties = {
  padding: '8px 12px', textAlign: 'left', borderBottom: `2px solid ${C.border}`,
  fontSize: 11, fontWeight: 600, color: C.textSecondary, background: C.surface,
  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
  textTransform: 'uppercase', letterSpacing: '0.04em',
}

const tdDark: React.CSSProperties = {
  padding: '6px 12px', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis',
  whiteSpace: 'nowrap', fontSize: 12, color: C.text,
}
