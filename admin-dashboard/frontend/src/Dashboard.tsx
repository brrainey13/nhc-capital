import { useEffect, useMemo, useState } from 'react'
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Sector,
  Tooltip,
} from 'recharts'
import {
  API,
  buildHealthRows,
  fmtCompact,
  fmtCountdown,
  fmtCurrency,
  fmtDateTime,
  fmtDayLabel,
  fmtNum,
  fmtPct,
  fmtRelativeFromNow,
  fmtTimeEst,
  getRateLimitColor,
  getRecencyColor,
  type ClaudeCosts,
  type HealthData,
  type TableInfo,
  type UsageData,
} from './dashboardSupport'
import { PageHeader } from '@/components/ui/page-header'
import { StatCard } from '@/components/ui/stat-card'
import { ChartPanel, chartTooltipStyle } from '@/components/ui/chart-panel'
import { ProgressBar } from '@/components/ui/progress-bar'
import { StatusBadge } from '@/components/ui/status-badge'
import { InteractiveAreaChart } from '@/components/charts/interactive-area-chart'
import { InteractiveBarChart } from '@/components/charts/interactive-bar-chart'
import { ChartControls, downloadCSV } from '@/components/charts/chart-controls'

type DashboardProps = { mobile: boolean }

export default function Dashboard({ mobile }: DashboardProps) {
  const [usage, setUsage] = useState<UsageData | null>(null)
  const [claudeCosts, setClaudeCosts] = useState<ClaudeCosts | null>(null)
  const [health, setHealth] = useState<HealthData | null>(null)
  const [tables, setTables] = useState<TableInfo[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [nowMs, setNowMs] = useState(Date.now())
  const [showBurnBrush, setShowBurnBrush] = useState(false)
  const [activePieIndex, setActivePieIndex] = useState<number | undefined>(undefined)

  useEffect(() => {
    let cancelled = false

    async function loadAll() {
      try {
        const [usageRes, costsRes, healthRes, tablesRes] = await Promise.all([
          fetch(`${API}/usage`),
          fetch(`${API}/usage/claude-limits`),
          fetch(`${API}/health`),
          fetch(`${API}/tables`),
        ])

        const [usageJson, costsJson, healthJson, tablesJson] = await Promise.all([
          usageRes.ok ? usageRes.json() : null,
          costsRes.ok ? costsRes.json() : null,
          healthRes.ok ? healthRes.json() : null,
          tablesRes.ok ? tablesRes.json() : null,
        ])

        if (cancelled) return

        setUsage(usageJson && usageJson.freshness ? (usageJson as UsageData) : null)
        setClaudeCosts(costsJson ? (costsJson as ClaudeCosts) : null)
        setHealth((healthJson as HealthData | null) ?? null)
        setTables(Array.isArray(tablesJson) ? (tablesJson as TableInfo[]) : null)
        setLoadFailed(!usageJson)
      } catch {
        if (cancelled) return
        setUsage(null)
        setClaudeCosts(null)
        setHealth(null)
        setTables(null)
        setLoadFailed(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    loadAll()
    const refresh = window.setInterval(loadAll, 30_000)
    return () => {
      cancelled = true
      window.clearInterval(refresh)
    }
  }, [])

  useEffect(() => {
    const timer = window.setInterval(() => setNowMs(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const sessionRows = useMemo(() => {
    return (usage?.sessions ?? []).slice().sort((a, b) => {
      const burnDelta = (b.burn_rate_24h_est ?? 0) - (a.burn_rate_24h_est ?? 0)
      if (burnDelta !== 0) return burnDelta
      const updatedA = a.updated_at ? new Date(a.updated_at).getTime() : 0
      const updatedB = b.updated_at ? new Date(b.updated_at).getTime() : 0
      return updatedB - updatedA
    })
  }, [usage])

  const activeSessionsLastHour = useMemo(
    () => sessionRows.filter((session) => session.updated_at && (nowMs - new Date(session.updated_at).getTime()) <= 3600_000),
    [nowMs, sessionRows],
  )

  const dominantModel = useMemo(() => {
    const claudeSession = sessionRows.find((session) => session.model.toLowerCase().includes('claude'))
    return claudeSession?.model || usage?.models?.[0]?.model || 'Model unavailable'
  }, [sessionRows, usage])

  const tokenBudget = useMemo(() => {
    const used = usage?.windows.last_24h?.total_tokens ?? 0
    const activeCapacity = activeSessionsLastHour.reduce((sum, session) => sum + (session.context_window || 0), 0)
    const fallbackCapacity = sessionRows.reduce((sum, session) => sum + (session.context_window || 0), 0)
    const capacity = activeCapacity || fallbackCapacity
    const remaining = Math.max(capacity - used, 0)
    const pct = capacity > 0 ? Math.min((used / capacity) * 100, 100) : 0
    return { used, capacity, remaining, pct }
  }, [activeSessionsLastHour, sessionRows, usage])

  const burnTrend = useMemo(() => {
    return (usage?.trend.buckets ?? []).map((bucket) => ({
      label: fmtTimeEst(bucket.start),
      tokens: bucket.total_tokens,
      sessions: bucket.session_count,
      start: bucket.start,
    }))
  }, [usage])

  const dailyCostSeries = useMemo(() => {
    return (claudeCosts?.daily_costs ?? []).map((row) => ({
      ...row,
      label: fmtDayLabel(row.date),
    }))
  }, [claudeCosts])

  const costBreakdown = useMemo(() => {
    const palette = [
      'hsl(var(--chart-1))',
      'hsl(var(--chart-2))',
      'hsl(var(--chart-3))',
      'hsl(var(--chart-4))',
      'hsl(var(--chart-5))',
      'hsl(180 70% 50%)',
    ]
    return Object.entries(claudeCosts?.models_7d ?? {})
      .sort(([, a], [, b]) => b.cost - a.cost)
      .map(([model, data], index) => ({
        model,
        cost: data.cost,
        tokens: data.tokens,
        color: palette[index % palette.length],
      }))
  }, [claudeCosts])

  const hostMode = typeof window !== 'undefined' && !['localhost', '127.0.0.1'].includes(window.location.hostname)
    ? 'Cloudflare edge'
    : 'Local dev'
  const healthRows = buildHealthRows({ health, tables, hostMode, usage, claudeCosts, nowMs })

  if (loading && !usage) {
    return (
      <section className="rounded-xl border border-border bg-card p-4 shadow-lg">
        <div className="text-sm text-muted-foreground">Loading dashboard telemetry…</div>
      </section>
    )
  }

  if (!usage) {
    return (
      <section className="rounded-xl border border-border bg-card p-4 shadow-lg">
        <div className="text-sm text-muted-foreground">
          {loadFailed ? 'Unable to load dashboard telemetry. Refresh and sign in again.' : 'Loading dashboard telemetry…'}
        </div>
      </section>
    )
  }

  const rateLimitColor = getRateLimitColor(usage.claude_rate_limit.status)

  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const renderActiveShape = (props: any) => {
    const { cx, cy, innerRadius, outerRadius, startAngle, endAngle, fill, payload, percent } = props
    return (
      <g>
        <text x={cx} y={cy - 6} textAnchor="middle" fill="hsl(var(--foreground))" className="text-xs font-bold">
          {payload.model?.split('/').pop() ?? ''}
        </text>
        <text x={cx} y={cy + 12} textAnchor="middle" fill="hsl(var(--muted-foreground))" className="text-[10px]">
          {(percent * 100).toFixed(1)}%
        </text>
        <Sector cx={cx} cy={cy} innerRadius={innerRadius - 3} outerRadius={outerRadius + 6} startAngle={startAngle} endAngle={endAngle} fill={fill} />
        <Sector cx={cx} cy={cy} innerRadius={outerRadius + 8} outerRadius={outerRadius + 11} startAngle={startAngle} endAngle={endAngle} fill={fill} opacity={0.4} />
      </g>
    )
  }

  return (
    <div className={`page-enter h-full overflow-auto ${mobile ? 'pb-24' : 'pb-6'}`}>
      <PageHeader
        title="Ops Command Center"
        subtitle={
          <>
            Generated {fmtDateTime(usage.freshness.generated_at)} · latest session {fmtRelativeFromNow(usage.freshness.latest_session_update_at, nowMs)} · refreshes every 30s
          </>
        }
        actions={
          <div className="flex items-center gap-2 rounded-full border border-border bg-card px-3 py-2">
            <span className="h-2 w-2 rounded-full" style={{ background: rateLimitColor, boxShadow: `0 0 12px ${rateLimitColor}66` }} />
            <span className="text-xs uppercase tracking-wider text-muted-foreground">Claude {usage.claude_rate_limit.status}</span>
            <span className="text-xs font-bold tabular-nums text-foreground">
              {fmtCountdown(usage.claude_rate_limit.seconds_until_reset, nowMs, usage.claude_rate_limit.reset_at)}
            </span>
          </div>
        }
      />

      {/* Metric Cards */}
      <section className={`mb-4 grid gap-3 ${mobile ? 'grid-cols-1' : 'grid-cols-4'}`}>
        <StatCard
          label="API Status"
          accentColor={rateLimitColor}
          footer={`Reset ${fmtDateTime(usage.claude_rate_limit.reset_at)}`}
          value={
            <div className="flex items-center justify-between gap-3">
              <div>
                <div className="text-[26px] font-extrabold tracking-tight text-foreground">
                  {health?.status === 'ok' ? 'Online' : 'Check API'}
                </div>
                <div className="mt-1 truncate text-xs text-muted-foreground">{dominantModel}</div>
              </div>
              <StatusBadge label={usage.claude_rate_limit.status} color={rateLimitColor} />
            </div>
          }
        >
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>Rate limit reset</span>
            <span className="font-bold tabular-nums text-foreground">
              {fmtCountdown(usage.claude_rate_limit.seconds_until_reset, nowMs, usage.claude_rate_limit.reset_at)}
            </span>
          </div>
        </StatCard>

        <StatCard
          label="Token Budget"
          animateValue={tokenBudget.used}
          formatAnimatedValue={(v) => fmtNum(Math.round(v))}
          subtitle="Last 24h tokens across recent sessions"
          accentColor="hsl(var(--primary))"
          footer={tokenBudget.capacity > 0 ? `${fmtNum(tokenBudget.remaining)} remaining capacity` : 'Context capacity unavailable'}
        >
          <ProgressBar value={tokenBudget.pct} color="hsl(var(--primary))" />
          <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
            <span>{fmtPct(tokenBudget.pct)} of active context capacity</span>
            <span>{tokenBudget.capacity > 0 ? fmtNum(tokenBudget.capacity) : '—'} total</span>
          </div>
        </StatCard>

        <StatCard
          label="Cost (7d)"
          accentColor="hsl(var(--chart-2))"
          footer={claudeCosts ? `${fmtNum(claudeCosts.total_tokens_7d)} tokens over 7d` : 'CodexBar data unavailable'}
          value={
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="text-[30px] font-extrabold tracking-tight text-foreground">
                  {claudeCosts ? fmtCurrency(claudeCosts.total_cost_7d) : '—'}
                </div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {claudeCosts?.error ? 'CodexBar feed degraded' : 'Daily spend trend'}
                </div>
              </div>
              <div className={`shrink-0 ${mobile ? 'h-14 w-24' : 'h-14 w-[120px]'}`}>
                {dailyCostSeries.length > 0 ? (
                  <InteractiveAreaChart
                    data={dailyCostSeries}
                    areas={[{ dataKey: 'cost', color: 'hsl(var(--chart-2))', label: 'Cost' }]}
                    xKey="label"
                    height={56}
                    animationDuration={800}
                  />
                ) : (
                  <div className="h-full rounded-lg border border-border bg-muted" />
                )}
              </div>
            </div>
          }
        />

        <StatCard
          label="Active Sessions"
          animateValue={activeSessionsLastHour.length}
          subtitle="Updated within the last hour"
          accentColor="hsl(var(--chart-3))"
          footer={`${fmtNum(usage.totals.session_count)} sessions total`}
        >
          <div className="flex flex-col gap-1.5">
            {activeSessionsLastHour.slice(0, 3).map((session) => (
              <div key={session.key} className="flex items-center justify-between gap-2 text-xs">
                <span className="truncate text-foreground">{session.label}</span>
                <span className="text-muted-foreground">{fmtCompact(session.total_tokens)}</span>
              </div>
            ))}
            {activeSessionsLastHour.length === 0 && (
              <div className="text-xs text-muted-foreground">No sessions updated in the last hour.</div>
            )}
          </div>
        </StatCard>
      </section>

      {/* Token Burn Chart */}
      <ChartPanel
        title="Token Burn"
        subtitle={`${fmtCompact(Math.round(usage.windows.last_24h?.burn_rate_tokens_per_hour ?? 0))} tokens/hour avg · last 24h in ${usage.trend.bucket_minutes}-minute buckets`}
        height={mobile ? 240 : 320}
        className="mb-4"
        actions={
          <ChartControls
            showBrush={showBurnBrush}
            onBrushToggle={setShowBurnBrush}
            exportData={() => downloadCSV(burnTrend as Record<string, unknown>[], 'token-burn.csv')}
          />
        }
      >
        <InteractiveAreaChart
          data={burnTrend}
          areas={[{ dataKey: 'tokens', color: 'hsl(var(--primary))', label: 'Tokens' }]}
          xKey="label"
          formatY={(v) => fmtCompact(v)}
          showBrush={showBurnBrush}
          height={mobile ? 220 : 300}
        />
      </ChartPanel>

      {/* Session Activity + Cost Breakdown */}
      <section className={`mb-4 grid gap-4 ${mobile ? 'grid-cols-1' : 'grid-cols-[1.6fr_minmax(320px,1fr)]'}`}>
        <div className="rounded-xl border border-border bg-card p-4 shadow-lg">
          <div className="mb-3.5 flex flex-wrap items-baseline justify-between gap-3">
            <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Session Activity</div>
            <div className="text-xs text-muted-foreground">Sorted by estimated burn rate with freshness coloring</div>
          </div>
          {mobile ? (
            <div className="flex flex-col gap-2.5">
              {sessionRows.map((session) => {
                const hoursSince = session.updated_at ? (nowMs - new Date(session.updated_at).getTime()) / 3_600_000 : null
                const color = getRecencyColor(hoursSince)
                return (
                  <div key={session.key} className="rounded-lg border border-border bg-muted/30 p-3">
                    <div className="mb-2 flex items-center gap-2">
                      <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color, boxShadow: `0 0 12px ${color}55` }} />
                      <span className="truncate text-sm font-semibold text-foreground">{session.label}</span>
                      <span className="ml-auto text-xs font-semibold" style={{ color }}>{fmtRelativeFromNow(session.updated_at, nowMs)}</span>
                    </div>
                    <div className="mb-1 truncate text-xs text-muted-foreground">{session.model || '—'}</div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
                      <span className="text-foreground"><span className="text-muted-foreground">Tokens </span>{fmtNum(session.total_tokens)}</span>
                      <span className="text-foreground"><span className="text-muted-foreground">Share </span>{fmtPct(session.share_pct ?? 0)}</span>
                      <span className="text-foreground"><span className="text-muted-foreground">Burn </span>{fmtCompact(Math.round(session.burn_rate_24h_est ?? 0))}/h</span>
                    </div>
                  </div>
                )
              })}
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full border-collapse">
                <thead>
                  <tr>
                    {['Session', 'Model', 'Tokens Used', 'Share', 'Burn Rate', 'Last Active'].map((col, i) => (
                      <th key={col} className={`border-b border-border px-3 py-2.5 text-left text-[11px] font-bold uppercase tracking-wider text-muted-foreground ${i === 0 ? 'w-[28%]' : ''}`}>
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sessionRows.map((session) => {
                    const hoursSince = session.updated_at ? (nowMs - new Date(session.updated_at).getTime()) / 3_600_000 : null
                    const color = getRecencyColor(hoursSince)
                    return (
                      <tr key={session.key} className="transition-colors hover:bg-muted/30">
                        <td className="border-b border-border px-3 py-3.5 align-top text-sm tabular-nums text-foreground">
                          <div className="flex items-center gap-2.5">
                            <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: color, boxShadow: `0 0 12px ${color}55` }} />
                            <div className="min-w-0">
                              <div className="truncate font-semibold text-foreground">{session.label}</div>
                              <div className="mt-0.5 text-[11px] text-muted-foreground">{session.key.slice(0, 12)}…</div>
                            </div>
                          </div>
                        </td>
                        <td className="max-w-[220px] truncate border-b border-border px-3 py-3.5 align-top text-sm tabular-nums text-muted-foreground">{session.model || '—'}</td>
                        <td className="border-b border-border px-3 py-3.5 align-top text-sm tabular-nums text-foreground">{fmtNum(session.total_tokens)}</td>
                        <td className="border-b border-border px-3 py-3.5 align-top text-sm tabular-nums text-foreground">{fmtPct(session.share_pct ?? 0)}</td>
                        <td className="border-b border-border px-3 py-3.5 align-top text-sm tabular-nums text-foreground">{fmtCompact(Math.round(session.burn_rate_24h_est ?? 0))}/h</td>
                        <td className="border-b border-border px-3 py-3.5 align-top text-sm tabular-nums text-foreground">
                          <div className="font-semibold" style={{ color }}>{fmtRelativeFromNow(session.updated_at, nowMs)}</div>
                          <div className="mt-0.5 text-[11px] text-muted-foreground">{fmtDateTime(session.updated_at)}</div>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="flex flex-col gap-4">
          <div className="rounded-xl border border-border bg-card p-4 shadow-lg">
            <div className="mb-3.5 flex flex-wrap items-baseline justify-between gap-3">
              <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground">Cost Breakdown</div>
              <div className="text-xs text-muted-foreground">
                {claudeCosts ? `${fmtCurrency(claudeCosts.total_cost_7d)} total over the last 7 days` : 'No cost data available'}
              </div>
            </div>
            <div className={`flex gap-3 ${mobile ? 'flex-col' : 'flex-row'}`}>
              <div className={mobile ? '' : 'flex-[1_1_52%]'}>
                <div className="h-[220px]">
                  {costBreakdown.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
                        <Pie
                          data={costBreakdown}
                          dataKey="cost"
                          nameKey="model"
                          innerRadius={58}
                          outerRadius={82}
                          paddingAngle={2}
                          stroke="none"
                          {...{ activeIndex: activePieIndex, activeShape: renderActiveShape } as any}
                          onMouseEnter={(_: unknown, index: number) => setActivePieIndex(index)}
                          onMouseLeave={() => setActivePieIndex(undefined)}
                        >
                          {costBreakdown.map((entry) => (
                            <Cell key={entry.model} fill={entry.color} />
                          ))}
                        </Pie>
                        <Tooltip contentStyle={chartTooltipStyle} formatter={(value: number | string | undefined) => [fmtCurrency(Number(value ?? 0)), 'Cost']} />
                      </PieChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-border bg-muted text-xs text-muted-foreground">
                      No model cost breakdown available.
                    </div>
                  )}
                </div>
              </div>
              <div className={`flex flex-col gap-3 ${mobile ? '' : 'flex-[1_1_48%]'}`}>
                <div className="text-[28px] font-extrabold tracking-tight text-foreground">
                  {claudeCosts ? fmtCurrency(claudeCosts.total_cost_7d) : '—'}
                </div>
                <div className="text-xs text-muted-foreground">Model share of last 7 days</div>
                <div className="flex flex-col gap-2">
                  {costBreakdown.slice(0, 5).map((entry) => {
                    const pct = claudeCosts && claudeCosts.total_cost_7d > 0 ? (entry.cost / claudeCosts.total_cost_7d) * 100 : 0
                    return (
                      <div key={entry.model}>
                        <div className="mb-1 flex items-center justify-between gap-2 text-xs">
                          <span className="truncate text-foreground">{entry.model}</span>
                          <span className="font-medium text-foreground">{fmtCurrency(entry.cost)}</span>
                        </div>
                        <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                          <div className="h-full rounded-full transition-all duration-700" style={{ width: `${pct}%`, background: entry.color }} />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>

            <div className="mt-4">
              <div className="mb-2.5 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">Daily Cost</div>
              <div className="h-[180px]">
                {dailyCostSeries.length > 0 ? (
                  <InteractiveBarChart
                    data={dailyCostSeries}
                    bars={[{ dataKey: 'cost', color: 'hsl(var(--primary))', label: 'Cost' }]}
                    xKey="label"
                    formatY={(v) => `$${v.toFixed(0)}`}
                    height={170}
                    showSortToggle={false}
                  />
                ) : (
                  <div className="flex h-full items-center justify-center rounded-xl border border-dashed border-border bg-muted text-xs text-muted-foreground">
                    No daily cost history available.
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* System Health */}
      <section className="rounded-xl border border-border bg-card p-4 shadow-lg">
        <div className="mb-3.5 flex flex-wrap items-baseline justify-between gap-3">
          <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground">System Health</div>
          <div className="text-xs text-muted-foreground">Best-effort status from existing endpoints only</div>
        </div>
        <div className={`grid gap-3 ${mobile ? 'grid-cols-1' : 'grid-cols-3'}`}>
          {healthRows.map((row) => (
            <div key={row.label} className="card-hover rounded-xl border border-border bg-muted p-3.5">
              <div className="mb-2.5 flex items-center justify-between gap-2.5">
                <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{row.label}</div>
                <StatusBadge label={row.status} color={row.color} subtle />
              </div>
              <div className="text-xs leading-relaxed text-muted-foreground">{row.detail}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
