import React from 'react'

export const API = '/api'
export const EST = 'America/New_York'

export const C = {
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
}

export type SessionInfo = {
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

export type UsageData = {
  sessions: SessionInfo[]
  totals: {
    total_tokens: number
    input_tokens: number
    output_tokens: number
    session_count: number
  }
  models: Array<{
    model: string
    total_tokens: number
    input_tokens: number
    output_tokens: number
    session_count: number
  }>
  claude_rate_limit: {
    status: 'active' | 'limited' | 'unknown'
    reset_at: string | null
    seconds_until_reset: number | null
    reason: string | null
    source: string
  }
  windows: Record<
    string,
    {
      hours: number
      session_count: number
      total_tokens: number
      input_tokens: number
      output_tokens: number
      burn_rate_tokens_per_hour: number
    }
  >
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
    buckets: Array<{
      start: string | null
      end: string | null
      session_count: number
      total_tokens: number
    }>
  }
  freshness: {
    generated_at: string
    latest_session_update_at: string | null
    staleness_seconds: number | null
  }
}

export type OAuthUsage = {
  five_hour?: { utilization: number; resets_at: string }
  seven_day?: { utilization: number; resets_at: string }
  extra_usage?: { is_enabled: boolean; monthly_limit: number; used_credits: number }
}

export type ClaudeCosts = {
  daily_costs: Array<{ date: string; cost: number; tokens: number }>
  total_cost_7d: number
  total_tokens_7d: number
  models_7d: Record<string, { tokens: number; cost: number }>
  fetched_at: string
  error?: string
  oauth?: OAuthUsage
}

export type HealthData = { status?: string }
export type TableInfo = { name: string; row_count: number }
export type HealthRow = { label: string; status: string; color: string; detail: string }

export function fmtNum(value: number): string {
  return value.toLocaleString()
}

export function fmtCurrency(value: number): string {
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

export function fmtCompact(value: number): string {
  return value.toLocaleString(undefined, {
    notation: 'compact',
    maximumFractionDigits: value >= 1000 ? 1 : 0,
  })
}

export function fmtPct(value: number): string {
  return `${value.toFixed(1)}%`
}

export function fmtDateTime(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function fmtTimeEst(value: string | null): string {
  if (!value) return '—'
  return new Date(value).toLocaleTimeString([], {
    timeZone: EST,
    hour: 'numeric',
    minute: '2-digit',
  })
}

export function fmtDayLabel(value: string): string {
  return new Date(`${value}T12:00:00`).toLocaleDateString([], {
    timeZone: EST,
    weekday: 'short',
  })
}

export function fmtRelativeFromNow(value: string | null, nowMs: number): string {
  if (!value) return '—'
  const seconds = Math.max(Math.floor((nowMs - new Date(value).getTime()) / 1000), 0)
  if (seconds < 60) return `${seconds}s ago`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function fmtCountdown(seconds: number | null, nowMs: number, resetAt: string | null): string {
  if (!resetAt) return 'Unavailable'
  const fallback = seconds ?? Math.max(Math.floor((new Date(resetAt).getTime() - nowMs) / 1000), 0)
  const safe = Math.max(fallback, 0)
  const hours = Math.floor(safe / 3600)
  const minutes = Math.floor((safe % 3600) / 60)
  const remainingSeconds = safe % 60
  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(remainingSeconds).padStart(2, '0')}`
}

export function getRecencyColor(hours: number | null): string {
  if (hours == null) return C.textMuted
  if (hours < 1) return C.success
  if (hours < 6) return '#f59e0b'
  return C.textMuted
}

export function getRateLimitColor(status: UsageData['claude_rate_limit']['status']): string {
  if (status === 'active') return C.success
  if (status === 'limited') return C.danger
  return C.textMuted
}

export function metricCardSpan(mobile: boolean, basis: string): React.CSSProperties {
  return { minWidth: 0, display: 'flex', flexDirection: 'column', gap: 12, ...(mobile ? {} : { flex: basis }) }
}

export function buildHealthRows({
  health,
  tables,
  hostMode,
  usage,
  claudeCosts,
  nowMs,
}: {
  health: HealthData | null
  tables: TableInfo[] | null
  hostMode: string
  usage: UsageData | null
  claudeCosts: ClaudeCosts | null
  nowMs: number
}): HealthRow[] {
  return [
    {
      label: 'API',
      status: health?.status === 'ok' ? 'Healthy' : 'Unavailable',
      color: health?.status === 'ok' ? C.success : C.danger,
      detail: health?.status === 'ok' ? 'GET /api/health responding' : 'Health check failed',
    },
    {
      label: 'Database',
      status: tables ? 'Connected' : 'Unknown',
      color: tables ? C.success : C.textMuted,
      detail: tables ? `${fmtNum(tables.length)} tables discovered` : 'No DB telemetry loaded',
    },
    {
      label: 'Cloudflare Tunnel',
      status: hostMode,
      color: hostMode === 'Cloudflare edge' ? C.success : '#f59e0b',
      detail: hostMode === 'Cloudflare edge' ? window.location.hostname : 'Running outside production edge path',
    },
    {
      label: 'Telemetry',
      status: usage ? 'Fresh' : 'Unknown',
      color: usage ? (usage.freshness.staleness_seconds && usage.freshness.staleness_seconds > 600 ? '#f59e0b' : C.success) : C.textMuted,
      detail: usage ? `Latest session ${fmtRelativeFromNow(usage.freshness.latest_session_update_at, nowMs)}` : 'Usage feed unavailable',
    },
    {
      label: 'Cost Feed',
      status: claudeCosts?.error ? 'Degraded' : claudeCosts ? 'Healthy' : 'Unknown',
      color: claudeCosts?.error ? '#f59e0b' : claudeCosts ? C.success : C.textMuted,
      detail: claudeCosts?.error ? 'CodexBar returned an error' : claudeCosts ? `Fetched ${fmtRelativeFromNow(claudeCosts.fetched_at, nowMs)}` : 'Cost feed unavailable',
    },
    {
      label: 'Cron + Git',
      status: 'Not exposed',
      color: C.textMuted,
      detail: 'Current backend health payload does not include cron or deploy metadata',
    },
  ]
}

export function LoadingState() {
  return (
    <section style={panelStyle}>
      <div style={{ fontSize: 13, color: C.textMuted }}>Loading dashboard telemetry…</div>
    </section>
  )
}

export function MetricCard({
  title,
  accent,
  footer,
  children,
}: {
  title: string
  accent: string
  footer: string
  children: React.ReactNode
}) {
  return (
    <section style={{ ...panelStyle, position: 'relative', overflow: 'hidden', minHeight: 182 }}>
      <div style={{ position: 'absolute', inset: 0, background: `radial-gradient(circle at top right, ${accent}18 0%, transparent 45%)`, pointerEvents: 'none' }} />
      <div style={{ position: 'relative', display: 'flex', flexDirection: 'column', gap: 12, height: '100%' }}>
        <div style={{ fontSize: 11, color: C.textMuted, textTransform: 'uppercase', letterSpacing: '0.05em', fontWeight: 700 }}>{title}</div>
        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 12 }}>{children}</div>
        <div style={{ fontSize: 11, color: C.textMuted }}>{footer}</div>
      </div>
    </section>
  )
}

export function SectionHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 14 }}>
      <div style={{ fontSize: 12, color: C.textSecondary, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 700 }}>{title}</div>
      <div style={{ fontSize: 12, color: C.textMuted }}>{subtitle}</div>
    </div>
  )
}

export function StatusPill({ label, color, subtle }: { label: string; color: string; subtle?: boolean }) {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '6px 10px',
        borderRadius: 999,
        border: `1px solid ${color}33`,
        background: subtle ? `${color}14` : `${color}18`,
        color,
        fontSize: 11,
        fontWeight: 700,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
      }}
    >
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: color }} />
      {label}
    </span>
  )
}

export function ProgressBar({ value, color }: { value: number; color: string }) {
  return (
    <div style={{ height: 10, width: '100%', borderRadius: 999, background: C.surfaceActive, overflow: 'hidden', border: `1px solid ${C.border}` }}>
      <div style={{ width: `${Math.min(value, 100)}%`, height: '100%', borderRadius: 999, background: `linear-gradient(90deg, ${color}, ${C.purple})` }} />
    </div>
  )
}

export const panelStyle: React.CSSProperties = {
  background: C.surface,
  border: `1px solid ${C.border}`,
  borderRadius: 16,
  padding: 16,
  boxShadow: '0 18px 40px rgba(0, 0, 0, 0.22)',
}

export const tableHeadStyle: React.CSSProperties = {
  padding: '10px 12px',
  textAlign: 'left',
  color: C.textMuted,
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: '0.05em',
  textTransform: 'uppercase',
  borderBottom: `1px solid ${C.border}`,
}

export const tableCellStyle: React.CSSProperties = {
  padding: '14px 12px',
  color: C.text,
  fontSize: 13,
  borderBottom: `1px solid ${C.border}`,
  fontVariantNumeric: 'tabular-nums',
  verticalAlign: 'top',
}

export const tooltipStyle = {
  backgroundColor: '#11151d',
  border: `1px solid ${C.borderLight}`,
  borderRadius: 12,
  color: C.text,
}

export const emptyChartStyle: React.CSSProperties = {
  height: '100%',
  borderRadius: 12,
  border: `1px dashed ${C.borderLight}`,
  background: C.surfaceActive,
  color: C.textMuted,
  fontSize: 12,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'center',
}
