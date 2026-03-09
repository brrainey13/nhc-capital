import { useState, useEffect, useMemo } from 'react'
import { cn } from '@/lib/utils'
import { type TableInfo, type SchemaColumn, API, fmtNum, fmtCompact } from './types'
import { DataGrid } from './data-grid'

/* ── Table grouping ── */

interface ProjectGroup {
  label: string
  icon: string
  match: (name: string) => boolean
}

const PROJECT_GROUPS: ProjectGroup[] = [
  { label: 'NHL Betting', icon: '', match: (n) => ['games','game_team_stats','player_stats','players','teams','standings','schedules','injuries','injuries_live','lineup_absences','period_scores','goalie_advanced','goalie_saves_by_strength','goalie_starts','goalie_stats','saves_odds','sog_odds','predictions','model_runs','theses','live_game_snapshots','positions','player_odds','team_odds'].includes(n) },
  { label: 'Polymarket', icon: '', match: (n) => ['markets','market_snapshots'].includes(n) },
  { label: 'Real Estate', icon: '', match: (n) => n.startsWith('cook_county_') || n.startsWith('ct_') || n.startsWith('whitney_glen_') || n === 'sf_rentals' || ['commercial_valuations','parcel_sales','parcel_universe','data_refresh_log'].includes(n) },
  { label: 'Crypto', icon: '₿', match: (n) => n.startsWith('crypto_') },
  { label: 'Dashboard', icon: '', match: (n) => ['kanban_events','kanban_tasks','agent_log','api_snapshots','human_notes'].includes(n) },
]

interface TableGroup {
  label: string; icon: string; tables: TableInfo[]; totalRows: number
}

function groupTables(tables: TableInfo[]): TableGroup[] {
  const groups: TableGroup[] = PROJECT_GROUPS.map(g => ({ label: g.label, icon: g.icon, tables: [], totalRows: 0 }))
  const other: TableInfo[] = []
  for (const t of tables) {
    const idx = PROJECT_GROUPS.findIndex(g => g.match(t.name))
    if (idx >= 0) groups[idx].tables.push(t)
    else other.push(t)
  }
  if (other.length > 0) groups.push({ label: 'Other', icon: '', tables: other, totalRows: 0 })
  return groups
    .filter(g => g.tables.length > 0)
    .map(g => ({ ...g, totalRows: g.tables.reduce((s, t) => s + t.row_count, 0) }))
}

/* ── Sidebar ── */

function TableSidebar({ tables, selected, onSelect, search, onSearchChange }: {
  tables: TableInfo[]
  selected: string | null
  onSelect: (name: string) => void
  search: string
  onSearchChange: (v: string) => void
}) {
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({})
  const groups = useMemo(() => groupTables(tables), [tables])

  const filtered = useMemo(() => {
    if (!search.trim()) return groups
    const q = search.toLowerCase()
    return groups.map(g => ({
      ...g,
      tables: g.tables.filter(t => t.name.toLowerCase().includes(q)),
    })).filter(g => g.tables.length > 0)
  }, [groups, search])

  function toggle(label: string) {
    setExpandedGroups(prev => ({ ...prev, [label]: !prev[label] }))
  }

  return (
    <div className="flex flex-col h-full border-r border-border bg-card">
      <div className="p-3 border-b border-border">
        <input type="text" value={search} onChange={e => onSearchChange(e.target.value)}
          placeholder="Search tables…"
          className="w-full rounded-md border border-border bg-muted px-3 py-2 text-sm text-foreground font-sans outline-none" />
        <div className="text-[11px] text-muted-foreground mt-1.5">
          {fmtNum(tables.length)} tables · {fmtCompact(tables.reduce((s, t) => s + t.row_count, 0))} rows
        </div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {filtered.map(g => {
          const expanded = expandedGroups[g.label] ?? (search.trim().length > 0)
          return (
            <div key={g.label}>
              <button onClick={() => toggle(g.label)}
                className="flex items-center justify-between w-full bg-transparent border-none cursor-pointer font-sans text-foreground text-left px-3 py-2.5 text-[13px] font-semibold hover:bg-muted/50 border-b border-border">
                <span>{expanded ? '▾' : '▸'} {g.icon} {g.label}</span>
                <span className="text-[10px] text-muted-foreground font-normal">{g.tables.length}</span>
              </button>
              {expanded && g.tables.sort((a, b) => b.row_count - a.row_count).map(t => (
                <button key={t.name} onClick={() => onSelect(t.name)}
                  className={cn(
                    'flex items-center justify-between w-full bg-transparent border-none cursor-pointer font-sans text-left pl-8 pr-3 py-2 text-[13px] hover:bg-muted/50 border-b border-border/50',
                    selected === t.name && 'bg-primary/10 text-primary font-medium',
                    selected !== t.name && 'text-foreground',
                  )}>
                  <span className="font-mono text-xs truncate">{t.name}</span>
                  <span className="text-[10px] text-muted-foreground tabular-nums ml-2 shrink-0">{fmtCompact(t.row_count)}</span>
                </button>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ── Table Explorer ── */

export function TableExplorer({ tables, mobile }: {
  tables: TableInfo[]
  mobile?: boolean
}) {
  const [selected, setSelected] = useState<string | null>(null)
  const [schema, setSchema] = useState<SchemaColumn[]>([])
  const [search, setSearch] = useState('')
  const [showSidebar, setShowSidebar] = useState(!mobile)

  useEffect(() => {
    if (!selected) { setSchema([]); return }
    fetch(`${API}/tables/${selected}/schema`)
      .then(r => r.json())
      .then(d => setSchema(d.columns || []))
      .catch(() => setSchema([]))
  }, [selected])

  if (mobile) {
    return (
      <div className="flex flex-col h-full">
        {!selected ? (
          <TableSidebar tables={tables} selected={selected} onSelect={setSelected}
            search={search} onSearchChange={setSearch} />
        ) : (
          <div className="flex flex-col h-full">
            <button onClick={() => setSelected(null)}
              className="px-3 py-2 bg-muted border border-border rounded-md text-[11px] text-muted-foreground font-medium cursor-pointer self-start mb-2">
              ← Tables
            </button>
            <div className="text-lg font-bold text-foreground mb-1">{selected}</div>
            <DataGrid tableName={selected} schema={schema} mobile />
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="flex h-full gap-0">
      {showSidebar && (
        <div className="w-[260px] shrink-0 h-full">
          <TableSidebar tables={tables} selected={selected} onSelect={setSelected}
            search={search} onSearchChange={setSearch} />
        </div>
      )}
      <div className="flex-1 flex flex-col min-w-0 h-full px-4">
        <div className="flex items-center gap-2 mb-2 shrink-0">
          <button onClick={() => setShowSidebar(!showSidebar)}
            className="px-2 py-1 bg-muted border border-border rounded text-[11px] text-muted-foreground cursor-pointer">
            {showSidebar ? '◁' : '▷'} Tables
          </button>
          {selected && <h3 className="text-base font-bold text-foreground m-0">{selected}</h3>}
        </div>
        {selected ? (
          <DataGrid tableName={selected} schema={schema} />
        ) : (
          <div className="flex-1 flex items-center justify-center text-muted-foreground text-sm">
            Select a table from the sidebar
          </div>
        )}
      </div>
    </div>
  )
}
