import React, { useEffect, useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import {
  API,
  buildHealthRows,
  C,
  emptyChartStyle,
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
  LoadingState,
  metricCardSpan,
  MetricCard,
  panelStyle,
  ProgressBar,
  SectionHeader,
  StatusPill,
  tableCellStyle,
  tableHeadStyle,
  tooltipStyle,
  type ClaudeCosts,
  type HealthData,
  type TableInfo,
  type UsageData,
} from './dashboardSupport'

type DashboardProps = { mobile: boolean }

export default function Dashboard({ mobile }: DashboardProps) {
  const [usage, setUsage] = useState<UsageData | null>(null)
  const [claudeCosts, setClaudeCosts] = useState<ClaudeCosts | null>(null)
  const [health, setHealth] = useState<HealthData | null>(null)
  const [tables, setTables] = useState<TableInfo[] | null>(null)
  const [loading, setLoading] = useState(true)
  const [loadFailed, setLoadFailed] = useState(false)
  const [nowMs, setNowMs] = useState(Date.now())

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
    const palette = ['#4f8cff', '#22c55e', '#a855f7', '#f59e0b', '#ef4444', '#14b8a6']
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
    return <LoadingState />
  }

  if (!usage) {
    return (
      <section style={panelStyle}>
        <div style={{ color: C.textMuted, fontSize: 13 }}>
          {loadFailed ? 'Unable to load dashboard telemetry. Refresh and sign in again.' : 'Loading dashboard telemetry…'}
        </div>
      </section>
    )
  }

  return (
    <div style={{ height: '100%', overflow: 'auto', paddingBottom: mobile ? 96 : 24 }}>
      <div style={{ display: 'flex', alignItems: mobile ? 'flex-start' : 'center', justifyContent: 'space-between', gap: 12, marginBottom: 16, flexDirection: mobile ? 'column' : 'row' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: mobile ? 22 : 26, fontWeight: 800, letterSpacing: '-0.04em', color: C.white }}>Ops Command Center</h2>
          <div style={{ marginTop: 6, fontSize: 12, color: C.textMuted }}>
            Generated {fmtDateTime(usage.freshness.generated_at)} · latest session {fmtRelativeFromNow(usage.freshness.latest_session_update_at, nowMs)} · refreshes every 30s
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', borderRadius: 999, border: `1px solid ${C.border}`, background: C.surface }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: getRateLimitColor(usage.claude_rate_limit.status), boxShadow: `0 0 12px ${getRateLimitColor(usage.claude_rate_limit.status)}66` }} />
          <span style={{ fontSize: 12, color: C.textSecondary, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Claude {usage.claude_rate_limit.status}
          </span>
          <span style={{ fontSize: 12, fontWeight: 700, color: C.white, fontVariantNumeric: 'tabular-nums' }}>
            {fmtCountdown(usage.claude_rate_limit.seconds_until_reset, nowMs, usage.claude_rate_limit.reset_at)}
          </span>
        </div>
      </div>

      <section style={{ display: 'grid', gap: 12, gridTemplateColumns: mobile ? '1fr' : 'repeat(4, minmax(0, 1fr))', marginBottom: 16 }}>
        <MetricCard
          title="API Status"
          accent={getRateLimitColor(usage.claude_rate_limit.status)}
          footer={`Reset ${fmtDateTime(usage.claude_rate_limit.reset_at)}`}
        >
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
            <div>
              <div style={{ fontSize: 26, fontWeight: 800, color: C.white, letterSpacing: '-0.03em' }}>
                {health?.status === 'ok' ? 'Online' : 'Check API'}
              </div>
              <div style={{ marginTop: 4, fontSize: 12, color: C.textSecondary, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {dominantModel}
              </div>
            </div>
            <StatusPill label={usage.claude_rate_limit.status} color={getRateLimitColor(usage.claude_rate_limit.status)} />
          </div>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12, color: C.textMuted }}>
            <span>Rate limit reset</span>
            <span style={{ color: C.white, fontVariantNumeric: 'tabular-nums' }}>
              {fmtCountdown(usage.claude_rate_limit.seconds_until_reset, nowMs, usage.claude_rate_limit.reset_at)}
            </span>
          </div>
        </MetricCard>

        <MetricCard
          title="Token Budget"
          accent={C.accent}
          footer={tokenBudget.capacity > 0 ? `${fmtNum(tokenBudget.remaining)} remaining capacity` : 'Context capacity unavailable'}
        >
          <div style={{ fontSize: 30, fontWeight: 800, color: C.white, letterSpacing: '-0.04em' }}>{fmtNum(tokenBudget.used)}</div>
          <div style={{ fontSize: 12, color: C.textSecondary }}>Last 24h tokens across recent sessions</div>
          <ProgressBar value={tokenBudget.pct} color={C.accent} />
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12, color: C.textMuted }}>
            <span>{fmtPct(tokenBudget.pct)} of active context capacity</span>
            <span>{tokenBudget.capacity > 0 ? fmtNum(tokenBudget.capacity) : '—'} total</span>
          </div>
        </MetricCard>

        <MetricCard
          title="Cost (7d)"
          accent={C.success}
          footer={claudeCosts ? `${fmtNum(claudeCosts.total_tokens_7d)} tokens over 7d` : 'CodexBar data unavailable'}
        >
          <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12 }}>
            <div>
              <div style={{ fontSize: 30, fontWeight: 800, color: C.white, letterSpacing: '-0.04em' }}>
                {claudeCosts ? fmtCurrency(claudeCosts.total_cost_7d) : '—'}
              </div>
              <div style={{ marginTop: 4, fontSize: 12, color: C.textSecondary }}>
                {claudeCosts?.error ? 'CodexBar feed degraded' : 'Daily spend trend'}
              </div>
            </div>
            <div style={{ width: mobile ? 96 : 120, height: 56, flexShrink: 0 }}>
              {dailyCostSeries.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={dailyCostSeries}>
                    <defs>
                      <linearGradient id="costSpark" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor={C.success} stopOpacity={0.8} />
                        <stop offset="100%" stopColor={C.success} stopOpacity={0.08} />
                      </linearGradient>
                    </defs>
                    <Area type="monotone" dataKey="cost" stroke={C.success} strokeWidth={2.5} fill="url(#costSpark)" />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ height: '100%', borderRadius: 10, background: C.surfaceActive, border: `1px solid ${C.border}` }} />
              )}
            </div>
          </div>
        </MetricCard>

        <MetricCard
          title="Active Sessions"
          accent={C.purple}
          footer={`${fmtNum(usage.totals.session_count)} sessions total`}
        >
          <div style={{ fontSize: 30, fontWeight: 800, color: C.white, letterSpacing: '-0.04em' }}>{activeSessionsLastHour.length}</div>
          <div style={{ fontSize: 12, color: C.textSecondary }}>Updated within the last hour</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {activeSessionsLastHour.slice(0, 3).map((session) => (
              <div key={session.key} style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12 }}>
                <span style={{ color: C.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{session.label}</span>
                <span style={{ color: C.textMuted }}>{fmtCompact(session.total_tokens)}</span>
              </div>
            ))}
            {activeSessionsLastHour.length === 0 && <div style={{ fontSize: 12, color: C.textMuted }}>No sessions updated in the last hour.</div>}
          </div>
        </MetricCard>
      </section>

      <section style={{ ...panelStyle, marginBottom: 16 }}>
        <SectionHeader
          title="Token Burn"
          subtitle={`${fmtCompact(Math.round(usage.windows.last_24h?.burn_rate_tokens_per_hour ?? 0))} tokens/hour avg · last 24h in ${usage.trend.bucket_minutes}-minute buckets`}
        />
        <div style={{ height: mobile ? 240 : 320 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={burnTrend} margin={{ top: 10, right: 8, left: 0, bottom: 0 }}>
              <defs>
                <linearGradient id="burnFill" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={C.accent} stopOpacity={0.7} />
                  <stop offset="100%" stopColor={C.accent} stopOpacity={0.05} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={C.border} vertical={false} />
              <XAxis dataKey="label" stroke={C.textMuted} tick={{ fill: C.textMuted, fontSize: 11 }} />
              <YAxis stroke={C.textMuted} tick={{ fill: C.textMuted, fontSize: 11 }} tickFormatter={(value) => fmtCompact(Number(value))} width={72} />
              <Tooltip
                contentStyle={tooltipStyle}
                cursor={{ stroke: `${C.accent}55`, strokeWidth: 1 }}
                formatter={(value: number | string | undefined) => [fmtNum(Number(value ?? 0)), 'Tokens']}
                labelFormatter={(_, payload) => fmtDateTime(payload?.[0]?.payload?.start ?? null)}
              />
              <Area type="monotone" dataKey="tokens" stroke={C.accent} strokeWidth={3} fill="url(#burnFill)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section style={{ display: 'grid', gap: 16, gridTemplateColumns: mobile ? '1fr' : 'minmax(0, 1.6fr) minmax(320px, 1fr)', marginBottom: 16 }}>
        <div style={panelStyle}>
          <SectionHeader
            title="Session Activity"
            subtitle="Sorted by estimated burn rate with freshness coloring"
          />
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: mobile ? 760 : 0 }}>
              <thead>
                <tr>
                  <th style={{ ...tableHeadStyle, width: '28%' }}>Session</th>
                  <th style={tableHeadStyle}>Model</th>
                  <th style={tableHeadStyle}>Tokens Used</th>
                  <th style={tableHeadStyle}>Share</th>
                  <th style={tableHeadStyle}>Burn Rate</th>
                  <th style={tableHeadStyle}>Last Active</th>
                </tr>
              </thead>
              <tbody>
                {sessionRows.map((session) => {
                  const hoursSince = session.updated_at ? (nowMs - new Date(session.updated_at).getTime()) / 3_600_000 : null
                  const color = getRecencyColor(hoursSince)
                  return (
                    <tr key={session.key}>
                      <td style={tableCellStyle}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <span style={{ width: 8, height: 8, borderRadius: '50%', background: color, boxShadow: `0 0 12px ${color}55`, flexShrink: 0 }} />
                          <div style={{ minWidth: 0 }}>
                            <div style={{ color: C.white, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{session.label}</div>
                            <div style={{ color: C.textMuted, fontSize: 11, marginTop: 3 }}>{session.key.slice(0, 12)}…</div>
                          </div>
                        </div>
                      </td>
                      <td style={{ ...tableCellStyle, color: C.textSecondary, maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{session.model || '—'}</td>
                      <td style={tableCellStyle}>{fmtNum(session.total_tokens)}</td>
                      <td style={tableCellStyle}>{fmtPct(session.share_pct ?? 0)}</td>
                      <td style={tableCellStyle}>{fmtCompact(Math.round(session.burn_rate_24h_est ?? 0))}/h</td>
                      <td style={tableCellStyle}>
                        <div style={{ color, fontWeight: 600 }}>{fmtRelativeFromNow(session.updated_at, nowMs)}</div>
                        <div style={{ marginTop: 3, color: C.textMuted, fontSize: 11 }}>{fmtDateTime(session.updated_at)}</div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={panelStyle}>
            <SectionHeader
              title="Cost Breakdown"
              subtitle={claudeCosts ? `${fmtCurrency(claudeCosts.total_cost_7d)} total over the last 7 days` : 'No cost data available'}
            />
            <div style={{ display: 'flex', flexDirection: mobile ? 'column' : 'row', gap: 12 }}>
              <div style={metricCardSpan(mobile, '1 1 52%')}>
                <div style={{ height: 220 }}>
                  {costBreakdown.length > 0 ? (
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Pie
                          data={costBreakdown}
                          dataKey="cost"
                          nameKey="model"
                          innerRadius={58}
                          outerRadius={82}
                          paddingAngle={2}
                          stroke="none"
                        >
                          {costBreakdown.map((entry) => (
                            <Cell key={entry.model} fill={entry.color} />
                          ))}
                        </Pie>
                        <Tooltip
                          contentStyle={tooltipStyle}
                          formatter={(value: number | string | undefined) => [fmtCurrency(Number(value ?? 0)), 'Cost']}
                        />
                      </PieChart>
                    </ResponsiveContainer>
                  ) : (
                    <div style={emptyChartStyle}>No model cost breakdown available.</div>
                  )}
                </div>
              </div>
              <div style={metricCardSpan(mobile, '1 1 48%')}>
                <div style={{ fontSize: 28, fontWeight: 800, color: C.white, letterSpacing: '-0.04em' }}>
                  {claudeCosts ? fmtCurrency(claudeCosts.total_cost_7d) : '—'}
                </div>
                <div style={{ fontSize: 12, color: C.textSecondary }}>Model share of last 7 days</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                  {costBreakdown.slice(0, 5).map((entry) => {
                    const pct = claudeCosts && claudeCosts.total_cost_7d > 0 ? (entry.cost / claudeCosts.total_cost_7d) * 100 : 0
                    return (
                      <div key={entry.model}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, fontSize: 12, marginBottom: 4 }}>
                          <span style={{ color: C.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{entry.model}</span>
                          <span style={{ color: C.white }}>{fmtCurrency(entry.cost)}</span>
                        </div>
                        <div style={{ height: 6, borderRadius: 999, overflow: 'hidden', background: C.surfaceActive }}>
                          <div style={{ width: `${pct}%`, height: '100%', borderRadius: 999, background: entry.color }} />
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>
            <div style={{ marginTop: 16 }}>
              <div style={{ fontSize: 11, color: C.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>Daily Cost</div>
              <div style={{ height: 180 }}>
                {dailyCostSeries.length > 0 ? (
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={dailyCostSeries}>
                      <CartesianGrid stroke={C.border} vertical={false} />
                      <XAxis dataKey="label" stroke={C.textMuted} tick={{ fill: C.textMuted, fontSize: 11 }} />
                      <YAxis stroke={C.textMuted} tick={{ fill: C.textMuted, fontSize: 11 }} tickFormatter={(value) => `$${Number(value).toFixed(0)}`} width={52} />
                      <Tooltip
                        contentStyle={tooltipStyle}
                        formatter={(value: number | string | undefined) => [fmtCurrency(Number(value ?? 0)), 'Cost']}
                        labelFormatter={(_, payload) => payload?.[0]?.payload?.date ?? ''}
                      />
                      <Bar dataKey="cost" radius={[8, 8, 0, 0]} fill={C.accent} />
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div style={emptyChartStyle}>No daily cost history available.</div>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>

      <section style={panelStyle}>
        <SectionHeader
          title="System Health"
          subtitle="Best-effort status from existing endpoints only"
        />
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: mobile ? '1fr' : 'repeat(3, minmax(0, 1fr))' }}>
          {healthRows.map((row) => (
            <div key={row.label} style={{ borderRadius: 14, border: `1px solid ${C.border}`, background: C.surfaceActive, padding: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10, marginBottom: 10 }}>
                <div style={{ fontSize: 11, color: C.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>{row.label}</div>
                <StatusPill label={row.status} color={row.color} subtle />
              </div>
              <div style={{ fontSize: 12, color: C.textSecondary, lineHeight: 1.5 }}>{row.detail}</div>
            </div>
          ))}
        </div>
      </section>
    </div>
  )
}
