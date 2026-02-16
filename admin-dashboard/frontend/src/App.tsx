import React, { useEffect, useState } from 'react'

const API = '/api'

interface TableInfo { name: string; row_count: number }
interface ColInfo { column_name: string; data_type: string; is_nullable: string }

/* ── Apple Liquid Glass Design System ── */

const glassPanel = {
  background: 'rgba(255, 255, 255, 0.08)',
  backdropFilter: 'blur(40px) saturate(180%)',
  WebkitBackdropFilter: 'blur(40px) saturate(180%)',
  border: '1px solid rgba(255, 255, 255, 0.12)',
  borderRadius: 16,
} as React.CSSProperties

const glassPanelHover = {
  background: 'rgba(255, 255, 255, 0.12)',
  border: '1px solid rgba(255, 255, 255, 0.18)',
}

const styles: Record<string, React.CSSProperties> = {
  /* Root */
  app: {
    display: 'flex',
    height: '100vh',
    background: 'linear-gradient(135deg, #0a0a1a 0%, #111128 30%, #1a1040 60%, #0d1b2a 100%)',
    color: 'rgba(255, 255, 255, 0.9)',
    fontFamily: '-apple-system, BlinkMacSystemFont, "SF Pro Display", "SF Pro Text", "Helvetica Neue", system-ui, sans-serif',
    letterSpacing: '-0.01em',
  },

  /* Sidebar */
  sidebar: {
    width: 260,
    padding: 20,
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    borderRight: '1px solid rgba(255, 255, 255, 0.06)',
  },
  sidebarTitle: {
    fontSize: 13,
    fontWeight: 600,
    color: 'rgba(255, 255, 255, 0.45)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.06em',
    padding: '0 12px',
    marginBottom: 8,
    marginTop: 4,
  },
  tableBtn: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    width: '100%',
    padding: '10px 14px',
    background: 'transparent',
    color: 'rgba(255, 255, 255, 0.75)',
    border: '1px solid transparent',
    cursor: 'pointer',
    textAlign: 'left' as const,
    borderRadius: 12,
    fontSize: 13,
    fontWeight: 500,
    fontFamily: 'inherit',
    transition: 'all 0.2s ease',
    letterSpacing: '-0.01em',
  },
  tableBtnActive: {
    ...glassPanel,
    color: 'rgba(255, 255, 255, 0.95)',
    boxShadow: '0 2px 12px rgba(0, 0, 0, 0.2), inset 0 1px 0 rgba(255, 255, 255, 0.08)',
  },
  badge: {
    fontSize: 11,
    fontWeight: 500,
    color: 'rgba(255, 255, 255, 0.3)',
    fontVariantNumeric: 'tabular-nums',
  },

  /* Main content */
  main: {
    flex: 1,
    padding: 32,
    overflowY: 'auto',
    display: 'flex',
    flexDirection: 'column',
    gap: 20,
  },

  /* Tabs */
  tabBar: {
    display: 'inline-flex',
    gap: 2,
    padding: 3,
    ...glassPanel,
    borderRadius: 12,
    width: 'fit-content',
  },
  tab: {
    padding: '8px 18px',
    background: 'transparent',
    color: 'rgba(255, 255, 255, 0.55)',
    border: 'none',
    cursor: 'pointer',
    borderRadius: 10,
    fontSize: 13,
    fontWeight: 500,
    fontFamily: 'inherit',
    transition: 'all 0.2s ease',
    letterSpacing: '-0.01em',
  },
  tabActive: {
    background: 'rgba(255, 255, 255, 0.12)',
    color: 'rgba(255, 255, 255, 0.95)',
    boxShadow: '0 1px 4px rgba(0, 0, 0, 0.15)',
  },

  /* Header */
  header: {
    display: 'flex',
    alignItems: 'baseline',
    gap: 12,
  },
  h2: {
    margin: 0,
    fontSize: 22,
    fontWeight: 600,
    color: 'rgba(255, 255, 255, 0.95)',
    letterSpacing: '-0.02em',
  },
  headerBadge: {
    fontSize: 13,
    fontWeight: 500,
    color: 'rgba(255, 255, 255, 0.35)',
  },

  /* Table */
  tableCard: {
    ...glassPanel,
    overflow: 'hidden',
  },
  table: {
    width: '100%',
    borderCollapse: 'collapse' as const,
    fontSize: 13,
  },
  th: {
    background: 'rgba(255, 255, 255, 0.04)',
    padding: '10px 16px',
    textAlign: 'left' as const,
    borderBottom: '1px solid rgba(255, 255, 255, 0.06)',
    color: 'rgba(255, 255, 255, 0.5)',
    fontWeight: 600,
    fontSize: 11,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.05em',
  },
  td: {
    padding: '9px 16px',
    borderBottom: '1px solid rgba(255, 255, 255, 0.04)',
    maxWidth: 220,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap' as const,
    color: 'rgba(255, 255, 255, 0.75)',
    fontVariantNumeric: 'tabular-nums',
  },

  /* Pagination */
  pagination: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '12px 16px',
    borderTop: '1px solid rgba(255, 255, 255, 0.06)',
    background: 'rgba(255, 255, 255, 0.02)',
  },
  paginationText: {
    fontSize: 12,
    color: 'rgba(255, 255, 255, 0.4)',
    fontVariantNumeric: 'tabular-nums',
  },

  /* Buttons */
  btn: {
    padding: '7px 16px',
    background: 'rgba(255, 255, 255, 0.08)',
    color: 'rgba(255, 255, 255, 0.8)',
    border: '1px solid rgba(255, 255, 255, 0.1)',
    borderRadius: 10,
    cursor: 'pointer',
    fontSize: 12,
    fontWeight: 500,
    fontFamily: 'inherit',
    transition: 'all 0.2s ease',
    backdropFilter: 'blur(20px)',
    WebkitBackdropFilter: 'blur(20px)',
  },
  btnPrimary: {
    background: 'rgba(88, 130, 255, 0.25)',
    border: '1px solid rgba(88, 130, 255, 0.3)',
    color: 'rgba(160, 190, 255, 0.95)',
  },

  /* SQL area */
  textarea: {
    width: '100%',
    height: 120,
    background: 'rgba(0, 0, 0, 0.25)',
    color: 'rgba(255, 255, 255, 0.85)',
    border: '1px solid rgba(255, 255, 255, 0.1)',
    borderRadius: 12,
    padding: 16,
    fontFamily: '"SF Mono", "Fira Code", "JetBrains Mono", monospace',
    fontSize: 13,
    lineHeight: 1.5,
    resize: 'vertical' as const,
    outline: 'none',
    transition: 'border-color 0.2s ease',
    boxSizing: 'border-box' as const,
  },

  /* Empty state */
  emptyState: {
    display: 'flex',
    flexDirection: 'column' as const,
    alignItems: 'center',
    justifyContent: 'center',
    flex: 1,
    gap: 12,
    opacity: 0.4,
  },
  emptyIcon: {
    fontSize: 48,
    marginBottom: 8,
  },
  emptyText: {
    fontSize: 16,
    fontWeight: 500,
    letterSpacing: '-0.01em',
  },
  emptySubtext: {
    fontSize: 13,
    color: 'rgba(255, 255, 255, 0.5)',
  },

  /* Error */
  error: {
    padding: '12px 16px',
    background: 'rgba(255, 69, 58, 0.12)',
    border: '1px solid rgba(255, 69, 58, 0.2)',
    borderRadius: 12,
    color: 'rgba(255, 120, 115, 0.95)',
    fontSize: 13,
  },

  /* Logo area */
  logo: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '8px 12px',
    marginBottom: 16,
  },
  logoText: {
    fontSize: 16,
    fontWeight: 700,
    letterSpacing: '-0.03em',
    color: 'rgba(255, 255, 255, 0.9)',
  },
  logoSub: {
    fontSize: 11,
    color: 'rgba(255, 255, 255, 0.3)',
    fontWeight: 500,
  },
}

/* ── Global CSS injection for scrollbar + hover + focus ── */
const globalCSS = `
  ::-webkit-scrollbar { width: 6px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 3px; }
  ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.18); }
  * { box-sizing: border-box; }
  body { margin: 0; overflow: hidden; }
  button:hover { filter: brightness(1.15); }
  button:active { transform: scale(0.98); }
  textarea:focus { border-color: rgba(88, 130, 255, 0.4) !important; }
  tr:hover td { background: rgba(255,255,255,0.03); }
  ::selection { background: rgba(88, 130, 255, 0.35); }
`

export default function App() {
  const [tables, setTables] = useState<TableInfo[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [schema, setSchema] = useState<ColInfo[]>([])
  const [rows, setRows] = useState<Record<string, unknown>[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [tab, setTab] = useState<'data' | 'schema' | 'query'>('data')
  const [sql, setSql] = useState('')
  const [queryResult, setQueryResult] = useState<{ columns: string[]; rows: Record<string, unknown>[]; error?: string } | null>(null)
  const limit = 100

  useEffect(() => { fetch(`${API}/tables`).then(r => r.json()).then(setTables) }, [])

  useEffect(() => {
    if (!selected) return
    setOffset(0)
    fetch(`${API}/tables/${selected}/schema`).then(r => r.json()).then(d => setSchema(d.columns))
    loadData(selected, 0)
  }, [selected])

  function loadData(name: string, off: number) {
    fetch(`${API}/tables/${name}/data?limit=${limit}&offset=${off}`)
      .then(r => r.json())
      .then(d => { setRows(d.rows); setColumns(d.columns); setTotal(d.total); setOffset(off) })
  }

  function runQuery() {
    fetch(`${API}/query`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sql }) })
      .then(async r => { const d = await r.json(); if (!r.ok) throw new Error(d.detail); return d })
      .then(d => setQueryResult({ columns: d.columns, rows: d.rows }))
      .catch(e => setQueryResult({ columns: [], rows: [], error: e.message }))
  }

  const renderTable = (cols: string[], data: Record<string, unknown>[]) => (
    <div style={styles.tableCard}>
      <table style={styles.table}>
        <thead><tr>{cols.map(c => <th key={c} style={styles.th}>{c}</th>)}</tr></thead>
        <tbody>{data.map((r, i) => <tr key={i}>{cols.map(c => <td key={c} style={styles.td}>{String(r[c] ?? '')}</td>)}</tr>)}</tbody>
      </table>
    </div>
  )

  return (
    <>
      <style>{globalCSS}</style>
      <div style={styles.app}>
        {/* Sidebar */}
        <div style={styles.sidebar}>
          <div style={styles.logo}>
            <div>
              <div style={styles.logoText}>⚡ NHC</div>
              <div style={styles.logoSub}>Admin Dashboard</div>
            </div>
          </div>
          <div style={styles.sidebarTitle}>Tables</div>
          {tables.map(t => (
            <button key={t.name} onClick={() => { setSelected(t.name); setTab('data') }}
              style={{ ...styles.tableBtn, ...(selected === t.name ? styles.tableBtnActive : {}) }}>
              <span>{t.name}</span>
              <span style={styles.badge}>{t.row_count.toLocaleString()}</span>
            </button>
          ))}
        </div>

        {/* Main */}
        <div style={styles.main}>
          {!selected ? (
            <div style={styles.emptyState}>
              <div style={styles.emptyIcon}>📊</div>
              <div style={styles.emptyText}>Select a table to explore</div>
              <div style={styles.emptySubtext}>Browse schema, data, or run SQL queries</div>
            </div>
          ) : <>
            {/* Tab bar */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div style={styles.tabBar}>
                {(['data', 'schema', 'query'] as const).map(t => (
                  <button key={t} onClick={() => setTab(t)}
                    style={{ ...styles.tab, ...(tab === t ? styles.tabActive : {}) }}>
                    {t === 'data' ? '📋 Data' : t === 'schema' ? '🧬 Schema' : '⚡ SQL'}
                  </button>
                ))}
              </div>
            </div>

            {/* Header */}
            <div style={styles.header}>
              <h2 style={styles.h2}>{selected}</h2>
              <span style={styles.headerBadge}>{total.toLocaleString()} rows</span>
            </div>

            {/* Data tab */}
            {tab === 'data' && <>
              {renderTable(columns, rows)}
              <div style={{ ...styles.tableCard, ...styles.pagination }}>
                <button style={styles.btn} disabled={offset === 0}
                  onClick={() => loadData(selected, Math.max(0, offset - limit))}>← Prev</button>
                <span style={styles.paginationText}>
                  {offset + 1}–{Math.min(offset + limit, total)} of {total.toLocaleString()}
                </span>
                <button style={styles.btn} disabled={offset + limit >= total}
                  onClick={() => loadData(selected, offset + limit)}>Next →</button>
              </div>
            </>}

            {/* Schema tab */}
            {tab === 'schema' && renderTable(
              ['column_name', 'data_type', 'is_nullable', 'column_default'],
              schema as unknown as Record<string, unknown>[]
            )}

            {/* Query tab */}
            {tab === 'query' && <>
              <textarea style={styles.textarea} value={sql} onChange={e => setSql(e.target.value)}
                placeholder="SELECT * FROM teams LIMIT 10" />
              <div>
                <button style={{ ...styles.btn, ...styles.btnPrimary }} onClick={runQuery}>▶ Run Query</button>
              </div>
              {queryResult && (queryResult.error
                ? <div style={styles.error}>⚠ {queryResult.error}</div>
                : <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                    {renderTable(queryResult.columns, queryResult.rows)}
                    <span style={styles.paginationText}>{queryResult.rows.length} rows returned</span>
                  </div>
              )}
            </>}
          </>}
        </div>
      </div>
    </>
  )
}
