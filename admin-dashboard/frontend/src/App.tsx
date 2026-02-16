import React, { useEffect, useMemo, useState } from 'react'
import {
  useReactTable,
  getCoreRowModel,
  getFilteredRowModel,
  flexRender,
  type ColumnDef,
  type ColumnFiltersState,
} from '@tanstack/react-table'

const API = '/api'

/* ── Types ── */

interface TableInfo { name: string; row_count: number }
interface SessionInfo {
  key: string; label: string; total_tokens: number; input_tokens: number
  output_tokens: number; context_window: number; model: string; updated_at: string | null
}
interface UsageData { sessions: SessionInfo[]; totals: { total_tokens: number; input_tokens: number; output_tokens: number } }

type Page = 'home' | 'explorer' | 'sql'

/* ── Helpers ── */

function fmtNum(n: number): string {
  return n.toLocaleString()
}

function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

/* ── Data Table with TanStack ── */

function DataTable({ tableName }: { tableName: string }) {
  const [data, setData] = useState<Record<string, unknown>[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [total, setTotal] = useState(0)
  const [pageIndex, setPageIndex] = useState(0)
  const [columnFilters, setColumnFilters] = useState<ColumnFiltersState>([])
  const pageSize = 100

  useEffect(() => {
    setPageIndex(0)
    setColumnFilters([])
    loadPage(0)
  }, [tableName])

  function loadPage(page: number) {
    fetch(`${API}/tables/${tableName}/data?limit=${pageSize}&offset=${page * pageSize}`)
      .then(r => r.json())
      .then(d => { setData(d.rows); setColumns(d.columns); setTotal(d.total); setPageIndex(page) })
  }

  const colDefs: ColumnDef<Record<string, unknown>, unknown>[] = useMemo(
    () => columns.map(c => ({
      accessorKey: c,
      header: c,
      cell: (info: { getValue: () => unknown }) => String(info.getValue() ?? ''),
      filterFn: 'includesString' as const,
    })),
    [columns]
  )

  const table = useReactTable({
    data,
    columns: colDefs,
    state: { columnFilters },
    onColumnFiltersChange: setColumnFilters,
    getCoreRowModel: getCoreRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    manualPagination: true,
    pageCount: Math.ceil(total / pageSize),
  })

  const totalPages = Math.ceil(total / pageSize)
  const start = pageIndex * pageSize + 1
  const end = Math.min((pageIndex + 1) * pageSize, total)

  return (
    <div>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
          <thead>
            <tr>
              {table.getHeaderGroups()[0]?.headers.map(h => (
                <th key={h.id} style={thStyle}>
                  {flexRender(h.column.columnDef.header, h.getContext())}
                </th>
              ))}
            </tr>
            <tr>
              {table.getHeaderGroups()[0]?.headers.map(h => (
                <th key={h.id + '-filter'} style={{ ...thStyle, padding: '4px 8px' }}>
                  <input
                    type="text"
                    placeholder="Filter..."
                    value={(h.column.getFilterValue() as string) ?? ''}
                    onChange={e => h.column.setFilterValue(e.target.value)}
                    style={filterInput}
                  />
                </th>
              ))}
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
          {total > 0 ? `${fmtNum(start)}–${fmtNum(end)} of ${fmtNum(total)}` : 'No rows'}
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
