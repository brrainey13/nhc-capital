import React, { useMemo } from 'react'
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

export interface SessionInfo {
  key: string
  label: string
  total_tokens: number
  input_tokens: number
  output_tokens: number
  context_window: number
  model: string
  updated_at: string | null
  age_hours?: number | null
  share_pct?: number
  burn_rate_24h_est?: number
}

export interface UsageData {
  sessions: SessionInfo[]
  totals: { total_tokens: number; input_tokens: number; output_tokens: number; session_count: number }
  models: Array<{
    model: string
    total_tokens: number
    input_tokens: number
    output_tokens: number
    session_count: number
    top_sessions: Array<{
      key: string
      label: string
      total_tokens: number
      updated_at: string | null
      share_within_model_pct: number
    }>
  }>
  claude_rate_limit: {
    status: 'active' | 'limited' | 'unknown'
    reset_at: string | null
    seconds_until_reset: number | null
    reason: string | null
    source: string
  }
  windows: Record<string, {
    hours: number
    session_count: number
    total_tokens: number
    input_tokens: number
    output_tokens: number
    burn_rate_tokens_per_hour: number
  }>
  top_consumers: Array<{
    key: string
    label: string
    total_tokens: number
    share_pct: number
    updated_at: string | null
    burn_rate_24h_est: number
  }>
  trend: {
    window_hours: number
    bucket_minutes: number
    buckets: Array<{ start: string | null; end: string | null; session_count: number; total_tokens: number }>
  }
  freshness: { generated_at: string; latest_session_update_at: string | null; staleness_seconds: number | null }
}

export interface OAuthUsage {
  five_hour?: { utilization: number; resets_at: string }
  seven_day?: { utilization: number; resets_at: string }
  extra_usage?: { is_enabled: boolean; monthly_limit: number; used_credits: number }
}

export interface ClaudeCosts {
  daily_costs: Array<{ date: string; cost: number; tokens: number }>
  total_cost_7d: number
  total_tokens_7d: number
  models_7d: Record<string, { tokens: number; cost: number }>
  fetched_at: string
  error?: string
  oauth?: OAuthUsage
}

export interface HealthData {
  status?: string
}

const C = {
  bg: '#0f1117',
  surface: '#181a20',
  surfaceHover: '#1e2028',
  surfaceActive: '#252830',
  border: '#2a2d37',
  borderLight: '#333642',
  text: '#e4e5e9',
  textSecondary: '#8b8f9a',
  textMuted: '#5f6370',
  accent: '#4f8cff',
  accentDim: '#3a6fd8',
  accentBg: 'rgba(79,140,255,0.08)',
  white: '#ffffff',
  danger: '#ef4444',
  dangerBg: 'rgba(239,68,68,0.1)',
  success: '#22c55e',
  purple: '#a855f7',
  purpleBg: 'rgba(168,85,247,0.08)',
  warning: '#f59e0b',
  warningBg: 'rgba(245,158,11,0.12)',
}

const PIE_COLORS = [C.accent, '#60a5fa', '#34d399', '#f59e0b', '#f87171', '#a78bfa']

function fmtNum(n: number): string {
  return n.toLocaleString()
}

function fmtCompact(n: number): string {
  if (Math.abs(n) >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (Math.abs(n) >= 1_000) return `${(n / 1_000).toFixed(1)}K`
  return String(Math.round(n))
}

function fmtMoney(value: number): string {
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function fmtPct(value: number, digits = 1): string {
  return `${value.toFixed(digits)}%`
}

function fmtDateTime(iso: string | null): string {
  if (!iso) return 'Unavailable'
  return new Date(iso).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function fmtTime(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleTimeString([], {
    timeZone: 'America/New_York',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function fmtRelative(iso: string | null): string {
  if (!iso) return 'Unknown'
  const diffSeconds = Math.max(Math.floor((Date.now() - new Date(iso).getTime()) / 1000), 0)
  if (diffSeconds < 60) return `${diffSeconds}s ago`
  const mins = Math.floor(diffSeconds / 60)
  if (mins < 60) return `${mins}m ago`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours}h ago`
  return `${Math.floor(hours / 24)}d ago`
}

function fmtCountdown(seconds: number | null): string {
  if (seconds == null) return 'Unavailable'
  const safe = Math.max(seconds, 0)
  const hours = Math.floor(safe / 3600)
  const mins = Math.floor((safe % 3600) / 60)
  const secs = safe % 60
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`
}

function sessionAgeHours(updatedAt: string | null): number | null {
  if (!updatedAt) return null
  return Math.max((Date.now() - new Date(updatedAt).getTime()) / 3_600_000, 0)
}

function statusColorFromAge(hours: number | null): string {
  if (hours == null) return C.textMuted
  if (hours < 1) return C.success
  if (hours < 6) return C.warning
  return C.textMuted
}

function statusLabelFromAge(hours: number | null): string {
  if (hours == null) return 'Unknown'
  if (hours < 1) return 'Active'
  if (hours < 6) return 'Warm'
  return 'Stale'
}

function topModelName(usage: UsageData): string {
  return usage.models[0]?.model || usage.sessions[0]?.model || 'claude-opus-4-6'
}

type DashboardProps = {
  mobile: boolean
  usage: UsageData | null
  usageLoadFailed: boolean
  claudeCosts: ClaudeCosts | null
  health: HealthData | null
  healthLoadFailed: boolean
  nowMs: number
}

export default function Dashboard({
  mobile,
  usage,
  usageLoadFailed,
  claudeCosts,
  health,
  healthLoadFailed,
  nowMs,
}: DashboardProps) {
  const recentSessions = useMemo(
    () => (usage?.sessions ?? [])
      .filter((session) => {
        const age = sessionAgeHours(session.updated_at)
        return age != null && age < 1
      })
      .sort((a, b) => (b.burn_rate_24h_est ?? 0) - (a.burn_rate_24h_est ?? 0)),
    [usage],
  )

  const sessionRows = useMemo(
    () => (usage?.sessions ?? [])
      .slice()
      .sort((a, b) => {
        const burnDiff = (b.burn_rate_24h_est ?? 0) - (a.burn_rate_24h_est ?? 0)
        if (burnDiff !== 0) return burnDiff
        return (b.total_tokens ?? 0) - (a.total_tokens ?? 0)
      }),
    [usage],
  )

  const trendData = useMemo(
    () => (usage?.trend.buckets ?? []).map((bucket) => ({
      label: fmtTime(bucket.start),
      fullLabel: bucket.start ? new Date(bucket.start).toLocaleString([], {
        timeZone: 'America/New_York',
        month: 'short',
        day: 'numeric',
        hour: 'numeric',
      }) : 'Unknown',
      tokens: bucket.total_tokens,
      sessions: bucket.session_count,
    })),
    [usage],
  )

  const totalContextCapacity = useMemo(
    () => recentSessions.reduce((sum, session) => sum + (session.context_window || 0), 0),
    [recentSessions],
  )

  const tokenBudgetUsed = usage?.windows.last_24h?.total_tokens ?? 0
  const tokenBudgetPct = totalContextCapacity > 0
    ? Math.min((tokenBudgetUsed / totalContextCapacity) * 100, 100)
    : 0
  const tokenBudgetRemaining = Math.max(totalContextCapacity - tokenBudgetUsed, 0)

  const sparklineData = claudeCosts?.daily_costs ?? []
  const donutData = useMemo(
    () => Object.entries(claudeCosts?.models_7d ?? {})
      .map(([model, data]) => ({ model, cost: data.cost, tokens: data.tokens }))
      .sort((a, b) => b.cost - a.cost),
    [claudeCosts],
  )

  const burnRate = usage?.windows.last_24h?.burn_rate_tokens_per_hour ?? 0
  const rateLimitCountdown = usage?.claude_rate_limit.reset_at
    ? Math.max(Math.floor((new Date(usage.claude_rate_limit.reset_at).getTime() - nowMs) / 1000), 0)
    : usage?.claude_rate_limit.seconds_until_reset ?? null

  if (!usage) {
    return (
      <div style={{ ...panel, minHeight: 180, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ color: C.textMuted, fontSize: 13 }}>
          {usageLoadFailed ? 'Unable to load dashboard data. Refresh and sign in again.' : 'Loading dashboard…'}
        </div>
      </div>
    )
  }

  return (
    <div style={{ height: '100%', overflow: 'auto', paddingBottom: mobile ? 24 : 12 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: mobile ? 'flex-start' : 'center', gap: 12, marginBottom: 16, flexDirection: mobile ? 'column' : 'row' }}>
        <div>
          <h2 style={{ fontSize: mobile ? 20 : 24, fontWeight: 800, margin: '0 0 4px', color: C.white, letterSpacing: '-0.03em' }}>Ops Command Center</h2>
          <div style={{ fontSize: 12, color: C.textMuted }}>
            Refreshed {fmtDateTime(usage.freshness.generated_at)} · latest session {fmtRelative(usage.freshness.latest_session_update_at)}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
          <Badge tone={usage.claude_rate_limit.status === 'limited' ? 'danger' : usage.claude_rate_limit.status === 'active' ? 'success' : 'muted'}>
            Claude {usage.claude_rate_limit.status}
          </Badge>
          <Badge tone={health?.status === 'ok' ? 'success' : healthLoadFailed ? 'danger' : 'muted'}>
            API {health?.status === 'ok' ? 'healthy' : healthLoadFailed ? 'unreachable' : 'checking'}
          </Badge>
        </div>
      </div>

      <div style={{ display: 'grid', gap: 14, gridTemplateColumns: mobile ? '1fr' : 'repeat(4, minmax(0, 1fr))', marginBottom: 14 }}>
        <MetricCard
          title="API Status"
          value={health?.status === 'ok' ? 'Operational' : healthLoadFailed ? 'Offline' : 'Checking'}
          accent={health?.status === 'ok' ? C.success : healthLoadFailed ? C.danger : C.textSecondary}
          footer={`${topModelName(usage)} · ${usage.claude_rate_limit.status.toUpperCase()}`}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <StatusDot color={health?.status === 'ok' ? C.success : healthLoadFailed ? C.danger : C.textMuted} />
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 12, color: C.textSecondary }}>Rate limit reset</div>
              <div style={{ fontSize: 18, fontWeight: 700, color: C.white, fontVariantNumeric: 'tabular-nums' }}>{fmtCountdown(rateLimitCountdown)}</div>
            </div>
          </div>
        </MetricCard>

        <MetricCard
          title="Token Budget"
          value={fmtNum(tokenBudgetUsed)}
          accent={C.white}
          footer={totalContextCapacity > 0 ? `${fmtPct(tokenBudgetPct)} of active context capacity` : 'Context capacity unavailable'}
        >
          <ProgressBar value={tokenBudgetPct} color={tokenBudgetPct > 85 ? C.danger : tokenBudgetPct > 60 ? C.warning : C.accent} />
          <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontSize: 12, color: C.textSecondary }}>
            <span>Remaining {fmtNum(tokenBudgetRemaining)}</span>
            <span>Cap {fmtNum(totalContextCapacity)}</span>
          </div>
        </MetricCard>

        <MetricCard
          title="Cost (7d)"
          value={claudeCosts ? fmtMoney(claudeCosts.total_cost_7d) : '—'}
          accent={C.accent}
          footer={claudeCosts ? `${fmtNum(claudeCosts.total_tokens_7d)} tokens in 7d` : 'Waiting for CodexBar'}
        >
          <div style={{ height: 56, marginTop: 6 }}>
            {sparklineData.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <AreaChart data={sparklineData}>
                  <defs>
                    <linearGradient id="costSpark" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor={C.accent} stopOpacity={0.65} />
                      <stop offset="100%" stopColor={C.accent} stopOpacity={0.05} />
                    </linearGradient>
                  </defs>
                  <Area type="monotone" dataKey="cost" stroke={C.accent} fill="url(#costSpark)" strokeWidth={2} />
                </AreaChart>
              </ResponsiveContainer>
            ) : (
              <div style={{ height: '100%', display: 'flex', alignItems: 'center', color: C.textMuted, fontSize: 12 }}>
                {claudeCosts?.error ? 'Cost feed unavailable' : 'Waiting for daily costs'}
              </div>
            )}
          </div>
        </MetricCard>

        <MetricCard
          title="Active Sessions"
          value={String(usage.windows.last_1h?.session_count ?? recentSessions.length)}
          accent={C.white}
          footer={`${recentSessions.length} updated in the last hour`}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 6 }}>
            {(recentSessions.slice(0, 3)).map((session) => (
              <div key={session.key} style={{ display: 'flex', justifyContent: 'space-between', gap: 10, fontSize: 12 }}>
                <span style={{ color: C.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{session.label}</span>
                <span style={{ color: C.textMuted }}>{fmtCompact(session.burn_rate_24h_est ?? 0)}/h</span>
              </div>
            ))}
            {recentSessions.length === 0 && <div style={{ fontSize: 12, color: C.textMuted }}>No sessions active in the last hour.</div>}
          </div>
        </MetricCard>
      </div>

      <section style={{ ...panel, marginBottom: 14 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: mobile ? 'flex-start' : 'center', gap: 10, marginBottom: 14, flexDirection: mobile ? 'column' : 'row' }}>
          <div>
            <div style={eyebrow}>Token Burn</div>
            <div style={{ fontSize: 22, fontWeight: 700, color: C.white, letterSpacing: '-0.03em' }}>24-hour usage curve</div>
          </div>
          <div style={{ fontSize: 13, color: C.textSecondary }}>
            {fmtCompact(Math.round(burnRate))} tokens/hour avg
          </div>
        </div>
        <div style={{ height: mobile ? 240 : 320 }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={trendData}>
              <defs>
                <linearGradient id="tokenBurn" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={C.accent} stopOpacity={0.55} />
                  <stop offset="100%" stopColor={C.accent} stopOpacity={0.04} />
                </linearGradient>
              </defs>
              <CartesianGrid stroke={C.border} vertical={false} />
              <XAxis dataKey="label" stroke={C.textMuted} tick={{ fontSize: 11 }} />
              <YAxis stroke={C.textMuted} tick={{ fontSize: 11 }} tickFormatter={(value) => fmtCompact(Number(value))} width={mobile ? 44 : 60} />
              <Tooltip
                contentStyle={tooltipStyle}
                formatter={(value) => [fmtNum(Number(value ?? 0)), 'Tokens']}
                labelFormatter={(_, payload) => payload?.[0]?.payload?.fullLabel || 'Unknown'}
              />
              <Area type="monotone" dataKey="tokens" stroke={C.accent} fill="url(#tokenBurn)" strokeWidth={3} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </section>

      <div style={{ display: 'grid', gap: 14, gridTemplateColumns: mobile ? '1fr' : 'minmax(0, 1.6fr) minmax(340px, 1fr)', marginBottom: 14 }}>
        <section style={{ ...panel, overflow: 'hidden' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 10, marginBottom: 12 }}>
            <div>
              <div style={eyebrow}>Session Activity</div>
              <div style={{ fontSize: 20, fontWeight: 700, color: C.white, letterSpacing: '-0.02em' }}>Live session ranking</div>
            </div>
            <div style={{ fontSize: 12, color: C.textMuted }}>Sorted by burn rate</div>
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', minWidth: 720 }}>
              <thead>
                <tr>
                  {['Session', 'Model', 'Tokens Used', 'Share', 'Burn Rate', 'Last Active'].map((label) => (
                    <th key={label} style={th}>{label}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sessionRows.map((session) => {
                  const age = sessionAgeHours(session.updated_at)
                  return (
                    <tr key={session.key}>
                      <td style={td}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                          <StatusDot color={statusColorFromAge(age)} />
                          <div>
                            <div style={{ color: C.white, fontWeight: 600 }}>{session.label}</div>
                            <div style={{ color: C.textMuted, fontSize: 11 }}>{statusLabelFromAge(age)}</div>
                          </div>
                        </div>
                      </td>
                      <td style={tdMuted}>{session.model || 'Unknown'}</td>
                      <td style={td}>{fmtNum(session.total_tokens)}</td>
                      <td style={td}>{fmtPct(session.share_pct ?? 0)}</td>
                      <td style={td}>{fmtCompact(session.burn_rate_24h_est ?? 0)}/h</td>
                      <td style={tdMuted}>{fmtRelative(session.updated_at)}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </section>

        <section style={{ ...panel, display: 'grid', gap: 14, alignContent: 'start' }}>
          <div>
            <div style={eyebrow}>Cost Breakdown</div>
            <div style={{ fontSize: 20, fontWeight: 700, color: C.white, letterSpacing: '-0.02em' }}>Seven-day model mix</div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: mobile ? '1fr' : '190px 1fr', gap: 14, alignItems: 'center' }}>
            <div style={{ height: 190 }}>
              {donutData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie data={donutData} dataKey="cost" nameKey="model" innerRadius={52} outerRadius={78} paddingAngle={2}>
                      {donutData.map((entry, index) => (
                        <Cell key={entry.model} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={tooltipStyle} formatter={(value) => [fmtMoney(Number(value ?? 0)), 'Cost']} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', color: C.textMuted, fontSize: 12 }}>
                  No model cost data
                </div>
              )}
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div style={{ fontSize: 28, fontWeight: 800, color: C.white, letterSpacing: '-0.04em' }}>{claudeCosts ? fmtMoney(claudeCosts.total_cost_7d) : '—'}</div>
              <div style={{ fontSize: 12, color: C.textMuted }}>Total cost over the last 7 days</div>
              {donutData.slice(0, 5).map((row, index) => (
                <div key={row.model} style={{ display: 'grid', gridTemplateColumns: '12px minmax(0, 1fr) auto', gap: 10, alignItems: 'center', fontSize: 12 }}>
                  <span style={{ width: 12, height: 12, borderRadius: 999, background: PIE_COLORS[index % PIE_COLORS.length] }} />
                  <span style={{ color: C.text, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.model}</span>
                  <span style={{ color: C.textSecondary }}>{fmtMoney(row.cost)}</span>
                </div>
              ))}
            </div>
          </div>
          <div style={{ height: 180 }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={sparklineData}>
                <CartesianGrid stroke={C.border} vertical={false} />
                <XAxis dataKey="date" stroke={C.textMuted} tick={{ fontSize: 11 }} tickFormatter={(value) => new Date(`${value}T12:00:00`).toLocaleDateString([], { weekday: 'short' })} />
                <YAxis stroke={C.textMuted} tick={{ fontSize: 11 }} tickFormatter={(value) => `$${Number(value).toFixed(0)}`} width={44} />
                <Tooltip
                  contentStyle={tooltipStyle}
                  formatter={(value, _, item) => [fmtMoney(Number(value ?? 0)), item?.payload?.tokens ? `${fmtNum(item.payload.tokens)} tokens` : 'Cost']}
                  labelFormatter={(label) => fmtDateTime(label ? `${label}T12:00:00` : null)}
                />
                <Bar dataKey="cost" radius={[6, 6, 0, 0]} fill={C.accent} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </section>
      </div>

      <section style={panel}>
        <div style={{ marginBottom: 12 }}>
          <div style={eyebrow}>System Health</div>
          <div style={{ fontSize: 20, fontWeight: 700, color: C.white, letterSpacing: '-0.02em' }}>Operational checks</div>
        </div>
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: mobile ? '1fr' : 'repeat(4, minmax(0, 1fr))' }}>
          <HealthCard
            label="Cloudflare Tunnel"
            value={health?.status === 'ok' ? 'Protected' : 'Unknown'}
            tone={health?.status === 'ok' ? 'success' : 'muted'}
            sub={health?.status === 'ok' ? 'API reachable behind Access' : 'Tunnel runtime not exposed by API'}
          />
          <HealthCard
            label="Database"
            value={health?.status === 'ok' ? 'Connected' : 'Unknown'}
            tone={health?.status === 'ok' ? 'success' : 'muted'}
            sub={health?.status === 'ok' ? 'Backend responding to health checks' : 'Connection detail not exposed'}
          />
          <HealthCard
            label="Cron Jobs"
            value={usage.freshness.staleness_seconds != null && usage.freshness.staleness_seconds < 3600 ? 'Fresh data' : 'Unknown'}
            tone={usage.freshness.staleness_seconds != null && usage.freshness.staleness_seconds < 3600 ? 'success' : 'warning'}
            sub={usage.freshness.latest_session_update_at ? `Latest update ${fmtRelative(usage.freshness.latest_session_update_at)}` : 'Last run times not exposed'}
          />
          <HealthCard
            label="Git / Deploy"
            value="Not exposed"
            tone="muted"
            sub="Branch, SHA, and deploy status are not returned by current API"
          />
        </div>
      </section>
    </div>
  )
}

function MetricCard({
  title,
  value,
  footer,
  accent,
  children,
}: {
  title: string
  value: string
  footer: string
  accent: string
  children?: React.ReactNode
}) {
  return (
    <section style={{ ...panel, minHeight: 174 }}>
      <div style={eyebrow}>{title}</div>
      <div style={{ fontSize: 30, fontWeight: 800, color: accent, letterSpacing: '-0.04em', marginBottom: 6 }}>{value}</div>
      <div style={{ fontSize: 12, color: C.textSecondary, minHeight: 18 }}>{footer}</div>
      {children}
    </section>
  )
}

function Badge({ children, tone }: { children: React.ReactNode; tone: 'success' | 'danger' | 'muted' }) {
  const toneStyle = tone === 'success'
    ? { color: C.success, background: 'rgba(34,197,94,0.12)', borderColor: 'rgba(34,197,94,0.24)' }
    : tone === 'danger'
      ? { color: C.danger, background: C.dangerBg, borderColor: 'rgba(239,68,68,0.22)' }
      : { color: C.textSecondary, background: C.surfaceActive, borderColor: C.borderLight }
  return (
    <div style={{ ...toneStyle, borderWidth: 1, borderStyle: 'solid', borderRadius: 999, padding: '8px 12px', fontSize: 11, fontWeight: 700, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
      {children}
    </div>
  )
}

function ProgressBar({ value, color }: { value: number; color: string }) {
  return (
    <div style={{ marginTop: 12, height: 10, background: C.surfaceActive, borderRadius: 999, overflow: 'hidden' }}>
      <div style={{ width: `${Math.max(0, Math.min(value, 100))}%`, height: '100%', background: color, borderRadius: 999, transition: 'width 0.25s ease' }} />
    </div>
  )
}

function StatusDot({ color }: { color: string }) {
  return <span style={{ width: 10, height: 10, borderRadius: 999, background: color, boxShadow: `0 0 0 4px ${color}22`, flexShrink: 0 }} />
}

function HealthCard({
  label,
  value,
  sub,
  tone,
}: {
  label: string
  value: string
  sub: string
  tone: 'success' | 'warning' | 'muted'
}) {
  const valueColor = tone === 'success' ? C.success : tone === 'warning' ? C.warning : C.white
  return (
    <div style={{ background: C.surfaceActive, border: `1px solid ${C.borderLight}`, borderRadius: 12, padding: 14 }}>
      <div style={eyebrow}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: valueColor, letterSpacing: '-0.03em', marginBottom: 6 }}>{value}</div>
      <div style={{ fontSize: 12, color: C.textMuted }}>{sub}</div>
    </div>
  )
}

const panel: React.CSSProperties = {
  background: C.surface,
  border: `1px solid ${C.border}`,
  borderRadius: 16,
  padding: 16,
  boxShadow: '0 18px 40px rgba(0,0,0,0.24)',
}

const eyebrow: React.CSSProperties = {
  fontSize: 11,
  color: C.textMuted,
  marginBottom: 8,
  textTransform: 'uppercase',
  letterSpacing: '0.08em',
  fontWeight: 700,
}

const th: React.CSSProperties = {
  textAlign: 'left',
  padding: '0 0 10px',
  borderBottom: `1px solid ${C.border}`,
  fontSize: 11,
  color: C.textMuted,
  textTransform: 'uppercase',
  letterSpacing: '0.07em',
  fontWeight: 700,
}

const td: React.CSSProperties = {
  padding: '12px 0',
  borderBottom: `1px solid ${C.border}`,
  fontSize: 13,
  color: C.text,
  verticalAlign: 'middle',
}

const tdMuted: React.CSSProperties = {
  ...td,
  color: C.textSecondary,
}

const tooltipStyle: React.CSSProperties = {
  background: C.surface,
  border: `1px solid ${C.borderLight}`,
  borderRadius: 10,
  color: C.text,
}
