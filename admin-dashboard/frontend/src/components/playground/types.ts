export interface TableInfo {
  name: string
  row_count: number
  database?: string
}

export interface SchemaColumn {
  column_name: string
  data_type: string
  is_nullable: string
}

export interface ActiveFilter {
  id: string
  column: string
  operator: string
  value: string
  value2?: string
}

export interface DataResponse {
  columns: string[]
  rows: Record<string, unknown>[]
  total: number
  filtered_total: number
}

export interface QueryResult {
  columns: string[]
  rows: Record<string, unknown>[]
  error?: string
}

export interface Measure {
  id: string
  column: string
  fn: 'COUNT' | 'SUM' | 'AVG' | 'MIN' | 'MAX' | 'COUNT_DISTINCT'
  label: string
}

export interface AnalyticsConfig {
  table: string
  groupBy: string[]
  measures: Measure[]
  filters: ActiveFilter[]
  having: { measure: string; operator: string; value: string }[]
  sortBy: string | null
  sortDir: 'asc' | 'desc'
  limit: number
}

export type SortDir = 'asc' | 'desc' | null

export const API = '/api'

export const NUMERIC_TYPES = new Set([
  'integer', 'bigint', 'smallint', 'numeric', 'real', 'double precision',
])
export const DATE_TYPES = new Set([
  'date', 'timestamp without time zone', 'timestamp with time zone',
])
export const BOOLEAN_TYPES = new Set(['boolean'])

export function isNumericType(dt: string) { return NUMERIC_TYPES.has(dt) }
export function isDateType(dt: string) { return DATE_TYPES.has(dt) }

export function operatorsForType(dt: string): { value: string; label: string }[] {
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

export function fmtNum(n: number): string { return n.toLocaleString() }

export function fmtDate(iso: string | null): string {
  if (!iso) return '—'
  const d = new Date(iso)
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

export function fmtCompact(n: number): string {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M'
  if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K'
  return String(n)
}

let _filterId = 0
export function nextFilterId() { return `f${++_filterId}` }

export function buildFilterParam(
  filters: ActiveFilter[],
  typeMap: Record<string, string>,
): string | null {
  const active = filters.filter(f => f.value.trim() !== '')
  if (active.length === 0) return null
  return JSON.stringify(active.map(f => {
    const dt = typeMap[f.column] || ''
    if (f.operator === 'between') {
      const vals = isNumericType(dt)
        ? [Number(f.value), Number(f.value2 ?? f.value)]
        : [f.value, f.value2 ?? f.value]
      return { column: f.column, operator: f.operator, value: vals }
    }
    return {
      column: f.column, operator: f.operator,
      value: isNumericType(dt) ? Number(f.value) : f.value,
    }
  }))
}

export function formatCellValue(value: unknown, dataType?: string): string {
  if (value === null || value === undefined) return ''
  if (typeof value === 'boolean') return String(value)
  if (typeof value === 'number') {
    if (Number.isInteger(value)) return value.toLocaleString()
    return value.toLocaleString(undefined, { maximumFractionDigits: 4 })
  }
  if (dataType && isDateType(dataType)) return fmtDate(String(value))
  return String(value)
}
