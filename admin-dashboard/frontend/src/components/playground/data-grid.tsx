import { useMemo, useRef, useCallback, useState, useEffect } from 'react'
import {
  useReactTable, getCoreRowModel, flexRender,
  type ColumnDef, type VisibilityState, type RowSelectionState,
} from '@tanstack/react-table'
import { useVirtualizer } from '@tanstack/react-virtual'
import { cn } from '@/lib/utils'
import {
  type SchemaColumn, type SortDir, type ActiveFilter,
  isNumericType, isDateType, formatCellValue, fmtNum, API, buildFilterParam,
} from './types'
import { FilterPanel } from './column-filter'
import { ExportButton } from './export-button'

const PAGE_SIZES = [25, 50, 100, 250] as const

interface DataGridProps {
  tableName: string
  schema: SchemaColumn[]
  mobile?: boolean
}

export function DataGrid({ tableName, schema, mobile }: DataGridProps) {
  const [data, setData] = useState<Record<string, unknown>[]>([])
  const [columns, setColumns] = useState<string[]>([])
  const [total, setTotal] = useState(0)
  const [filteredTotal, setFilteredTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [pageSize, setPageSize] = useState<number>(50)
  const [sortBy, setSortBy] = useState<string | null>(null)
  const [sortDir, setSortDir] = useState<SortDir>(null)
  const [filters, setFilters] = useState<ActiveFilter[]>([])
  const [loading, setLoading] = useState(false)
  const [showFilters, setShowFilters] = useState(false)
  const [columnVisibility, setColumnVisibility] = useState<VisibilityState>({})
  const [rowSelection, setRowSelection] = useState<RowSelectionState>({})
  const [showColumnPicker, setShowColumnPicker] = useState(false)
  const [frozenCols, setFrozenCols] = useState(0)

  const containerRef = useRef<HTMLDivElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const typeMap = useMemo(() => {
    const m: Record<string, string> = {}
    for (const c of schema) m[c.column_name] = c.data_type
    return m
  }, [schema])

  // Reset state when table changes
  useEffect(() => {
    setData([]); setColumns([]); setPage(0); setSortBy(null); setSortDir(null)
    setFilters([]); setShowFilters(false); setColumnVisibility({}); setRowSelection({})
    setFrozenCols(0)
  }, [tableName])

  const fetchData = useCallback(async () => {
    if (abortRef.current) abortRef.current.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setLoading(true)
    try {
      const params = new URLSearchParams({
        limit: String(pageSize),
        offset: String(page * pageSize),
      })
      if (sortBy && sortDir) { params.set('sort_by', sortBy); params.set('sort_dir', sortDir) }
      const fp = buildFilterParam(filters, typeMap)
      if (fp) params.set('filters', fp)
      const r = await fetch(`${API}/tables/${tableName}/data?${params}`, { signal: controller.signal })
      const d = await r.json()
      setData(d.rows); setColumns(d.columns); setTotal(d.total); setFilteredTotal(d.filtered_total)
    } catch (e) {
      if (e instanceof DOMException && e.name === 'AbortError') return
    } finally { setLoading(false) }
  }, [tableName, page, pageSize, sortBy, sortDir, filters, typeMap])

  // Fetch on param changes (debounce filters)
  const filterKey = JSON.stringify(filters.map(f => ({ c: f.column, o: f.operator, v: f.value, v2: f.value2 })))
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => fetchData(), 300)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [fetchData, filterKey])

  function handleSort(col: string) {
    setPage(0)
    if (sortBy !== col) { setSortBy(col); setSortDir('asc') }
    else if (sortDir === 'asc') setSortDir('desc')
    else { setSortBy(null); setSortDir(null) }
  }

  function handleFilterChange(newFilters: ActiveFilter[]) {
    setPage(0); setFilters(newFilters)
  }

  const totalPages = Math.max(1, Math.ceil(filteredTotal / pageSize))
  const activeFilterCount = filters.filter(f => f.value.trim()).length
  const selectedCount = Object.keys(rowSelection).length

  const colDefs = useMemo<ColumnDef<Record<string, unknown>>[]>(() => {
    const selectCol: ColumnDef<Record<string, unknown>> = {
      id: '_select',
      header: ({ table: t }) => (
        <input type="checkbox" checked={t.getIsAllPageRowsSelected()}
          onChange={t.getToggleAllPageRowsSelectedHandler()}
          className="accent-primary" />
      ),
      cell: ({ row }) => (
        <input type="checkbox" checked={row.getIsSelected()}
          onChange={row.getToggleSelectedHandler()}
          className="accent-primary" />
      ),
      size: 40,
      enableSorting: false,
    }

    const dataCols: ColumnDef<Record<string, unknown>>[] = columns.map((c, idx) => ({
      accessorKey: c,
      header: c,
      size: 160,
      cell: (info: { getValue: () => unknown }) => {
        const v = info.getValue()
        if (v === null || v === undefined) return <span className="text-muted-foreground italic">null</span>
        if (typeof v === 'boolean') return <span className={v ? 'text-green-500' : 'text-destructive'}>{String(v)}</span>
        const dt = typeMap[c]
        const formatted = formatCellValue(v, dt)
        const isLong = formatted.length > 60
        return (
          <span title={isLong ? formatted : undefined}
            className={cn(isNumericType(dt || '') && 'tabular-nums text-right')}>
            {isLong ? formatted.slice(0, 60) + '…' : formatted}
          </span>
        )
      },
      meta: { frozen: idx < frozenCols },
    }))

    return [selectCol, ...dataCols]
  }, [columns, typeMap, frozenCols])

  const table = useReactTable({
    data,
    columns: colDefs,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualFiltering: true,
    manualPagination: true,
    pageCount: totalPages,
    state: { columnVisibility, rowSelection },
    onColumnVisibilityChange: setColumnVisibility,
    onRowSelectionChange: setRowSelection,
    enableRowSelection: true,
  })

  const { rows: tableRows } = table.getRowModel()
  const rowVirtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => containerRef.current,
    estimateSize: () => 36,
    overscan: 15,
  })

  return (
    <div className="flex flex-col h-full gap-2">
      {/* Toolbar */}
      <div className="flex items-center gap-2 flex-wrap shrink-0">
        <button onClick={() => setShowFilters(!showFilters)}
          className={cn(
            'px-2.5 py-1.5 border rounded-md text-[11px] font-medium cursor-pointer font-sans',
            showFilters ? 'bg-primary/10 border-primary/25 text-primary' : 'bg-muted border-border text-muted-foreground',
          )}>
          Filters{activeFilterCount > 0 && <span className="ml-1 bg-primary text-primary-foreground rounded-full px-1.5 text-[10px] font-bold">{activeFilterCount}</span>}
        </button>

        <div className="relative">
          <button onClick={() => setShowColumnPicker(!showColumnPicker)}
            className="px-2.5 py-1.5 bg-muted border border-border rounded-md text-[11px] text-muted-foreground font-medium cursor-pointer font-sans hover:text-foreground">
            Columns
          </button>
          {showColumnPicker && (
            <div className="absolute top-full left-0 mt-1 z-30 bg-card border border-border rounded-lg shadow-xl p-3 max-h-[300px] overflow-y-auto min-w-[200px]">
              <div className="flex gap-1.5 mb-2">
                <button onClick={() => setColumnVisibility({})}
                  className="px-2 py-1 bg-muted border border-border rounded text-[10px] font-medium cursor-pointer">Show All</button>
                <button onClick={() => { const v: VisibilityState = {}; columns.slice(5).forEach(c => v[c] = false); setColumnVisibility(v) }}
                  className="px-2 py-1 bg-muted border border-border rounded text-[10px] font-medium cursor-pointer">First 5</button>
              </div>
              {columns.map(c => {
                const visible = columnVisibility[c] !== false
                return (
                  <label key={c} className="flex items-center gap-2 py-1 cursor-pointer text-xs">
                    <input type="checkbox" checked={visible}
                      onChange={() => setColumnVisibility(prev => ({ ...prev, [c]: !visible }))}
                      className="accent-primary" />
                    <span className={cn('font-mono', !visible && 'text-muted-foreground')}>{c}</span>
                  </label>
                )
              })}
            </div>
          )}
        </div>

        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground">Freeze:</span>
          <select value={frozenCols} onChange={e => setFrozenCols(Number(e.target.value))}
            className="rounded-md border border-border bg-muted px-2 py-1 text-[11px] text-foreground font-sans outline-none">
            {[0, 1, 2, 3].map(n => <option key={n} value={n}>{n} col{n !== 1 ? 's' : ''}</option>)}
          </select>
        </div>

        <ExportButton tableName={tableName} columns={columns} rows={data}
          filters={filters} typeMap={typeMap} sortBy={sortBy} sortDir={sortDir} />

        <div className="flex-1" />

        {selectedCount > 0 && (
          <span className="text-[11px] text-primary font-medium">{selectedCount} selected</span>
        )}
      </div>

      {/* Active filters summary */}
      {activeFilterCount > 0 && !showFilters && (
        <div className="flex items-center gap-1.5 flex-wrap">
          {filters.filter(f => f.value.trim()).map(f => (
            <span key={f.id} className="inline-flex items-center gap-1 px-2 py-0.5 bg-primary/10 text-primary border border-primary/20 rounded-full text-[10px]">
              {f.column} {f.operator} {f.value}{f.value2 ? `–${f.value2}` : ''}
              <button onClick={() => setFilters(filters.filter(x => x.id !== f.id))}
                className="bg-transparent border-none cursor-pointer text-primary/60 hover:text-primary leading-none text-xs">×</button>
            </span>
          ))}
        </div>
      )}

      {showFilters && (
        <FilterPanel columns={columns} schema={schema} filters={filters}
          onChange={handleFilterChange} tableName={tableName} />
      )}

      {/* Info bar */}
      <div className="text-[11px] text-muted-foreground flex gap-3 items-center flex-wrap shrink-0">
        <span className="tabular-nums">
          {filteredTotal < total
            ? <><strong className="text-foreground">{fmtNum(filteredTotal)}</strong> of {fmtNum(total)} rows</>
            : <><strong className="text-foreground">{fmtNum(total)}</strong> rows</>}
        </span>
        <span>Page {page + 1} of {totalPages}</span>
        {loading && <span className="text-primary">Loading…</span>}
      </div>

      {/* Table */}
      <div ref={containerRef}
        className="flex-1 overflow-auto border border-border rounded-lg bg-card min-h-0">
        <table style={{ minWidth: columns.length * 160 + 40 }} className="border-collapse text-xs w-full">
          <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur-sm">
            <tr className="border-b border-border">
              {table.getHeaderGroups()[0]?.headers.map(h => {
                const isFrozen = h.column.columnDef.meta && (h.column.columnDef.meta as { frozen?: boolean }).frozen
                const isSelect = h.column.id === '_select'
                return (
                  <th key={h.id}
                    onClick={() => !isSelect && handleSort(h.column.id)}
                    className={cn(
                      'px-3 py-2 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground whitespace-nowrap',
                      !isSelect && 'cursor-pointer hover:text-foreground transition-colors',
                      isFrozen && 'sticky left-0 z-20 bg-muted',
                      isSelect && 'w-10',
                    )}
                    style={{ width: h.column.getSize() }}>
                    <span>{flexRender(h.column.columnDef.header, h.getContext())}</span>
                    {!isSelect && (
                      <span className={cn('text-[10px] ml-1', sortBy === h.column.id ? 'text-primary' : 'text-muted-foreground/30')}>
                        {sortBy === h.column.id ? (sortDir === 'asc' ? '↑' : '↓') : '↕'}
                      </span>
                    )}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody>
            {rowVirtualizer.getVirtualItems().length > 0 && (
              <tr><td style={{ height: rowVirtualizer.getVirtualItems()[0]?.start ?? 0, padding: 0 }} colSpan={colDefs.length} /></tr>
            )}
            {rowVirtualizer.getVirtualItems().map(vr => {
              const row = tableRows[vr.index]
              return (
                <tr key={row.id} className="border-b border-border/50 hover:bg-muted/30 transition-colors h-9">
                  {row.getVisibleCells().map(cell => {
                    const isFrozen = cell.column.columnDef.meta && (cell.column.columnDef.meta as { frozen?: boolean }).frozen
                    return (
                      <td key={cell.id}
                        className={cn(
                          'px-3 py-1.5 text-sm text-foreground font-mono tabular-nums max-w-[260px] overflow-hidden text-ellipsis whitespace-nowrap',
                          isFrozen && 'sticky left-0 z-[1] bg-card',
                        )}>
                        {flexRender(cell.column.columnDef.cell, cell.getContext())}
                      </td>
                    )
                  })}
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
              }} colSpan={colDefs.length} /></tr>
            )}
          </tbody>
        </table>
        {data.length === 0 && !loading && (
          <div className="p-10 text-center text-muted-foreground">No data</div>
        )}
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between gap-2 shrink-0 pt-1">
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-muted-foreground">Rows:</span>
          <select value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setPage(0) }}
            className="rounded-md border border-border bg-muted px-2 py-1 text-[11px] text-foreground font-sans outline-none">
            {PAGE_SIZES.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>

        <div className="flex items-center gap-1">
          <button onClick={() => setPage(0)} disabled={page === 0}
            className="px-2 py-1 bg-muted border border-border rounded text-[11px] font-medium cursor-pointer disabled:opacity-30">
            ««
          </button>
          <button onClick={() => setPage(p => Math.max(0, p - 1))} disabled={page === 0}
            className="px-2 py-1 bg-muted border border-border rounded text-[11px] font-medium cursor-pointer disabled:opacity-30">
            ‹
          </button>
          <span className="px-3 text-[11px] text-foreground tabular-nums">
            {page + 1} / {totalPages}
          </span>
          <button onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))} disabled={page >= totalPages - 1}
            className="px-2 py-1 bg-muted border border-border rounded text-[11px] font-medium cursor-pointer disabled:opacity-30">
            ›
          </button>
          <button onClick={() => setPage(totalPages - 1)} disabled={page >= totalPages - 1}
            className="px-2 py-1 bg-muted border border-border rounded text-[11px] font-medium cursor-pointer disabled:opacity-30">
            »»
          </button>
        </div>
      </div>
    </div>
  )
}

/* ── Simple results grid for query results (no pagination, no server-side) ── */

export function ResultsGrid({ columns, rows, mobile }: {
  columns: string[]
  rows: Record<string, unknown>[]
  mobile?: boolean
}) {
  const containerRef = useRef<HTMLDivElement>(null)

  const colDefs = useMemo<ColumnDef<Record<string, unknown>>[]>(() =>
    columns.map(c => ({
      accessorKey: c,
      header: c,
      size: 160,
      cell: (info: { getValue: () => unknown }) => {
        const v = info.getValue()
        if (v === null || v === undefined) return <span className="text-muted-foreground italic">null</span>
        if (typeof v === 'number') return <span className="tabular-nums">{v.toLocaleString()}</span>
        return String(v)
      },
    })),
  [columns])

  const table = useReactTable({
    data: rows, columns: colDefs, getCoreRowModel: getCoreRowModel(),
  })

  const { rows: tableRows } = table.getRowModel()
  const rowVirtualizer = useVirtualizer({
    count: tableRows.length,
    getScrollElement: () => containerRef.current,
    estimateSize: () => 36,
    overscan: 15,
  })

  return (
    <div ref={containerRef} className="flex-1 overflow-auto border border-border rounded-lg bg-card min-h-0">
      <table style={{ minWidth: columns.length * 160 }} className="border-collapse text-xs w-full">
        <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur-sm">
          <tr className="border-b border-border">
            {table.getHeaderGroups()[0]?.headers.map(h => (
              <th key={h.id}
                className="px-3 py-2 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground whitespace-nowrap">
                {flexRender(h.column.columnDef.header, h.getContext())}
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
              <tr key={row.id} className="border-b border-border/50 hover:bg-muted/30 transition-colors h-9">
                {row.getVisibleCells().map(cell => (
                  <td key={cell.id} className="px-3 py-1.5 text-sm text-foreground max-w-[260px] overflow-hidden text-ellipsis whitespace-nowrap">
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
      {rows.length === 0 && <div className="p-10 text-center text-muted-foreground">No results</div>}
      <div className="text-[11px] text-muted-foreground px-3 py-2 border-t border-border">{rows.length} rows</div>
    </div>
  )
}
