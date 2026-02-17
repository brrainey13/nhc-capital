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
      // Reset operator when column changes
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {filters.map(f => {
        const dt = typeMap[f.column] || ''
        const ops = operatorsForType(dt)
        const isBetween = f.operator === 'between'
        const inputType = isNumericType(dt) ? 'number' : isDateType(dt) ? 'date' : 'text'
        return (
          <div key={f.id} style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <select value={f.column} onChange={e => updateFilter(f.id, { column: e.target.value })}
              style={selectStyle}>
              {columns.map(c => <option key={c} value={c}>{c}</option>)}
            </select>
            <select value={f.operator} onChange={e => updateFilter(f.id, { operator: e.target.value })}
              style={{ ...selectStyle, width: 100 }}>
              {ops.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
            <input type={inputType} value={f.value} placeholder={isBetween ? 'Min' : 'Value'}
              onChange={e => updateFilter(f.id, { value: e.target.value })}
              style={{ ...inputStyle, width: isBetween ? 90 : 140 }} />
            {isBetween && (
              <>
                <span style={{ fontSize: 12, color: '#888' }}>to</span>
                <input type={inputType} value={f.value2 ?? ''} placeholder="Max"
                  onChange={e => updateFilter(f.id, { value2: e.target.value })}
                  style={{ ...inputStyle, width: 90 }} />
              </>
            )}
            <button onClick={() => removeFilter(f.id)}
              style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: 16, color: '#999', padding: '0 4px', lineHeight: 1 }}>
              ×
            </button>
          </div>
        )
      })}
      <button onClick={addFilter}
        style={{ ...chipBtn, alignSelf: 'flex-start', marginTop: filters.length > 0 ? 2 : 0 }}>
        + Add Filter
      </button>
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

  // Reset on table change
  useEffect(() => {
    setAllData([])
    setSortBy(null)
    setSortDir(null)
    setFilters([])
    setGroupBy(null)
    setGroupData([])
    setHasMore(true)
  }, [tableName])

  // Build filter params for API
  const buildFilterParam = useCallback(() => {
    const active = filters.filter(f => f.value.trim() !== '')
    if (active.length === 0) return null
    return JSON.stringify(active.map(f => {
      const dt = typeMap[f.column] || ''
      if (f.operator === 'between') {
        const vals: (string | number)[] = []
        if (isNumericType(dt)) {
          vals.push(Number(f.value), Number(f.value2 ?? f.value))
        } else {
          vals.push(f.value, f.value2 ?? f.value)
        }
        return { column: f.column, operator: f.operator, value: vals }
      }
      const val = isNumericType(dt) ? Number(f.value) : f.value
      return { column: f.column, operator: f.operator, value: val }
    }))
  }, [filters, typeMap])

  const buildUrl = useCallback((offset: number) => {
    const params = new URLSearchParams({
      limit: String(BATCH),
      offset: String(offset),
    })
    if (sortBy && sortDir) {
      params.set('sort_by', sortBy)
      params.set('sort_dir', sortDir)
    }
    const fp = buildFilterParam()
    if (fp) params.set('filters', fp)
    return `${API}/tables/${tableName}/data?${params}`
  }, [tableName, sortBy, sortDir, buildFilterParam])

  // Fetch a batch
  const fetchBatch = useCallback(async (offset: number, append: boolean) => {
    if (fetchingRef.current) return
    fetchingRef.current = true
    setLoading(true)
    try {
      const r = await fetch(buildUrl(offset))
      const d = await r.json()
      if (append) {
        setAllData(prev => [...prev, ...d.rows])
      } else {
        setAllData(d.rows)
        setColumns(d.columns)
      }
      setTotal(d.total)
      setFilteredTotal(d.filtered_total)
      setHasMore(offset + d.rows.length < d.filtered_total)
    } finally {
      fetchingRef.current = false
      setLoading(false)
    }
  }, [buildUrl])

  // Initial load + reload on sort/table change
  useEffect(() => {
    setAllData([])
    setHasMore(true)
    fetchBatch(0, false)
  }, [sortBy, sortDir, tableName, buildFilterParam])

  // Debounced reload on filter change
  const onFiltersChange = useCallback((newFilters: ActiveFilter[]) => {
    setFilters(newFilters)
  }, [])

  // Reload on filter edit (debounced)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setAllData([])
      setHasMore(true)
      fetchBatch(0, false)
    }, 400)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [filters])

  // Group data
  useEffect(() => {
    if (!groupBy) { setGroupData([]); return }
    fetch(`${API}/tables/${tableName}/grouped?group_by=${groupBy}`)
      .then(r => r.json())
      .then(setGroupData)
  }, [tableName, groupBy])

  function handleSort(col: string) {
    if (sortBy !== col) { setSortBy(col); setSortDir('asc') }
    else if (sortDir === 'asc') setSortDir('desc')
    else { setSortBy(null); setSortDir(null) }
  }

  function sortIcon(col: string) {
    if (sortBy !== col) return '↕'
    return sortDir === 'asc' ? '↑' : '↓'
  }

  // Click a group row to filter by it
  function filterByGroup(value: unknown) {
    if (!groupBy) return
    const dt = typeMap[groupBy] || ''
    const op = isNumericType(dt) ? 'eq' : 'equals'
    const newFilter: ActiveFilter = {
      id: nextFilterId(), column: groupBy, operator: op, value: String(value ?? '')
    }
    setFilters(prev => [...prev, newFilter])
    setGroupBy(null)
  }

  const colDefs: ColumnDef<Record<string, unknown>, unknown>[] = useMemo(
    () => columns.map(c => ({
      accessorKey: c,
      header: c,
      size: 150,
      cell: (info: { getValue: () => unknown }) => {
        const v = info.getValue()
        if (v === null || v === undefined) return <span style={{ color: '#ccc' }}>null</span>
        return String(v)
      },
    })),
    [columns]
  )

  const table = useReactTable({
    data: allData,
    columns: colDefs,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualFiltering: true,
  })

  const { rows: tableRows } = table.getRowModel()

  const rowVirtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => tableContainerRef.current,
    estimateSize: () => 34,
    overscan: 20,
  })

  // Infinite scroll: fetch more when near bottom
  useEffect(() => {
    const el = tableContainerRef.current
    if (!el) return
    function onScroll() {
      if (!el || !hasMore || fetchingRef.current) return
      const { scrollTop, scrollHeight, clientHeight } = el
      if (scrollTop + clientHeight >= scrollHeight - 200) {
        fetchBatch(allData.length, true)
      }
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [hasMore, allData.length, fetchBatch])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Toolbar */}
      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 16, marginBottom: 8, flexWrap: 'wrap' }}>
        <div style={{ flex: 1 }}>
          <FilterBar columns={columns} typeMap={typeMap} filters={filters} onChange={onFiltersChange} />
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0, paddingTop: 2 }}>
          <span style={{ fontSize: 12, color: '#888' }}>Group:</span>
          <select value={groupBy ?? ''} onChange={e => setGroupBy(e.target.value || null)}
            style={selectStyle}>
            <option value="">None</option>
            {columns.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      </div>

      {/* Status bar */}
      <div style={{ fontSize: 12, color: '#888', marginBottom: 6, display: 'flex', gap: 12, alignItems: 'center' }}>
        <span>
          {filteredTotal < total
            ? `${fmtNum(filteredTotal)} of ${fmtNum(total)} rows`
            : `${fmtNum(total)} rows`}
        </span>
        <span>· Showing {fmtNum(allData.length)}</span>
        {loading && <span style={{ color: '#4a90d9' }}>Loading…</span>}
      </div>

      {/* Group-by panels */}
      {groupBy && groupData.length > 0 && (
        <div style={{ marginBottom: 8, maxHeight: 200, overflowY: 'auto', border: '1px solid #e0e0e0', borderRadius: 6 }}>
          {groupData.map(g => {
            const key = String(g.value ?? 'NULL')
            return (
              <button key={key} onClick={() => filterByGroup(g.value)}
                style={{
                  width: '100%', padding: '6px 12px', background: '#fff',
                  border: 'none', borderBottom: '1px solid #f0f0f0', cursor: 'pointer',
                  display: 'flex', justifyContent: 'space-between', fontSize: 12,
                  fontFamily: 'inherit',
                }}>
                <span>{key}</span>
                <span style={{ color: '#888' }}>{fmtNum(g.count)}</span>
              </button>
            )
          })}
        </div>
      )}

      {/* Virtualized Table */}
      <div ref={tableContainerRef}
        style={{
          flex: 1, overflow: 'auto', border: '1px solid #e0e0e0', borderRadius: 6,
          background: '#fff', minHeight: 0,
        }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, tableLayout: 'fixed' }}>
          <thead style={{ position: 'sticky', top: 0, zIndex: 1 }}>
            <tr>
              {table.getHeaderGroups()[0]?.headers.map(h => {
                const col = h.column.id
                return (
                  <th key={h.id} onClick={() => handleSort(col)}
                    style={{
                      ...thStyle, cursor: 'pointer', userSelect: 'none',
                      width: h.column.getSize(),
                    }}>
                    <span>{flexRender(h.column.columnDef.header, h.getContext())}</span>
                    <span style={{ fontSize: 9, marginLeft: 3, color: sortBy === col ? '#1a1a1a' : '#ccc' }}>
                      {sortIcon(col)}
                    </span>
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {/* Spacer for virtual items above */}
            {rowVirtualizer.getVirtualItems().length > 0 && (
              <tr><td style={{ height: rowVirtualizer.getVirtualItems()[0]?.start ?? 0, padding: 0 }} colSpan={columns.length} /></tr>
            )}
            {rowVirtualizer.getVirtualItems().map(virtualRow => {
              const row = tableRows[virtualRow.index]
              return (
                <tr key={row.id} style={{ height: 34, borderBottom: '1px solid #f5f5f5' }}>
                  {row.getVisibleCells().map(cell => (
                    <td key={cell.id} style={tdStyle}>
                      {flexRender(cell.column.columnDef.cell, cell.getContext())}
                    </td>
                  ))}
                </tr>
              )
            })}
            {/* Spacer for virtual items below */}
            {rowVirtualizer.getVirtualItems().length > 0 && (
              <tr><td style={{
                height: (() => {
                  const items = rowVirtualizer.getVirtualItems()
                  const last = items[items.length - 1]
                  return rowVirtualizer.getTotalSize() - (last?.end ?? 0)
                })(),
                padding: 0,
              }} colSpan={columns.length} /></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/* ── Query Page (NL + Raw SQL) ── */

function QueryPage() {
  const [mode, setMode] = useState<'ask' | 'sql'>('ask')
  const [input, setInput] = useState('')
  const [generatedSql, setGeneratedSql] = useState<string | null>(null)
  const [result, setResult] = useState<{ columns: string[]; rows: Record<string, unknown>[]; error?: string } | null>(null)
  const [loading, setLoading] = useState(false)
  const [showSql, setShowSql] = useState(false)

  function runNL() {
    if (!input.trim()) return
    setLoading(true)
    setResult(null)
    setGeneratedSql(null)
    fetch(`${API}/nl-query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: input }),
    })
      .then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.detail); return d })
      .then(d => {
        setGeneratedSql(d.sql)
        setResult({ columns: d.columns, rows: d.rows })
      })
      .catch(e => setResult({ columns: [], rows: [], error: e.message }))
      .finally(() => setLoading(false))
  }

  function runSQL() {
    if (!input.trim()) return
    setLoading(true)
    setResult(null)
    setGeneratedSql(null)
    fetch(`${API}/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql: input }),
    })
      .then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.detail); return d })
      .then(d => setResult({ columns: d.columns, rows: d.rows }))
      .catch(e => setResult({ columns: [], rows: [], error: e.message }))
      .finally(() => setLoading(false))
  }

  function handleSubmit() {
    mode === 'ask' ? runNL() : runSQL()
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Toggle */}
      <div style={{ display: 'flex', gap: 0, marginBottom: 12 }}>
        <button onClick={() => { setMode('ask'); setInput(''); setResult(null) }}
          style={{ ...tabBtn, ...(mode === 'ask' ? tabBtnActive : {}), borderRadius: '6px 0 0 6px' }}>
          Ask in English
        </button>
        <button onClick={() => { setMode('sql'); setInput(''); setResult(null) }}
          style={{ ...tabBtn, ...(mode === 'sql' ? tabBtnActive : {}), borderRadius: '0 6px 6px 0' }}>
          Raw SQL
        </button>
      </div>

      {/* Input */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        {mode === 'sql' ? (
          <textarea value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) handleSubmit() }}
            placeholder="SELECT * FROM teams LIMIT 10"
            style={{ flex: 1, padding: 10, fontSize: 13, fontFamily: 'monospace', border: '1px solid #ddd', borderRadius: 6, resize: 'vertical', minHeight: 80, boxSizing: 'border-box' }} />
        ) : (
          <input type="text" value={input} onChange={e => setInput(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') handleSubmit() }}
            placeholder="e.g. Show me all goalies with more than 30 saves"
            style={{ flex: 1, padding: '10px 12px', fontSize: 14, border: '1px solid #ddd', borderRadius: 6, fontFamily: 'inherit' }} />
        )}
        <button onClick={handleSubmit} disabled={loading || !input.trim()}
          style={{ ...btnStyle, background: '#1a1a1a', color: '#fff', padding: '10px 20px', opacity: loading ? 0.6 : 1 }}>
          {loading ? '…' : 'Run'}
        </button>
      </div>

      {/* Generated SQL (collapsible) */}
      {generatedSql && (
        <div style={{ marginBottom: 12 }}>
          <button onClick={() => setShowSql(!showSql)}
            style={{ ...chipBtn, fontSize: 12 }}>
            {showSql ? '▼' : '▶'} Generated SQL
          </button>
          {showSql && (
            <pre style={{ margin: '6px 0 0', padding: 10, background: '#f5f5f5', borderRadius: 6, fontSize: 12, overflow: 'auto', fontFamily: 'monospace' }}>
              {generatedSql}
            </pre>
          )}
        </div>
      )}

      {/* Results */}
      {result && (result.error ? (
        <div style={{ padding: 12, background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 6, color: '#dc2626', fontSize: 13 }}>
          {result.error}
        </div>
      ) : (
        <div style={{ flex: 1, overflow: 'auto', border: '1px solid #e0e0e0', borderRadius: 6, minHeight: 0 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead style={{ position: 'sticky', top: 0 }}>
              <tr>{result.columns.map(c => <th key={c} style={thStyle}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {result.rows.map((r, i) => (
                <tr key={i} style={{ borderBottom: '1px solid #f5f5f5' }}>
                  {result.columns.map(c => <td key={c} style={tdStyle}>{String(r[c] ?? '')}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ fontSize: 12, color: '#888', padding: 8 }}>{result.rows.length} rows</div>
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

  useEffect(() => { fetch(`${API}/tables`).then(r => r.json()).then(setTables) }, [])
  useEffect(() => { fetch(`${API}/usage`).then(r => r.json()).then(setUsage) }, [])

  // Full viewport layout
  const navHeight = 48
  const contentPadding = 16

  return (
    <div style={{
      fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
      color: '#1a1a1a', height: '100vh', display: 'flex', flexDirection: 'column', background: '#f8f9fa',
    }}>
      {/* Nav bar */}
      <nav style={{
        background: '#fff', borderBottom: '1px solid #e0e0e0', padding: '0 20px',
        display: 'flex', alignItems: 'center', height: navHeight, flexShrink: 0,
      }}>
        <span style={{ fontWeight: 700, fontSize: 15, marginRight: 24 }}>NHC Admin</span>
        {(['home', 'explorer', 'query'] as Page[]).map(p => (
          <button key={p} onClick={() => setPage(p)}
            style={{ ...navBtn, ...(page === p ? { color: '#1a1a1a', borderBottom: '2px solid #1a1a1a' } : {}) }}>
            {p === 'home' ? 'Home' : p === 'explorer' ? 'Data Explorer' : 'Query'}
          </button>
        ))}
      </nav>

      {/* Content — fills remaining viewport */}
      <div style={{ flex: 1, overflow: 'hidden', padding: contentPadding, minHeight: 0 }}>

        {/* HOME */}
        {page === 'home' && (
          <div style={{ overflow: 'auto', height: '100%' }}>
            <h2 style={{ fontSize: 18, fontWeight: 600, margin: '0 0 16px' }}>Usage Statistics</h2>
            {usage ? (
              <>
                <div style={{ display: 'flex', gap: 12, marginBottom: 20, flexWrap: 'wrap' }}>
                  <StatCard label="Total Tokens" value={fmtNum(usage.totals.total_tokens)} />
                  <StatCard label="Input Tokens" value={fmtNum(usage.totals.input_tokens)} />
                  <StatCard label="Output Tokens" value={fmtNum(usage.totals.output_tokens)} />
                  <StatCard label="Sessions" value={String(usage.sessions.length)} />
                </div>
                <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))' }}>
                  {usage.sessions.map(s => (
                    <div key={s.key} style={cardStyle}>
                      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 6, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {s.label}
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '3px 12px', fontSize: 12, color: '#555' }}>
                        <span>Total</span><span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtNum(s.total_tokens)}</span>
                        <span>Input</span><span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtNum(s.input_tokens)}</span>
                        <span>Output</span><span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtNum(s.output_tokens)}</span>
                        <span>Model</span><span style={{ textAlign: 'right' }}>{s.model || '—'}</span>
                        <span>Updated</span><span style={{ textAlign: 'right' }}>{fmtDate(s.updated_at)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            ) : <p style={{ color: '#888' }}>Loading…</p>}
          </div>
        )}

        {/* DATA EXPLORER — full height */}
        {page === 'explorer' && (
          <div style={{ display: 'flex', gap: 16, height: '100%', minHeight: 0 }}>
            {/* Sidebar */}
            <div style={{ width: 200, flexShrink: 0, overflowY: 'auto', paddingRight: 4 }}>
              <div style={{ fontSize: 11, fontWeight: 600, color: '#888', textTransform: 'uppercase', marginBottom: 6, letterSpacing: '0.04em' }}>Tables</div>
              {tables.map(t => (
                <button key={t.name} onClick={() => setSelected(t.name)}
                  style={{ ...sideBtn, ...(selected === t.name ? { background: '#e8e8e8', fontWeight: 600 } : {}) }}>
                  <span>{t.name}</span>
                  <span style={{ fontSize: 10, color: '#999' }}>{fmtNum(t.row_count)}</span>
                </button>
              ))}
            </div>
            {/* Table area — flex column fills height */}
            <div style={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
              {selected ? (
                <>
                  <h2 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 8px', flexShrink: 0 }}>{selected}</h2>
                  <DataTable tableName={selected} />
                </>
              ) : (
                <div style={{ color: '#888', padding: 40, textAlign: 'center' }}>Select a table</div>
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

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ ...cardStyle, minWidth: 120, flex: '1 1 0' }}>
      <div style={{ fontSize: 11, color: '#888', marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )
}

/* ── Styles ── */

const cardStyle: React.CSSProperties = {
  background: '#fff', border: '1px solid #e0e0e0', borderRadius: 8, padding: 14,
}

const navBtn: React.CSSProperties = {
  background: 'none', border: 'none', borderBottom: '2px solid transparent',
  padding: '12px 14px', cursor: 'pointer', fontSize: 13, color: '#666', fontFamily: 'inherit',
}

const sideBtn: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%',
  padding: '6px 8px', background: 'transparent', border: 'none', cursor: 'pointer',
  borderRadius: 5, fontSize: 12, fontFamily: 'inherit', textAlign: 'left',
}

const btnStyle: React.CSSProperties = {
  padding: '6px 16px', background: '#fff', border: '1px solid #ddd', borderRadius: 6,
  cursor: 'pointer', fontSize: 13, fontFamily: 'inherit',
}

const chipBtn: React.CSSProperties = {
  padding: '4px 10px', background: '#f0f0f0', border: '1px solid #ddd', borderRadius: 4,
  cursor: 'pointer', fontSize: 11, fontFamily: 'inherit', color: '#555',
}

const selectStyle: React.CSSProperties = {
  fontSize: 12, padding: '4px 6px', border: '1px solid #ddd', borderRadius: 4,
  fontFamily: 'inherit', background: '#fff',
}

const inputStyle: React.CSSProperties = {
  fontSize: 12, padding: '4px 8px', border: '1px solid #ddd', borderRadius: 4,
  fontFamily: 'inherit', boxSizing: 'border-box' as const,
}

const tabBtn: React.CSSProperties = {
  padding: '8px 16px', border: '1px solid #ddd', background: '#fff',
  cursor: 'pointer', fontSize: 13, fontFamily: 'inherit', color: '#666',
}

const tabBtnActive: React.CSSProperties = {
  background: '#1a1a1a', color: '#fff', borderColor: '#1a1a1a',
}

const thStyle: React.CSSProperties = {
  padding: '7px 10px', textAlign: 'left', borderBottom: '2px solid #e0e0e0',
  fontSize: 11, fontWeight: 600, color: '#555', background: '#fafafa',
  whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
}

const tdStyle: React.CSSProperties = {
  padding: '5px 10px', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis',
  whiteSpace: 'nowrap', fontSize: 12,
}
