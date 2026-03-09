import { useState, useEffect, useRef } from 'react'
import { cn } from '@/lib/utils'
import {
  type SchemaColumn, type ActiveFilter,
  isNumericType, isDateType, operatorsForType, nextFilterId, API,
} from './types'

/* ── Distinct value fetcher for combo-box suggestions ── */

function useDistinctValues(tableName: string, column: string, query: string, open: boolean) {
  const [options, setOptions] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (!open) return
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setLoading(true)
      const params = new URLSearchParams({ column, limit: '50' })
      if (query.trim()) params.set('q', query)
      fetch(`${API}/tables/${tableName}/distinct?${params}`)
        .then(r => r.ok ? r.json() : [])
        .then(data => setOptions((data as unknown[]).map(v => String(v ?? 'NULL'))))
        .catch(() => setOptions([]))
        .finally(() => setLoading(false))
    }, 200)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [open, query, column, tableName])

  return { options, loading }
}

/* ── Single filter row ── */

function FilterRow({ filter, columns, typeMap, tableName, onUpdate, onRemove }: {
  filter: ActiveFilter
  columns: string[]
  typeMap: Record<string, string>
  tableName: string
  onUpdate: (patch: Partial<ActiveFilter>) => void
  onRemove: () => void
}) {
  const dt = typeMap[filter.column] || ''
  const ops = operatorsForType(dt)
  const isBetween = filter.operator === 'between'
  const inputType = isNumericType(dt) ? 'number' : isDateType(dt) ? 'date' : 'text'

  const [open, setOpen] = useState(false)
  const { options, loading } = useDistinctValues(tableName, filter.column, filter.value, open && inputType === 'text')
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      <select value={filter.column}
        onChange={e => {
          const newDt = typeMap[e.target.value] || ''
          onUpdate({
            column: e.target.value,
            operator: operatorsForType(newDt)[0].value,
            value: '', value2: undefined,
          })
        }}
        className="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground font-sans outline-none max-w-[160px]">
        {columns.map(c => <option key={c} value={c}>{c}</option>)}
      </select>

      <select value={filter.operator} onChange={e => onUpdate({ operator: e.target.value })}
        className="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground font-sans outline-none w-[90px]">
        {ops.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
      </select>

      <div ref={ref} className="relative">
        <input type={inputType} value={filter.value}
          placeholder={isBetween ? 'Min' : 'Value'}
          onFocus={() => inputType === 'text' && setOpen(true)}
          onChange={e => { onUpdate({ value: e.target.value }); if (inputType === 'text') setOpen(true) }}
          className={cn('rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground font-sans outline-none', isBetween ? 'w-[90px]' : 'w-[140px]')} />
        {open && inputType === 'text' && (
          <div className="absolute top-full left-0 right-0 mt-0.5 z-30 bg-card border border-border rounded-md shadow-xl overflow-y-auto max-h-[180px]">
            {loading && <div className="px-3 py-2 text-[11px] text-muted-foreground">Loading…</div>}
            {!loading && options.length === 0 && <div className="px-3 py-2 text-[11px] text-muted-foreground">No values</div>}
            {options.map((opt, i) => (
              <button key={i} onClick={() => { onUpdate({ value: opt }); setOpen(false) }}
                className="w-full px-3 py-1.5 bg-transparent border-none text-xs text-foreground text-left cursor-pointer font-sans hover:bg-muted">
                {opt}
              </button>
            ))}
          </div>
        )}
      </div>

      {isBetween && (
        <>
          <span className="text-xs text-muted-foreground">to</span>
          <input type={inputType} value={filter.value2 ?? ''} placeholder="Max"
            onChange={e => onUpdate({ value2: e.target.value })}
            className="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground font-sans outline-none w-[90px]" />
        </>
      )}

      <button onClick={onRemove}
        className="bg-transparent border-none cursor-pointer text-muted-foreground hover:text-destructive text-sm px-1 leading-none">
        ×
      </button>
    </div>
  )
}

/* ── Filter Panel ── */

export function FilterPanel({ columns, schema, filters, onChange, tableName }: {
  columns: string[]
  schema: SchemaColumn[]
  filters: ActiveFilter[]
  onChange: (filters: ActiveFilter[]) => void
  tableName: string
}) {
  const typeMap: Record<string, string> = {}
  for (const c of schema) typeMap[c.column_name] = c.data_type

  function addFilter() {
    const col = columns[0] || ''
    const dt = typeMap[col] || ''
    onChange([...filters, { id: nextFilterId(), column: col, operator: operatorsForType(dt)[0].value, value: '' }])
  }

  function updateFilter(id: string, patch: Partial<ActiveFilter>) {
    onChange(filters.map(f => f.id === id ? { ...f, ...patch } : f))
  }

  function removeFilter(id: string) {
    onChange(filters.filter(f => f.id !== id))
  }

  return (
    <div className="flex flex-col gap-2 p-3 bg-card border border-border rounded-lg">
      <div className="flex items-center justify-between">
        <span className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Filters</span>
        <button onClick={addFilter}
          className="px-2.5 py-1 bg-muted border border-border rounded-md text-[11px] text-muted-foreground font-medium cursor-pointer font-sans hover:text-foreground">
          + Add Filter
        </button>
      </div>
      {filters.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {filters.map(f => (
            <FilterRow key={f.id} filter={f} columns={columns} typeMap={typeMap}
              tableName={tableName}
              onUpdate={patch => updateFilter(f.id, patch)}
              onRemove={() => removeFilter(f.id)} />
          ))}
        </div>
      )}
      {filters.length > 0 && (
        <button onClick={() => onChange([])}
          className="self-start text-[11px] text-muted-foreground hover:text-destructive cursor-pointer bg-transparent border-none font-sans">
          Clear all
        </button>
      )}
    </div>
  )
}
