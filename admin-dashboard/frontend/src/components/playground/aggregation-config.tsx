import { useState } from 'react'
import { cn } from '@/lib/utils'
import type { Measure, SchemaColumn } from './types'
import { isNumericType } from './types'

const AGG_FUNCTIONS = ['COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'COUNT_DISTINCT'] as const

let _measureId = 0
function nextMeasureId() { return `m${++_measureId}` }

export function GroupByConfig({ columns, selected, onChange }: {
  columns: string[]; selected: string[]; onChange: (cols: string[]) => void
}) {
  return (
    <div>
      <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider block mb-1.5">Group By</label>
      <div className="flex flex-wrap gap-1.5">
        {columns.map(c => {
          const active = selected.includes(c)
          return (
            <button key={c} onClick={() => onChange(active ? selected.filter(x => x !== c) : [...selected, c])}
              className={cn(
                'px-2.5 py-1 rounded-md text-xs font-mono cursor-pointer border',
                active ? 'bg-primary/10 text-primary border-primary/25' : 'bg-muted text-muted-foreground border-border hover:text-foreground',
              )}>
              {c}
            </button>
          )
        })}
      </div>
    </div>
  )
}

export function MeasuresConfig({ columns, schema, measures, onChange }: {
  columns: string[]; schema: SchemaColumn[]; measures: Measure[]; onChange: (m: Measure[]) => void
}) {
  const numericCols = columns.filter(c => {
    const s = schema.find(sc => sc.column_name === c)
    return s && isNumericType(s.data_type)
  })
  const allCols = columns

  function addMeasure() {
    const col = numericCols[0] || allCols[0] || ''
    const fn = 'COUNT' as const
    const label = `${fn.toLowerCase()}_${col}`
    onChange([...measures, { id: nextMeasureId(), column: col, fn, label }])
  }

  function updateMeasure(id: string, patch: Partial<Measure>) {
    onChange(measures.map(m => {
      if (m.id !== id) return m
      const updated = { ...m, ...patch }
      if (patch.fn || patch.column) {
        updated.label = `${updated.fn.toLowerCase()}_${updated.column}`
      }
      return updated
    }))
  }

  function removeMeasure(id: string) {
    onChange(measures.filter(m => m.id !== id))
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Measures</label>
        <button onClick={addMeasure}
          className="px-2.5 py-1 bg-muted border border-border rounded-md text-[11px] text-muted-foreground font-medium cursor-pointer hover:text-foreground">
          + Add
        </button>
      </div>
      <div className="flex flex-col gap-1.5">
        {measures.map(m => (
          <div key={m.id} className="flex items-center gap-1.5 flex-wrap">
            <select value={m.fn}
              onChange={e => updateMeasure(m.id, { fn: e.target.value as Measure['fn'] })}
              className="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground font-sans outline-none w-[130px]">
              {AGG_FUNCTIONS.map(f => <option key={f} value={f}>{f.replace('_', ' ')}</option>)}
            </select>
            <select value={m.column}
              onChange={e => updateMeasure(m.id, { column: e.target.value })}
              className="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground font-mono outline-none max-w-[160px]">
              {(m.fn === 'COUNT' || m.fn === 'COUNT_DISTINCT' ? allCols : numericCols.length > 0 ? numericCols : allCols).map(c =>
                <option key={c} value={c}>{c}</option>,
              )}
            </select>
            <span className="text-[11px] text-muted-foreground">as</span>
            <input type="text" value={m.label}
              onChange={e => updateMeasure(m.id, { label: e.target.value })}
              className="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground font-mono outline-none w-[160px]" />
            <button onClick={() => removeMeasure(m.id)}
              className="bg-transparent border-none cursor-pointer text-muted-foreground hover:text-destructive text-sm px-1 leading-none">×</button>
          </div>
        ))}
        {measures.length === 0 && (
          <div className="text-[11px] text-muted-foreground italic">No measures configured</div>
        )}
      </div>
    </div>
  )
}

export function HavingConfig({ measures, having, onChange }: {
  measures: Measure[]
  having: { measure: string; operator: string; value: string }[]
  onChange: (h: { measure: string; operator: string; value: string }[]) => void
}) {
  if (measures.length === 0) return null

  function add() {
    const m = measures[0]?.label || ''
    onChange([...having, { measure: m, operator: 'gt', value: '' }])
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-[11px] font-semibold text-muted-foreground uppercase tracking-wider">Having</label>
        <button onClick={add}
          className="px-2.5 py-1 bg-muted border border-border rounded-md text-[11px] text-muted-foreground font-medium cursor-pointer hover:text-foreground">
          + Add
        </button>
      </div>
      {having.map((h, i) => (
        <div key={i} className="flex items-center gap-1.5 mb-1">
          <select value={h.measure}
            onChange={e => onChange(having.map((x, j) => j === i ? { ...x, measure: e.target.value } : x))}
            className="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground font-mono outline-none max-w-[160px]">
            {measures.map(m => <option key={m.label} value={m.label}>{m.label}</option>)}
          </select>
          <select value={h.operator}
            onChange={e => onChange(having.map((x, j) => j === i ? { ...x, operator: e.target.value } : x))}
            className="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground font-sans outline-none w-[70px]">
            {[['gt','>'],['lt','<'],['gte','≥'],['lte','≤'],['eq','=']].map(([v,l]) =>
              <option key={v} value={v}>{l}</option>,
            )}
          </select>
          <input type="number" value={h.value}
            onChange={e => onChange(having.map((x, j) => j === i ? { ...x, value: e.target.value } : x))}
            className="rounded-md border border-border bg-muted px-2 py-1.5 text-xs text-foreground font-sans outline-none w-[100px]" />
          <button onClick={() => onChange(having.filter((_, j) => j !== i))}
            className="bg-transparent border-none cursor-pointer text-muted-foreground hover:text-destructive text-sm px-1 leading-none">×</button>
        </div>
      ))}
    </div>
  )
}
