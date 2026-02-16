import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  flexRender,
  type ColumnDef,
} from '@tanstack/react-table'

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

type Page = 'home' | 'explorer' | 'sql'
type SortDir = 'asc' | 'desc' | null
type FilterValue = string | { min?: string; max?: string }

const NUMERIC_TYPES = new Set(['integer', 'bigint', 'smallint', 'numeric', 'real', 'double precision'])
const DATE_TYPES = new Set(['date', 'timestamp without time zone', 'timestamp with time zone'])

function isNumericType(dt: string) { return NUMERIC_TYPES.has(dt) }
function isDateType(dt: string) { return DATE_TYPES.has(dt) }

/* ── Helpers ── */

function fmtNum(n: number): string { return n.toLocaleString() }

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/* ── Data Table with Server-Side Sort/Filter ── */

function DataTable({ tableName }: { tableName: string }) {
  const [data, setData] = useState<Record<string, unknown>[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [schema, setSchema] = useState<SchemaColumn[]>([])
  const [total, setTotal] = useState(0)
  const [filteredTotal, setFilteredTotal] = useState(0)
  const [pageIndex, setPageIndex] = useState(0)
  const [sortBy, setSortBy] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>(null)
  const [filters, setFilters] = useState<Record<string, FilterValue>>({})
  const [groupBy, setGroupBy] = useState<string | null>(null)
  const [groupData, setGroupData] = useState<GroupRow[]>([])
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set())
  const pageSize = 100
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Fetch schema once per table
  useEffect(() => {
    fetch(`${API}/tables/${tableName}/schema`).then(r => r.json()).then(d => setSchema(d.columns))
  }, [tableName])

  const typeMap = useMemo(() => {
    const m: Record<string, string> = {}
    for (const c of schema) m[c.column_name] = c.data_type
    return m
  }, [schema])

  // Reset state when table changes
  useEffect(() => {
    setPageIndex(0)
    setSortBy(null)
    setSortDir(null)
    setFilters({})
    setGroupBy(null)
    setGroupData([])
    setExpandedGroups(new Set())
  }, [tableName])

  // Build fetch URL
  const buildUrl = useCallback((page: number) => {
    const params = new URLSearchParams({
      limit: String(pageSize),
      offset: String(page * pageSize),
    })
    if (sortBy && sortDir) {
      params.set('sort_by', sortBy)
      params.set('sort_dir', sortDir)
    }
    // Build filters for API: text → string, range → {min, max}
    const apiFilters: Record<string, unknown> = {}
    let hasFilters = false
    for (const [col, val] of Object.entries(filters)) {
      if (typeof val === 'string' && val.trim()) {
        apiFilters[col] = val.trim()
        hasFilters = true
      } else if (typeof val === 'object') {
        const range: Record<string, number> = {}
        if (val.min?.trim()) { range.min = Number(val.min); hasFilters = true }
        if (val.max?.trim()) { range.max = Number(val.max); hasFilters = true }
        if (Object.keys(range).length) apiFilters[col] = range
      }
    }
    if (hasFilters) params.set('filters', JSON.stringify(apiFilters))
    return `${API}/tables/${tableName}/data?${params}`
  }, [tableName, sortBy, sortDir, filters])

  // Load data
  const loadPage = useCallback((page: number) => {
    fetch(buildUrl(page))
      .then(r => r.json())
      .then(d => {
        setData(d.rows)
        setColumns(d.columns)
        setTotal(d.total)
        setFilteredTotal(d.filtered_total)
        setPageIndex(page)
      })
  }, [buildUrl])

  // Reload on sort/filter change (debounced for filters)
  useEffect(() => { loadPage(0) }, [sortBy, sortDir, tableName])

  // Debounced reload on filter change
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => loadPage(0), 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [filters])

  // Load group data
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

  function updateFilter(col: string, val: FilterValue) {
    setFilters(prev => ({ ...prev, [col]: val }))
  }

  function sortIndicator(col: string) {
    if (sortBy !== col) return ' \u2195'
    return sortDir === 'asc' ? ' \u2191' : ' \u2193'
  }

  function toggleGroup(v: string) {
    setExpandedGroups(prev => {
      const next = new Set(prev)
      next.has(v) ? next.delete(v) : next.add(v)
      return next
    })
  }

  // TanStack columns
  const colDefs: ColumnDef<Record<string, unknown>, unknown>[] = useMemo(
    () => columns.map(c => ({
      accessorKey: c,
      header: c,
      cell: (info: { getValue: () => unknown }) => String(info.getValue() ?? ''),
    })),
    [columns]
  )

  const table = useReactTable({
    data,
    columns: colDefs,
    getCoreRowModel: getCoreRowModel(),
    manualPagination: true,
    manualSorting: true,
    manualFiltering: true,
    pageCount: Math.ceil(filteredTotal / pageSize),
  })

  const totalPages = Math.ceil(filteredTotal / pageSize)
  const start = filteredTotal > 0 ? pageIndex * pageSize + 1 : 0
  const end = Math.min((pageIndex + 1) * pageSize, filteredTotal)

  return (
    <div>
      {/* Toolbar: counts + group-by */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 12, flexWrap: 'wrap' }}>
        <span style={{ fontSize: 13, color: '#666' }}>
          {filteredTotal < total
            ? `${fmtNum(filteredTotal)} of ${fmtNum(total)} rows (filtered)`
            : `${fmtNum(total)} rows`}
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8 }}>
          <label style={{ fontSize: 12, color: '#888' }}>Group By:</label>
          <select
            value={groupBy ?? ''}
            onChange={e => setGroupBy(e.target.value || null)}
            style={{ fontSize: 12, padding: '4px 8px', border: '1px solid #ddd', borderRadius: 4, fontFamily: 'inherit' }}
          >
            <option value="">None</option>
            {columns.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
      </div>

      {/* Group-by view */}
      {groupBy && groupData.length > 0 && (
        <div style={{ marginBottom: 16, border: '1px solid #e0e0e0', borderRadius: 8, overflow: 'hidden' }}>
          {groupData.map(g => {
            const key = String(g.value ?? 'NULL')
            const isOpen = expandedGroups.has(key)
            return (
              <div key={key}>
                <button
                  onClick={() => toggleGroup(key)}
                  style={{
                    width: '100%', padding: '10px 14px', background: '#fafafa',
                    border: 'none', borderBottom: '1px solid #e0e0e0', cursor: 'pointer',
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    fontFamily: 'inherit', fontSize: 13,
                  }}
                >
                  <span><strong>{groupBy}:</strong> {key}</span>
                  <span style={{ color: '#888' }}>
                    {fmtNum(g.count)} rows {isOpen ? '\u25B2' : '\u25BC'}
                  </span>
                </button>
                {isOpen && (
                  <div style={{ padding: '8px 14px', fontSize: 12, color: '#666', background: '#fff' }}>
                    {fmtNum(g.count)} rows where {groupBy} = {key}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Data table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            {/* Column headers (sortable) */}
            <tr>
              {table.getHeaderGroups()[0]?.headers.map(h => {
                const col = h.column.id
                const dt = typeMap[col] ?? ''
                return (
                  <th key={h.id} style={{ ...thStyle, cursor: 'pointer', userSelect: 'none' }}
                    onClick={() => handleSort(col)}>
                    {flexRender(h.column.columnDef.header, h.getContext())}
                    <span style={{ fontSize: 10, marginLeft: 4, color: '#999' }}>{sortIndicator(col)}</span>
                    <div style={{ fontSize: 10, fontWeight: 400, color: '#aaa' }}>{dt}</div>
                  </th>
                )
              })}
            </tr>
            {/* Filter row */}
            <tr>
              {table.getHeaderGroups()[0]?.headers.map(h => {
                const col = h.column.id
                const dt = typeMap[col] ?? ''
                if (isNumericType(dt)) {
                  const val = (filters[col] ?? { min: '', max: '' }) as { min?: string; max?: string }
                  return (
                    <th key={h.id + '-filter'} style={{ ...thStyle, padding: '4px 6px' }}>
                      <div style={{ display: 'flex', gap: 4 }}>
                        <input type="number" placeholder="Min" value={val.min ?? ''}
                          onChange={e => updateFilter(col, { ...val, min: e.target.value })}
                          style={{ ...filterInput, width: '50%' }} />
                        <input type="number" placeholder="Max" value={val.max ?? ''}
                          onChange={e => updateFilter(col, { ...val, max: e.target.value })}
                          style={{ ...filterInput, width: '50%' }} />
                      </div>
                    </th>
                  )
                }
                if (isDateType(dt)) {
                  const val = (filters[col] ?? { min: '', max: '' }) as { min?: string; max?: string }
                  return (
                    <th key={h.id + '-filter'} style={{ ...thStyle, padding: '4px 6px' }}>
                      <div style={{ display: 'flex', gap: 4 }}>
                        <input type="date" placeholder="From" value={val.min ?? ''}
                          onChange={e => updateFilter(col, { ...val, min: e.target.value })}
                          style={{ ...filterInput, width: '50%' }} />
                        <input type="date" placeholder="To" value={val.max ?? ''}
                          onChange={e => updateFilter(col, { ...val, max: e.target.value })}
                          style={{ ...filterInput, width: '50%' }} />
                      </div>
                    </th>
                  )
                }
                return (
                  <th key={h.id + '-filter'} style={{ ...thStyle, padding: '4px 8px' }}>
                    <input type="text" placeholder="Filter..."
                      value={(filters[col] as string) ?? ''}
                      onChange={e => updateFilter(col, e.target.value)}
                      style={filterInput} />
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {table.getRowModel().rows.map(row => (
              <tr key={row.id} style={{ borderBottom: '1px solid #eee' }}>
                {row.getVisibleCells().map(cell => (
                  <td key={cell.id} style={tdStyle}>
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '12px 0' }}>
        <button style={btnStyle} disabled={pageIndex === 0} onClick={() => loadPage(pageIndex - 1)}>Prev</button>
        <span style={{ fontSize: 13, color: '#666' }}>
          {filteredTotal > 0 ? `${fmtNum(start)}\u2013${fmtNum(end)} of ${fmtNum(filteredTotal)}` : 'No rows'}
        </span>
        <button style={btnStyle} disabled={pageIndex + 1 >= totalPages} onClick={() => loadPage(pageIndex + 1)}>Next</button>
      </div>
    </div>
  )
}

/* ── Main App ── */

export default function App() {
  const [page, setPage] = useState<Page>('home')
  const [tables, setTables] = useState<TableInfo[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [usage, setUsage] = useState<UsageData | null>(null)

  // SQL state
  const [sql, setSql] = useState('')
  const [queryResult, setQueryResult] = useState<{ columns: string[]; rows: Record<string, unknown>[]; error?: string } | null>(null)

  useEffect(() => { fetch(`${API}/tables`).then(r => r.json()).then(setTables) }, [])
  useEffect(() => { fetch(`${API}/usage`).then(r => r.json()).then(setUsage) }, [])

  function runQuery() {
    fetch(`${API}/query`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sql }) })
      .then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.detail); return d })
      .then(d => setQueryResult({ columns: d.columns, rows: d.rows }))
      .catch(e => setQueryResult({ columns: [], rows: [], error: e.message }))
  }

  return (
    <div style={{ fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif', color: '#1a1a1a', minHeight: '100vh', background: '#f8f9fa' }}>
      {/* Nav bar */}
      <nav style={{ background: '#fff', borderBottom: '1px solid #e0e0e0', padding: '0 24px', display: 'flex', alignItems: 'center', height: 52 }}>
        <span style={{ fontWeight: 700, fontSize: 16, marginRight: 32 }}>NHC Admin</span>
        {(['home', 'explorer', 'sql'] as Page[]).map(p => (
          <button key={p} onClick={() => setPage(p)}
            style={{ ...navBtn, ...(page === p ? { color: '#1a1a1a', borderBottom: '2px solid #1a1a1a' } : {}) }}>
            {p === 'home' ? 'Home' : p === 'explorer' ? 'Data Explorer' : 'SQL Query'}
          </button>
        ))}
      </nav>

      <div style={{ maxWidth: 1200, margin: '0 auto', padding: '24px 16px' }}>
        {/* HOME PAGE */}
        {page === 'home' && (
          <div>
            <h2 style={{ fontSize: 20, fontWeight: 600, margin: '0 0 20px' }}>Usage Statistics</h2>
            {usage && (
              <>
                {/* Totals */}
                <div style={{ display: 'flex', gap: 16, marginBottom: 24, flexWrap: 'wrap' }}>
                  <StatCard label="Total Tokens" value={fmtNum(usage.totals.total_tokens)} />
                  <StatCard label="Input Tokens" value={fmtNum(usage.totals.input_tokens)} />
                  <StatCard label="Output Tokens" value={fmtNum(usage.totals.output_tokens)} />
                  <StatCard label="Sessions" value={String(usage.sessions.length)} />
                </div>
                {/* Session list */}
                <div style={{ display: 'grid', gap: 12, gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))' }}>
                  {usage.sessions.map(s => (
                    <div key={s.key} style={cardStyle}>
                      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 8, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                        {s.label}
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '4px 16px', fontSize: 13, color: '#555' }}>
                        <span>Total tokens</span><span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtNum(s.total_tokens)}</span>
                        <span>Input</span><span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtNum(s.input_tokens)}</span>
                        <span>Output</span><span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtNum(s.output_tokens)}</span>
                        <span>Context window</span><span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>{fmtNum(s.context_window)}</span>
                        <span>Model</span><span style={{ textAlign: 'right' }}>{s.model || '—'}</span>
                        <span>Updated</span><span style={{ textAlign: 'right' }}>{fmtDate(s.updated_at)}</span>
                      </div>
                    </div>
                  ))}
                </div>
              </>
            )}
            {!usage && <p style={{ color: '#888' }}>Loading...</p>}
          </div>
        )}

        {/* DATA EXPLORER */}
        {page === 'explorer' && (
          <div style={{ display: 'flex', gap: 24 }}>
            {/* Sidebar */}
            <div style={{ width: 220, flexShrink: 0 }}>
              <div style={{ fontSize: 12, fontWeight: 600, color: '#888', textTransform: 'uppercase', marginBottom: 8, letterSpacing: '0.04em' }}>Tables</div>
              {tables.map(t => (
                <button key={t.name} onClick={() => setSelected(t.name)}
                  style={{ ...sideBtn, ...(selected === t.name ? { background: '#e8e8e8', fontWeight: 600 } : {}) }}>
                  <span>{t.name}</span>
                  <span style={{ fontSize: 11, color: '#999' }}>{t.row_count.toLocaleString()}</span>
                </button>
              ))}
            </div>
            {/* Table content */}
            <div style={{ flex: 1, minWidth: 0 }}>
              {selected ? (
                <>
                  <h2 style={{ fontSize: 18, fontWeight: 600, margin: '0 0 12px' }}>{selected}</h2>
                  <DataTable tableName={selected} />
                </>
              ) : (
                <div style={{ color: '#888', padding: 40, textAlign: 'center' }}>Select a table to explore</div>
              )}
            </div>
          </div>
        )}

        {/* SQL QUERY */}
        {page === 'sql' && (
          <div>
            <h2 style={{ fontSize: 20, fontWeight: 600, margin: '0 0 16px' }}>SQL Query</h2>
            <textarea
              style={{ width: '100%', height: 120, padding: 12, fontSize: 13, fontFamily: 'monospace', border: '1px solid #ddd', borderRadius: 6, resize: 'vertical', boxSizing: 'border-box' }}
              value={sql} onChange={e => setSql(e.target.value)}
              placeholder="SELECT * FROM teams LIMIT 10"
            />
            <div style={{ margin: '12px 0' }}>
              <button style={{ ...btnStyle, background: '#1a1a1a', color: '#fff' }} onClick={runQuery}>Run Query</button>
            </div>
            {queryResult && (queryResult.error
              ? <div style={{ padding: 12, background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 6, color: '#dc2626', fontSize: 13 }}>{queryResult.error}</div>
              : <>
                <div style={{ overflowX: 'auto' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead><tr>{queryResult.columns.map(c => <th key={c} style={thStyle}>{c}</th>)}</tr></thead>
                    <tbody>{queryResult.rows.map((r, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid #eee' }}>
                        {queryResult.columns.map(c => <td key={c} style={tdStyle}>{String(r[c] ?? '')}</td>)}
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
                <div style={{ fontSize: 13, color: '#666', marginTop: 8 }}>{queryResult.rows.length} rows returned</div>
              </>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Small components ── */

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ ...cardStyle, minWidth: 140, flex: '1 1 0' }}>
      <div style={{ fontSize: 12, color: '#888', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )
}

/* ── Shared styles ── */

const cardStyle: React.CSSProperties = {
  background: '#fff', border: '1px solid #e0e0e0', borderRadius: 8, padding: 16,
}

const navBtn: React.CSSProperties = {
  background: 'none', border: 'none', borderBottom: '2px solid transparent',
  padding: '14px 16px', cursor: 'pointer', fontSize: 14, color: '#666', fontFamily: 'inherit',
}

const sideBtn: React.CSSProperties = {
  display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%',
  padding: '8px 10px', background: 'transparent', border: 'none', cursor: 'pointer',
  borderRadius: 6, fontSize: 13, fontFamily: 'inherit', textAlign: 'left',
}

const btnStyle: React.CSSProperties = {
  padding: '6px 16px', background: '#fff', border: '1px solid #ddd', borderRadius: 6,
  cursor: 'pointer', fontSize: 13, fontFamily: 'inherit',
}

const thStyle: React.CSSProperties = {
  padding: '8px 12px', textAlign: 'left', borderBottom: '2px solid #e0e0e0',
  fontSize: 12, fontWeight: 600, color: '#555', background: '#fafafa',
}

const tdStyle: React.CSSProperties = {
  padding: '6px 12px', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
}

const filterInput: React.CSSProperties = {
  width: '100%', padding: '4px 6px', fontSize: 12, border: '1px solid #ddd', borderRadius: 4,
  fontFamily: 'inherit', boxSizing: 'border-box',
}
