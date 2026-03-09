import { useState, useEffect, useMemo } from 'react'
import { cn } from '@/lib/utils'
import {
  BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, Legend,
} from 'recharts'
import { type TableInfo, type SchemaColumn, type Measure, type ActiveFilter, API, fmtNum, fmtCompact, isDateType } from './types'
import { GroupByConfig, MeasuresConfig, HavingConfig } from './aggregation-config'
import { FilterPanel } from './column-filter'
import { ResultsGrid } from './data-grid'

const CHART_COLORS = [
  'hsl(var(--primary))', 'hsl(var(--chart-2, 160 60% 45%))',
  'hsl(var(--chart-3, 30 80% 55%))', 'hsl(var(--chart-4, 280 65% 60%))',
  'hsl(var(--chart-5, 340 75% 55%))',
]

type ChartType = 'bar' | 'line' | 'none'

function buildAnalyticsQuery(config: {
  table: string; groupBy: string[]; measures: Measure[]
  filters: ActiveFilter[]; having: { measure: string; operator: string; value: string }[]
  sortBy: string | null; sortDir: string; limit: number
}): string {
  const { table, groupBy, measures, filters, having, sortBy, sortDir, limit } = config

  if (measures.length === 0) return ''

  const selectParts = [
    ...groupBy.map(g => `"${g}"`),
    ...measures.map(m => {
      if (m.fn === 'COUNT_DISTINCT') return `COUNT(DISTINCT "${m.column}") AS "${m.label}"`
      return `${m.fn}("${m.column}") AS "${m.label}"`
    }),
  ]

  let sql = `SELECT ${selectParts.join(', ')} FROM "${table}"`

  // WHERE
  const whereConditions: string[] = []
  for (const f of filters) {
    if (!f.value.trim()) continue
    const col = `"${f.column}"`
    const val = f.value.replace(/'/g, "''")
    switch (f.operator) {
      case 'contains': whereConditions.push(`${col} ILIKE '%${val}%'`); break
      case 'equals': whereConditions.push(`${col} = '${val}'`); break
      case 'starts_with': whereConditions.push(`${col} ILIKE '${val}%'`); break
      case 'ends_with': whereConditions.push(`${col} ILIKE '%${val}'`); break
      case 'eq': whereConditions.push(`${col} = ${val}`); break
      case 'ne': whereConditions.push(`${col} != ${val}`); break
      case 'gt': whereConditions.push(`${col} > ${val}`); break
      case 'lt': whereConditions.push(`${col} < ${val}`); break
      case 'gte': whereConditions.push(`${col} >= ${val}`); break
      case 'lte': whereConditions.push(`${col} <= ${val}`); break
      case 'before': whereConditions.push(`${col} < '${val}'`); break
      case 'after': whereConditions.push(`${col} > '${val}'`); break
      case 'between': {
        const v2 = (f.value2 ?? f.value).replace(/'/g, "''")
        whereConditions.push(`${col} BETWEEN '${val}' AND '${v2}'`)
        break
      }
    }
  }
  if (whereConditions.length > 0) sql += ` WHERE ${whereConditions.join(' AND ')}`

  // GROUP BY
  if (groupBy.length > 0) sql += ` GROUP BY ${groupBy.map(g => `"${g}"`).join(', ')}`

  // HAVING
  const havingOps: Record<string, string> = { gt: '>', lt: '<', gte: '>=', lte: '<=', eq: '=' }
  const havingConds = having.filter(h => h.value.trim()).map(h => `"${h.measure}" ${havingOps[h.operator] || '>'} ${h.value}`)
  if (havingConds.length > 0) sql += ` HAVING ${havingConds.join(' AND ')}`

  // ORDER BY
  if (sortBy) sql += ` ORDER BY "${sortBy}" ${sortDir}`
  else if (measures.length > 0) sql += ` ORDER BY "${measures[0].label}" DESC`

  // LIMIT
  sql += ` LIMIT ${limit}`

  return sql
}

function detectChartType(groupBy: string[], measures: Measure[], schema: SchemaColumn[]): ChartType {
  if (groupBy.length === 0 || measures.length === 0) return 'none'
  const groupCol = schema.find(s => s.column_name === groupBy[0])
  if (groupCol && isDateType(groupCol.data_type)) return 'line'
  return 'bar'
}

/* ── Chart ── */

function AnalyticsChart({ data, groupBy, measures, chartType, onChartTypeChange }: {
  data: Record<string, unknown>[]
  groupBy: string[]
  measures: Measure[]
  chartType: ChartType
  onChartTypeChange: (t: ChartType) => void
}) {
  if (data.length === 0 || chartType === 'none') return null
  const xKey = groupBy[0] || ''

  return (
    <div className="border border-border rounded-lg bg-card p-4">
      <div className="flex items-center gap-2 mb-3">
        <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Chart</span>
        <div className="flex gap-0.5">
          {(['bar', 'line'] as const).map(t => (
            <button key={t} onClick={() => onChartTypeChange(t)}
              className={cn(
                'px-2.5 py-1 rounded text-[11px] cursor-pointer border',
                chartType === t ? 'bg-primary/10 text-primary border-primary/25' : 'bg-muted text-muted-foreground border-border',
              )}>
              {t === 'bar' ? 'Bar' : 'Line'}
            </button>
          ))}
        </div>
      </div>
      <ResponsiveContainer width="100%" height={300}>
        {chartType === 'line' ? (
          <LineChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} />
            <YAxis tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} />
            <Tooltip contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }} />
            <Legend />
            {measures.map((m, i) => (
              <Line key={m.label} type="monotone" dataKey={m.label}
                stroke={CHART_COLORS[i % CHART_COLORS.length]} strokeWidth={2} dot={false} />
            ))}
          </LineChart>
        ) : (
          <BarChart data={data}>
            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
            <XAxis dataKey={xKey} tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} angle={-30} textAnchor="end" height={60} />
            <YAxis tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} />
            <Tooltip contentStyle={{ background: 'hsl(var(--card))', border: '1px solid hsl(var(--border))', borderRadius: 8, fontSize: 12 }} />
            <Legend />
            {measures.map((m, i) => (
              <Bar key={m.label} dataKey={m.label} fill={CHART_COLORS[i % CHART_COLORS.length]} radius={[4, 4, 0, 0]} />
            ))}
          </BarChart>
        )}
      </ResponsiveContainer>
    </div>
  )
}

/* ── Analytics Builder ── */

export function AnalyticsBuilder({ tables, mobile }: {
  tables: TableInfo[]
  mobile?: boolean
}) {
  const [selectedTable, setSelectedTable] = useState<string | null>(null)
  const [schema, setSchema] = useState<SchemaColumn[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [groupBy, setGroupBy] = useState<string[]>([])
  const [measures, setMeasures] = useState<Measure[]>([])
  const [filters, setFilters] = useState<ActiveFilter[]>([])
  const [having, setHaving] = useState<{ measure: string; operator: string; value: string }[]>([])
  const [sortBy, setSortBy] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [limit, setLimit] = useState(100)
  const [result, setResult] = useState<{ columns: string[]; rows: Record<string, unknown>[] } | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [showSql, setShowSql] = useState(false)
  const [chartType, setChartType] = useState<ChartType>('bar')
  const [tableSearch, setTableSearch] = useState('')
  const [showFilters, setShowFilters] = useState(false)

  useEffect(() => {
    if (!selectedTable) { setSchema([]); setColumns([]); return }
    fetch(`${API}/tables/${selectedTable}/schema`)
      .then(r => r.json())
      .then(d => {
        const cols = (d.columns || []) as SchemaColumn[]
        setSchema(cols)
        setColumns(cols.map(c => c.column_name))
      })
      .catch(() => { setSchema([]); setColumns([]) })
    // Reset config
    setGroupBy([]); setMeasures([]); setFilters([]); setHaving([])
    setSortBy(null); setResult(null); setError(null)
  }, [selectedTable])

  const sql = useMemo(() => {
    if (!selectedTable || measures.length === 0) return ''
    return buildAnalyticsQuery({
      table: selectedTable, groupBy, measures, filters, having, sortBy, sortDir, limit,
    })
  }, [selectedTable, groupBy, measures, filters, having, sortBy, sortDir, limit])

  const detectedChartType = useMemo(
    () => detectChartType(groupBy, measures, schema),
    [groupBy, measures, schema],
  )
  useEffect(() => { setChartType(detectedChartType === 'none' ? 'bar' : detectedChartType) }, [detectedChartType])

  async function runQuery() {
    if (!sql) return
    setLoading(true); setError(null)
    try {
      const r = await fetch(`${API}/query`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sql }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || 'Query failed')
      setResult({ columns: d.columns, rows: d.rows })
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error')
      setResult(null)
    } finally { setLoading(false) }
  }

  const filteredTables = tables.filter(t =>
    !tableSearch.trim() || t.name.toLowerCase().includes(tableSearch.toLowerCase()),
  )

  // Sort options: group by cols + measure labels
  const sortOptions = [...groupBy, ...measures.map(m => m.label)]

  return (
    <div className="flex flex-col h-full gap-4 overflow-auto">
      {/* Step 1: Pick table */}
      <div className="border border-border rounded-lg bg-card p-4">
        <div className="flex items-center gap-2 mb-2">
          <span className={cn(
            'w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shrink-0',
            selectedTable ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground border border-border',
          )}>1</span>
          <span className="text-sm font-semibold text-foreground">Select Table</span>
          {selectedTable && <span className="text-xs text-primary font-mono ml-2">{selectedTable}</span>}
        </div>
        {!selectedTable ? (
          <div>
            <input type="text" value={tableSearch} onChange={e => setTableSearch(e.target.value)}
              placeholder="Search tables…"
              className="w-full rounded-md border border-border bg-muted px-3 py-2 text-sm text-foreground font-sans outline-none mb-2 max-w-[300px]" />
            <div className="flex flex-wrap gap-1.5 max-h-[200px] overflow-y-auto">
              {filteredTables.map(t => (
                <button key={t.name} onClick={() => setSelectedTable(t.name)}
                  className="px-2.5 py-1.5 rounded-md border border-border bg-muted text-xs font-mono text-foreground cursor-pointer hover:bg-primary/10 hover:text-primary hover:border-primary/25">
                  {t.name} <span className="text-muted-foreground">({fmtCompact(t.row_count)})</span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <button onClick={() => setSelectedTable(null)}
            className="px-2.5 py-1 bg-muted border border-border rounded-md text-[11px] text-muted-foreground cursor-pointer hover:text-foreground">
            Change table
          </button>
        )}
      </div>

      {/* Step 2: Configure */}
      {selectedTable && columns.length > 0 && (
        <div className={cn('border rounded-lg bg-card p-4', measures.length > 0 ? 'border-primary/25' : 'border-border')}>
          <div className="flex items-center gap-2 mb-3">
            <span className={cn(
              'w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shrink-0',
              measures.length > 0 ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground border border-border',
            )}>2</span>
            <span className="text-sm font-semibold text-foreground">Configure Aggregation</span>
          </div>
          <div className="flex flex-col gap-4">
            <GroupByConfig columns={columns} selected={groupBy} onChange={setGroupBy} />
            <MeasuresConfig columns={columns} schema={schema} measures={measures} onChange={setMeasures} />

            <button onClick={() => setShowFilters(!showFilters)}
              className="self-start px-2.5 py-1 bg-muted border border-border rounded-md text-[11px] text-muted-foreground font-medium cursor-pointer hover:text-foreground">
              {showFilters ? 'Hide' : 'Show'} Filters
            </button>
            {showFilters && (
              <FilterPanel columns={columns} schema={schema} filters={filters}
                onChange={setFilters} tableName={selectedTable} />
            )}

            <HavingConfig measures={measures} having={having} onChange={setHaving} />

            <div className="flex items-center gap-3 flex-wrap">
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] text-muted-foreground">Sort:</span>
                <select value={sortBy ?? ''} onChange={e => setSortBy(e.target.value || null)}
                  className="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground font-sans outline-none">
                  <option value="">Auto</option>
                  {sortOptions.map(c => <option key={c} value={c}>{c}</option>)}
                </select>
                <select value={sortDir} onChange={e => setSortDir(e.target.value as 'asc' | 'desc')}
                  className="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground font-sans outline-none w-[70px]">
                  <option value="desc">DESC</option>
                  <option value="asc">ASC</option>
                </select>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-[11px] text-muted-foreground">Limit:</span>
                <input type="number" value={limit} onChange={e => setLimit(Number(e.target.value) || 100)}
                  className="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground font-sans outline-none w-[80px]" />
              </div>
            </div>

            {/* SQL preview */}
            {sql && (
              <div>
                <button onClick={() => setShowSql(!showSql)}
                  className="text-[11px] text-muted-foreground cursor-pointer bg-transparent border-none font-sans hover:text-foreground mb-1">
                  {showSql ? '▾ Hide' : '▸ Show'} SQL
                </button>
                {showSql && (
                  <pre className="p-3 bg-muted rounded-lg text-xs font-mono text-foreground whitespace-pre-wrap break-all border border-border">
                    {sql}
                  </pre>
                )}
              </div>
            )}

            <button onClick={runQuery} disabled={!sql || loading}
              className={cn(
                'px-5 py-2.5 bg-primary text-primary-foreground rounded-md text-sm font-semibold cursor-pointer self-start disabled:opacity-50',
                loading && 'cursor-wait',
              )}>
              {loading ? 'Running…' : 'Run Analysis'}
            </button>
          </div>
        </div>
      )}

      {/* Step 3+4: Results + Chart */}
      {error && (
        <div className="p-3.5 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive text-[13px]">
          {error}
        </div>
      )}
      {result && (
        <>
          <div className="border border-border rounded-lg bg-card p-4">
            <div className="flex items-center gap-2 mb-3">
              <span className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold bg-primary text-primary-foreground shrink-0">3</span>
              <span className="text-sm font-semibold text-foreground">Results</span>
              <span className="text-xs text-muted-foreground">{result.rows.length} rows</span>
            </div>
            <div className="h-[400px]">
              <ResultsGrid columns={result.columns} rows={result.rows} mobile={mobile} />
            </div>
          </div>

          {groupBy.length > 0 && measures.length > 0 && result.rows.length > 0 && (
            <div>
              <div className="flex items-center gap-2 mb-2">
                <span className="w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold bg-primary text-primary-foreground shrink-0">4</span>
                <span className="text-sm font-semibold text-foreground">Visualize</span>
              </div>
              <AnalyticsChart data={result.rows} groupBy={groupBy} measures={measures}
                chartType={chartType} onChartTypeChange={setChartType} />
            </div>
          )}
        </>
      )}
    </div>
  )
}
