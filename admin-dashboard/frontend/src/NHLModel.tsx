import React, { useEffect, useMemo, useState } from 'react'
import { ChartPanel } from '@/components/ui/chart-panel'
import { cn } from '@/lib/utils'
import { InteractiveBarChart } from '@/components/charts/interactive-bar-chart'
import { ChartControls, downloadCSV } from '@/components/charts/chart-controls'

type ModelInfo = {
  model_type: string
  model_found: boolean
  model_path: string | null
  n_features: number
  n_training_samples: number
  training_date: string | null
  feature_importances: Array<{ feature: string; importance: number }>
}

type Pick = {
  pick_id: number
  pick_date: string | null
  player: string
  market: string
  side: string | null
  line: number
  odds: number | null
  book: string | null
  edge: number
  edge_pct: number
  model_prob: number
  model_prob_pct: number
  implied_prob: number
  implied_prob_pct: number
  stake: number
  stake_dollars: number
  strategy: string | null
  confidence: string | null
  result: string | null
  pnl: number
}

type TodayPicksResponse = {
  pick_date: string
  count: number
  total_stake: number
  total_stake_dollars: number
  picks: Pick[]
}

type HistoryResponse = {
  summary: {
    wins: number
    losses: number
    pushes: number
    pending: number
    record: string
    total_pl: number
    total_staked: number
    roi: number
  }
  strategies: string[]
  picks: Pick[]
}

type StrategyRow = {
  strategy: string
  pick_count: number
  wins: number
  losses: number
  pushes: number
  pending: number
  record: string
  roi: number
  avg_edge: number
  total_pl: number
  total_staked: number
}

type StrategyResponse = {
  strategies: StrategyRow[]
}

type OddsOffer = {
  book: string
  side: string
  line: number
  odds: number | null
  pulled_at: string | null
}

type OddsMarket = {
  player: string
  market: string
  offers: OddsOffer[]
  best_over_odds: OddsOffer | null
  best_under_odds: OddsOffer | null
}

type OddsGame = {
  game: string
  snapshot_date: string | null
  markets: OddsMarket[]
}

type OddsSnapshotResponse = {
  source: string
  snapshot_date: string | null
  games: OddsGame[]
}

type SortKey = 'player' | 'market' | 'line' | 'odds' | 'book' | 'edge_pct' | 'model_prob_pct' | 'stake'

const API = '/api/nhl'

function fmtMoney(value: number) {
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function fmtPct(value: number, digits = 1) {
  return `${value.toFixed(digits)}%`
}

function fmtOdds(value: number | null) {
  if (value == null) return '\u2014'
  return value > 0 ? `+${value}` : `${value}`
}

function fmtDate(value: string | null) {
  if (!value) return '\u2014'
  return new Date(value).toLocaleDateString()
}

function edgeColorClass(edgePct: number) {
  if (edgePct > 10) return 'text-success'
  if (edgePct >= 5) return 'text-warning'
  return 'text-muted-foreground'
}

function resultColorClass(result: string | null) {
  if (result === 'W') return 'text-success'
  if (result === 'L') return 'text-destructive'
  if (result === 'P') return 'text-muted-foreground'
  return 'text-muted-foreground'
}

function sortPicks(picks: Pick[], key: SortKey, dir: 'asc' | 'desc') {
  const sorted = picks.slice().sort((a, b) => {
    const av = a[key]
    const bv = b[key]
    if (typeof av === 'number' && typeof bv === 'number') {
      return dir === 'asc' ? av - bv : bv - av
    }
    return dir === 'asc'
      ? String(av ?? '').localeCompare(String(bv ?? ''))
      : String(bv ?? '').localeCompare(String(av ?? ''))
  })
  return sorted
}

export default function NHLModel({ mobile }: { mobile: boolean }) {
  const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null)
  const [today, setToday] = useState<TodayPicksResponse | null>(null)
  const [history, setHistory] = useState<HistoryResponse | null>(null)
  const [strategies, setStrategies] = useState<StrategyResponse | null>(null)
  const [odds, setOdds] = useState<OddsSnapshotResponse | null>(null)
  const [strategyFilter, setStrategyFilter] = useState('All')
  const [sortKey, setSortKey] = useState<SortKey>('edge_pct')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [error, setError] = useState<string | null>(null)

  async function load(activeStrategy = strategyFilter) {
    const historyParams = new URLSearchParams({ days: '30' })
    if (activeStrategy !== 'All') historyParams.set('strategy', activeStrategy)
    const [infoRes, todayRes, historyRes, strategyRes, oddsRes] = await Promise.all([
      fetch(`${API}/model/info`),
      fetch(`${API}/picks/today`),
      fetch(`${API}/picks/history?${historyParams}`),
      fetch(`${API}/model/strategies?days=30`),
      fetch(`${API}/odds/snapshot`),
    ])
    const [infoJson, todayJson, historyJson, strategyJson, oddsJson] = await Promise.all([
      infoRes.json(),
      todayRes.json(),
      historyRes.json(),
      strategyRes.json(),
      oddsRes.json(),
    ])
    setModelInfo(infoJson as ModelInfo)
    setToday(todayJson as TodayPicksResponse)
    setHistory(historyJson as HistoryResponse)
    setStrategies(strategyJson as StrategyResponse)
    setOdds(oddsJson as OddsSnapshotResponse)
  }

  useEffect(() => {
    load(strategyFilter).catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [strategyFilter])

  const sortedTodayPicks = useMemo(() => {
    if (!today) return []
    return sortPicks(today.picks, sortKey, sortDir)
  }, [today, sortKey, sortDir])

  const topFeatures = useMemo(() => modelInfo?.feature_importances.slice(0, 15) ?? [], [modelInfo])
  const strategyOptions = useMemo(() => ['All', ...(history?.strategies ?? [])], [history])

  const confidenceCounts = useMemo(() => {
    if (!today) return []
    const counts: Record<string, number> = { HIGH: 0, MEDIUM: 0, LOW: 0 }
    for (const pick of today.picks) {
      const conf = (pick.confidence ?? 'LOW').toUpperCase()
      counts[conf] = (counts[conf] ?? 0) + 1
    }
    return Object.entries(counts)
      .filter(([, count]) => count > 0)
      .map(([confidence, count]) => ({ confidence, count }))
  }, [today])

  if (error) {
    return <div className="p-6 text-destructive">Failed to load model outputs: {error}</div>
  }

  if (!modelInfo || !today || !history || !strategies || !odds) {
    return <div className="p-6 text-muted-foreground">Loading model outputs&hellip;</div>
  }

  function toggleSort(nextKey: SortKey) {
    if (sortKey === nextKey) {
      setSortDir(sortDir === 'desc' ? 'asc' : 'desc')
      return
    }
    setSortKey(nextKey)
    setSortDir('desc')
  }

  return (
    <div className={cn('page-enter flex h-full flex-col gap-4 overflow-auto', mobile ? 'pb-24' : 'pb-6')}>
      {/* Model Info + Feature Importance */}
      <section className="rounded-xl border border-border bg-card p-4 shadow-lg">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-3">
          <div>
            <div className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">Model Info</div>
            <div className={cn('font-extrabold tracking-tight text-foreground', mobile ? 'text-2xl' : 'text-[30px]')}>{modelInfo.model_type}</div>
          </div>
          {!modelInfo.model_found && <div className="text-xs text-warning">Model artifact not found. Showing metadata fallbacks only.</div>}
        </div>
        <div className={cn('mb-4 grid gap-3', mobile ? 'grid-cols-2' : 'grid-cols-4')}>
          <div>
            <div className="mb-1 text-[11px] uppercase tracking-[0.05em] text-muted-foreground">Features</div>
            <div className="text-xl font-bold tabular-nums text-foreground">{String(modelInfo.n_features)}</div>
          </div>
          <div>
            <div className="mb-1 text-[11px] uppercase tracking-[0.05em] text-muted-foreground">Training Rows</div>
            <div className="text-xl font-bold tabular-nums text-foreground">{modelInfo.n_training_samples.toLocaleString()}</div>
          </div>
          <div>
            <div className="mb-1 text-[11px] uppercase tracking-[0.05em] text-muted-foreground">Training Date</div>
            <div className="text-xl font-bold tabular-nums text-foreground">{modelInfo.training_date || '\u2014'}</div>
          </div>
          <div>
            <div className="mb-1 text-[11px] uppercase tracking-[0.05em] text-muted-foreground">Artifact</div>
            <div className="text-xl font-bold tabular-nums text-primary">{modelInfo.model_path ? 'Found' : 'Missing'}</div>
          </div>
        </div>
        <ChartPanel
          title="Feature Importance"
          height={mobile ? 320 : 360}
          actions={
            <ChartControls
              exportData={() => downloadCSV(topFeatures as Record<string, unknown>[], 'feature-importance.csv')}
            />
          }
        >
          <InteractiveBarChart
            data={topFeatures}
            bars={[{ dataKey: 'importance', color: 'hsl(var(--primary))', label: 'Importance' }]}
            xKey="feature"
            layout="vertical"
            height={mobile ? 300 : 340}
            showSortToggle
            formatY={(v) => v.toFixed(0)}
          />
        </ChartPanel>
      </section>

      {/* Today's Picks + Confidence Distribution */}
      <section className="rounded-xl border border-border bg-card p-4 shadow-lg">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Today&apos;s Picks</div>
          <div className="flex flex-wrap gap-4">
            <span className="text-xs text-muted-foreground">{today.count} picks</span>
            <span className="text-xs text-muted-foreground">Stake {today.total_stake.toFixed(1)}u</span>
            <span className="text-xs text-muted-foreground">{fmtMoney(today.total_stake_dollars)}</span>
          </div>
        </div>

        {/* Pick Confidence Distribution */}
        {confidenceCounts.length > 0 && (
          <div className="mb-3">
            <ChartPanel title="Pick Confidence Distribution" height={120}>
              <InteractiveBarChart
                data={confidenceCounts}
                bars={[{
                  dataKey: 'count',
                  color: 'hsl(var(--chart-1))',
                  label: 'Picks',
                  colorByValue: false,
                }]}
                xKey="confidence"
                height={100}
              />
            </ChartPanel>
          </div>
        )}

        {today.picks.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <div className="text-3xl">🏒</div>
            <div className="text-sm text-muted-foreground">No picks generated yet today</div>
            <div className="text-xs text-muted-foreground">Check back when the model has run</div>
          </div>
        ) : mobile ? (
          <div className="flex max-h-[420px] flex-col gap-2 overflow-auto">
            {sortedTodayPicks.map((pick) => (
              <div key={pick.pick_id} className="rounded-lg border border-border bg-muted/30 p-3">
                <div className="mb-1.5 flex items-center justify-between gap-2">
                  <span className="truncate text-sm font-semibold text-foreground">{pick.player}</span>
                  <span className={cn('shrink-0 text-sm font-bold tabular-nums', edgeColorClass(pick.edge_pct))}>{fmtPct(pick.edge_pct, 2)}</span>
                </div>
                <div className="mb-1.5 text-xs text-muted-foreground">{pick.market} · {pick.book || '—'}</div>
                <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs tabular-nums">
                  <span><span className="text-muted-foreground">Line </span><span className="text-foreground">{pick.line.toFixed(1)}</span></span>
                  <span><span className="text-muted-foreground">Odds </span><span className="text-foreground">{fmtOdds(pick.odds)}</span></span>
                  <span><span className="text-muted-foreground">Prob </span><span className="text-foreground">{pick.model_prob_pct > 0 ? fmtPct(pick.model_prob_pct, 1) : '—'}</span></span>
                  <span><span className="text-muted-foreground">Stake </span><span className="text-foreground">{pick.stake.toFixed(1)}u</span></span>
                </div>
              </div>
            ))}
            <div className="rounded-lg border border-border bg-muted px-3 py-2.5 text-sm font-bold tabular-nums text-foreground">
              Total Stake: {today.total_stake.toFixed(1)}u
            </div>
          </div>
        ) : (
          <div className="max-h-[420px] overflow-auto rounded-xl border border-border">
            <table className="w-full text-xs">
              <thead>
                <tr>
                  {([
                    ['player', 'Player'],
                    ['market', 'Market'],
                    ['line', 'Line'],
                    ['odds', 'Odds'],
                    ['book', 'Book'],
                    ['edge_pct', 'Edge%'],
                    ['model_prob_pct', 'Model Prob'],
                    ['stake', 'Stake'],
                  ] as [SortKey, string][]).map(([key, label]) => (
                    <th
                      key={key}
                      onClick={() => toggleSort(key)}
                      className="sticky top-0 cursor-pointer border-b border-border bg-card px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground transition-colors hover:text-foreground"
                    >
                      {label}
                      {sortKey === key && <span className="ml-1">{sortDir === 'desc' ? '↓' : '↑'}</span>}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sortedTodayPicks.map((pick) => (
                  <tr key={pick.pick_id} className="border-b border-border/50 transition-colors hover:bg-muted/50">
                    <td className="px-3 py-2.5 tabular-nums text-foreground">{pick.player}</td>
                    <td className="px-3 py-2.5 tabular-nums text-foreground">{pick.market}</td>
                    <td className="px-3 py-2.5 tabular-nums text-foreground">{pick.line.toFixed(1)}</td>
                    <td className="px-3 py-2.5 tabular-nums text-foreground">{fmtOdds(pick.odds)}</td>
                    <td className="px-3 py-2.5 tabular-nums text-foreground">{pick.book || '\u2014'}</td>
                    <td className={cn('px-3 py-2.5 tabular-nums font-bold', edgeColorClass(pick.edge_pct))}>{fmtPct(pick.edge_pct, 2)}</td>
                    <td className="px-3 py-2.5 tabular-nums text-foreground">{pick.model_prob_pct > 0 ? fmtPct(pick.model_prob_pct, 1) : '\u2014'}</td>
                    <td className="px-3 py-2.5 tabular-nums text-foreground">{pick.stake.toFixed(1)}u</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td className="border-b border-border bg-muted px-3 py-2.5 font-bold tabular-nums text-foreground" colSpan={7}>Total Stake</td>
                  <td className="border-b border-border bg-muted px-3 py-2.5 font-bold tabular-nums text-foreground">{today.total_stake.toFixed(1)}u</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </section>

      {/* Pick History */}
      <section className="rounded-xl border border-border bg-card p-4 shadow-lg">
        <div className={cn('mb-3 flex gap-3', mobile ? 'flex-col items-stretch' : 'flex-row items-baseline justify-between')}>
          <div>
            <div className="mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">Pick History</div>
            <div className="flex flex-wrap gap-4">
              <span className="text-xs text-muted-foreground">Record {history.summary.record}</span>
              <span className="text-xs text-muted-foreground">ROI {fmtPct(history.summary.roi, 2)}</span>
              <span className="text-xs text-muted-foreground">P/L {fmtMoney(history.summary.total_pl)}</span>
            </div>
          </div>
          <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
            Strategy
            <select
              value={strategyFilter}
              onChange={(e) => setStrategyFilter(e.target.value)}
              className="rounded-lg border border-border bg-muted px-2.5 py-2 font-inherit text-foreground"
            >
              {strategyOptions.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
          </label>
        </div>
        {history.picks.length === 0 ? (
          <div className="flex flex-col items-center gap-2 py-8 text-center">
            <div className="text-3xl">📋</div>
            <div className="text-sm text-muted-foreground">No pick history for this period</div>
          </div>
        ) : mobile ? (
          <div className="flex max-h-[420px] flex-col gap-2 overflow-auto">
            {history.picks.map((pick) => (
              <div key={pick.pick_id} className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/30 p-3">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-semibold text-foreground">{pick.player}</div>
                  <div className="text-xs text-muted-foreground">{pick.market} · {fmtDate(pick.pick_date)}</div>
                </div>
                <div className="shrink-0 text-right">
                  <div className={cn('text-sm font-bold', resultColorClass(pick.result))}>{pick.result || 'Pending'}</div>
                  <div className={cn('text-xs tabular-nums', pick.pnl >= 0 ? 'text-success' : 'text-destructive')}>
                    {pick.result === 'Pending' ? '—' : fmtMoney(pick.pnl)}
                  </div>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <div className="max-h-[420px] overflow-auto rounded-xl border border-border">
            <table className="w-full text-xs">
              <thead>
                <tr>
                  {['Date', 'Player', 'Market', 'Result', 'P/L'].map((label) => (
                    <th key={label} className="sticky top-0 border-b border-border bg-card px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground">
                      {label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {history.picks.map((pick) => (
                  <tr key={pick.pick_id} className="border-b border-border/50 transition-colors hover:bg-muted/50">
                    <td className="px-3 py-2.5 tabular-nums text-foreground">{fmtDate(pick.pick_date)}</td>
                    <td className="px-3 py-2.5 tabular-nums text-foreground">{pick.player}</td>
                    <td className="px-3 py-2.5 tabular-nums text-foreground">{pick.market}</td>
                    <td className={cn('px-3 py-2.5 tabular-nums font-bold', resultColorClass(pick.result))}>{pick.result || 'Pending'}</td>
                    <td className={cn('px-3 py-2.5 tabular-nums', pick.pnl >= 0 ? 'text-success' : 'text-destructive')}>{pick.result === 'Pending' ? '\u2014' : fmtMoney(pick.pnl)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Strategy Performance */}
      <section className="rounded-xl border border-border bg-card p-4 shadow-lg">
        <div className="mb-3 text-[11px] uppercase tracking-wider text-muted-foreground">Strategy Performance</div>
        <div className={cn('mb-4 grid gap-3', mobile ? 'grid-cols-1' : 'grid-cols-[repeat(auto-fit,minmax(180px,1fr))]')}>
          {strategies.strategies.map((row) => (
            <div key={row.strategy} className="card-hover rounded-xl border border-border bg-muted/50 p-3.5">
              <div className="mb-1.5 text-xs text-muted-foreground">{row.strategy}</div>
              <div className="mb-2.5 text-[22px] font-bold text-foreground">{row.record}</div>
              <div className="mt-1.5 flex items-center justify-between gap-2 text-xs">
                <span className="text-muted-foreground">ROI</span>
                <span className={row.roi >= 0 ? 'text-success' : 'text-destructive'}>{fmtPct(row.roi, 2)}</span>
              </div>
              <div className="mt-1.5 flex items-center justify-between gap-2 text-xs">
                <span className="text-muted-foreground">Avg Edge</span>
                <span className="text-warning">{fmtPct(row.avg_edge, 2)}</span>
              </div>
              <div className="mt-1.5 flex items-center justify-between gap-2 text-xs">
                <span className="text-muted-foreground">Picks</span>
                <span className="text-foreground">{row.pick_count}</span>
              </div>
            </div>
          ))}
        </div>
        <ChartPanel
          title="Strategy ROI"
          height={mobile ? 280 : 320}
          actions={
            <ChartControls
              exportData={() => downloadCSV(strategies.strategies as unknown as Record<string, unknown>[], 'strategy-performance.csv')}
            />
          }
        >
          <InteractiveBarChart
            data={strategies.strategies}
            bars={[{
              dataKey: 'roi',
              color: 'hsl(var(--chart-1))',
              label: 'ROI',
              colorByValue: true,
              positiveColor: 'hsl(var(--success))',
              negativeColor: 'hsl(var(--destructive))',
            }]}
            xKey="strategy"
            formatY={(v) => `${v.toFixed(1)}%`}
            height={mobile ? 260 : 300}
            showSortToggle
          />
        </ChartPanel>
      </section>

      {/* Odds Snapshot */}
      <section className="rounded-xl border border-border bg-card p-4 shadow-lg">
        <div className="mb-3 flex flex-wrap items-baseline justify-between gap-3">
          <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Odds Snapshot</div>
          <div className="text-xs text-muted-foreground">Source {odds.source} &middot; Snapshot {odds.snapshot_date || '\u2014'}</div>
        </div>
        <div className="flex flex-col gap-3">
          {odds.games.length === 0 && (
            <div className="flex flex-col items-center gap-2 py-8 text-center">
              <div className="text-3xl">📊</div>
              <div className="text-sm text-muted-foreground">No odds snapshot available</div>
            </div>
          )}
          {odds.games.map((game) => (
            <div key={game.game} className="rounded-xl border border-border bg-muted/50 p-3.5">
              <div className="mb-2.5 text-base font-bold text-foreground">{game.game}</div>
              <div className="flex flex-col gap-2">
                {game.markets.map((market) => (
                  <div key={`${market.player}-${market.market}`} className="border-t border-border pt-2">
                    <div className="mb-1.5 flex flex-wrap items-center justify-between gap-3">
                      <span className="font-semibold text-foreground">{market.player}</span>
                      <span className="text-xs text-muted-foreground">{market.market}</span>
                    </div>
                    <div className={cn('grid gap-2', mobile ? 'grid-cols-1' : 'grid-cols-[repeat(auto-fit,minmax(140px,1fr))]')}>
                      {market.offers.map((offer, idx) => {
                        const isBest = (offer.side === 'over' && market.best_over_odds?.book === offer.book && market.best_over_odds?.odds === offer.odds)
                          || (offer.side === 'under' && market.best_under_odds?.book === offer.book && market.best_under_odds?.odds === offer.odds)
                        return (
                          <div
                            key={`${offer.book}-${offer.side}-${idx}`}
                            className={cn(
                              'card-hover rounded-lg border p-2.5',
                              isBest
                                ? 'border-success bg-success/[0.08]'
                                : 'border-border bg-card'
                            )}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-semibold text-foreground">{offer.book}</span>
                              <span className="text-muted-foreground">{offer.side.toUpperCase()}</span>
                            </div>
                            <div className="mt-1.5 text-foreground">Line {offer.line.toFixed(1)} &middot; {fmtOdds(offer.odds)}</div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
