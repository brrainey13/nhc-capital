import React, { useEffect, useState } from 'react'

const API = '/api'

interface TableInfo { name: string; row_count: number }
interface ColInfo { column_name: string; data_type: string; is_nullable: string }

const styles: Record<string, React.CSSProperties> = {
  app: { display: 'flex', height: '100vh', background: '#1a1a2e', color: '#e0e0e0', fontFamily: 'monospace' },
  sidebar: { width: 240, background: '#16213e', padding: 16, overflowY: 'auto', borderRight: '1px solid #0f3460' },
  main: { flex: 1, padding: 24, overflowY: 'auto' },
  tableBtn: { display: 'block', width: '100%', padding: '8px 12px', marginBottom: 4, background: 'transparent', color: '#e0e0e0', border: 'none', cursor: 'pointer', textAlign: 'left', borderRadius: 4, fontSize: 13 },
  tableBtnActive: { background: '#0f3460' },
  table: { width: '100%', borderCollapse: 'collapse', fontSize: 13 },
  th: { background: '#0f3460', padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid #1a1a2e' },
  td: { padding: '6px 12px', borderBottom: '1px solid #16213e', maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  btn: { padding: '6px 16px', background: '#0f3460', color: '#e0e0e0', border: 'none', borderRadius: 4, cursor: 'pointer', marginRight: 8 },
  textarea: { width: '100%', height: 100, background: '#16213e', color: '#e0e0e0', border: '1px solid #0f3460', borderRadius: 4, padding: 12, fontFamily: 'monospace', fontSize: 13, marginBottom: 8 },
  h2: { margin: '0 0 16px', color: '#e94560' },
  badge: { fontSize: 11, color: '#888', marginLeft: 8 },
}

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
    <table style={styles.table}>
      <thead><tr>{cols.map(c => <th key={c} style={styles.th}>{c}</th>)}</tr></thead>
      <tbody>{data.map((r, i) => <tr key={i}>{cols.map(c => <td key={c} style={styles.td}>{String(r[c] ?? '')}</td>)}</tr>)}</tbody>
    </table>
  )

  return (
    <div style={styles.app}>
      <div style={styles.sidebar}>
        <h3 style={{ color: '#e94560', marginTop: 0 }}>📊 Tables</h3>
        {tables.map(t => (
          <button key={t.name} onClick={() => { setSelected(t.name); setTab('data') }}
            style={{ ...styles.tableBtn, ...(selected === t.name ? styles.tableBtnActive : {}) }}>
            {t.name}<span style={styles.badge}>{t.row_count}</span>
          </button>
        ))}
      </div>
      <div style={styles.main}>
        {!selected ? <h2 style={styles.h2}>Select a table to explore</h2> : <>
          <div style={{ marginBottom: 16 }}>
            <button style={{ ...styles.btn, ...(tab === 'data' ? { background: '#e94560' } : {}) }} onClick={() => setTab('data')}>Data</button>
            <button style={{ ...styles.btn, ...(tab === 'schema' ? { background: '#e94560' } : {}) }} onClick={() => setTab('schema')}>Schema</button>
            <button style={{ ...styles.btn, ...(tab === 'query' ? { background: '#e94560' } : {}) }} onClick={() => setTab('query')}>SQL Query</button>
          </div>
          <h2 style={styles.h2}>{selected} <span style={{ fontSize: 14, color: '#888' }}>({total} rows)</span></h2>

          {tab === 'data' && <>
            {renderTable(columns, rows)}
            <div style={{ marginTop: 12 }}>
              <button style={styles.btn} disabled={offset === 0} onClick={() => loadData(selected, Math.max(0, offset - limit))}>← Prev</button>
              <span style={{ margin: '0 12px' }}>{offset + 1}–{Math.min(offset + limit, total)} of {total}</span>
              <button style={styles.btn} disabled={offset + limit >= total} onClick={() => loadData(selected, offset + limit)}>Next →</button>
            </div>
          </>}

          {tab === 'schema' && renderTable(['column_name', 'data_type', 'is_nullable', 'column_default'], schema as unknown as Record<string, unknown>[])}

          {tab === 'query' && <>
            <textarea style={styles.textarea} value={sql} onChange={e => setSql(e.target.value)} placeholder="SELECT * FROM teams LIMIT 10" />
            <button style={styles.btn} onClick={runQuery}>Run Query</button>
            {queryResult && (queryResult.error
              ? <p style={{ color: '#e94560' }}>Error: {queryResult.error}</p>
              : <div style={{ marginTop: 12 }}>{renderTable(queryResult.columns, queryResult.rows)}<p>{queryResult.rows.length} rows</p></div>
            )}
          </>}
        </>}
      </div>
    </div>
  )
}
