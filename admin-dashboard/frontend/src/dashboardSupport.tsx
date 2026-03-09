import React from 'react'
import { cn } from '@/lib/utils'

export const API = '/api'
export const EST = 'America/New_York'

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
  if (hours == null) return 'hsl(var(--muted-foreground))'
  if (hours < 1) return 'hsl(var(--success))'
  if (hours < 6) return 'hsl(var(--warning))'
  return 'hsl(var(--muted-foreground))'
}

export function getRateLimitColor(status: UsageData['claude_rate_limit']['status']): string {
  if (status === 'active') return 'hsl(var(--success))'
  if (status === 'limited') return 'hsl(var(--destructive))'
  return 'hsl(var(--muted-foreground))'
}

export function metricCardSpan(mobile: boolean, basis: string): string {
  return cn('min-w-0 flex flex-col gap-3', !mobile && `flex-[${basis}]`)
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
      color: health?.status === 'ok' ? 'hsl(var(--success))' : 'hsl(var(--destructive))',
      detail: health?.status === 'ok' ? 'GET /api/health responding' : 'Health check failed',
    },
    {
      label: 'Database',
      status: tables ? 'Connected' : 'Unknown',
      color: tables ? 'hsl(var(--success))' : 'hsl(var(--muted-foreground))',
      detail: tables ? `${fmtNum(tables.length)} tables discovered` : 'No DB telemetry loaded',
    },
    {
      label: 'Cloudflare Tunnel',
      status: hostMode,
      color: hostMode === 'Cloudflare edge' ? 'hsl(var(--success))' : 'hsl(var(--warning))',
      detail: hostMode === 'Cloudflare edge' ? window.location.hostname : 'Running outside production edge path',
    },
    {
      label: 'Telemetry',
      status: usage ? 'Fresh' : 'Unknown',
      color: usage ? (usage.freshness.staleness_seconds && usage.freshness.staleness_seconds > 600 ? 'hsl(var(--warning))' : 'hsl(var(--success))') : 'hsl(var(--muted-foreground))',
      detail: usage ? `Latest session ${fmtRelativeFromNow(usage.freshness.latest_session_update_at, nowMs)}` : 'Usage feed unavailable',
    },
    {
      label: 'Cost Feed',
      status: claudeCosts?.error ? 'Degraded' : claudeCosts ? 'Healthy' : 'Unknown',
      color: claudeCosts?.error ? 'hsl(var(--warning))' : claudeCosts ? 'hsl(var(--success))' : 'hsl(var(--muted-foreground))',
      detail: claudeCosts?.error ? 'CodexBar returned an error' : claudeCosts ? `Fetched ${fmtRelativeFromNow(claudeCosts.fetched_at, nowMs)}` : 'Cost feed unavailable',
    },
    {
      label: 'Cron + Git',
      status: 'Not exposed',
      color: 'hsl(var(--muted-foreground))',
      detail: 'Current backend health payload does not include cron or deploy metadata',
    },
  ]
}

export function LoadingState() {
  return (
    <section className="rounded-xl border border-border bg-card p-4 shadow-lg">
      <div className="text-[13px] text-muted-foreground">Loading dashboard telemetry…</div>
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
    <section className="rounded-xl border border-border bg-card p-4 shadow-lg relative overflow-hidden min-h-[182px]">
      <div className="absolute inset-0 pointer-events-none" style={{ background: `radial-gradient(circle at top right, ${accent}18 0%, transparent 45%)` }} />
      <div className="relative flex flex-col gap-3 h-full">
        <div className="text-[11px] text-muted-foreground uppercase tracking-wide font-bold">{title}</div>
        <div className="flex-1 flex flex-col gap-3">{children}</div>
        <div className="text-[11px] text-muted-foreground">{footer}</div>
      </div>
    </section>
  )
}

export function SectionHeader({ title, subtitle }: { title: string; subtitle: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3 flex-wrap mb-3.5">
      <div className="text-xs text-muted-foreground uppercase tracking-wider font-bold">{title}</div>
      <div className="text-xs text-muted-foreground">{subtitle}</div>
    </div>
  )
}

export function StatusPill({ label, color, subtle }: { label: string; color: string; subtle?: boolean }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[11px] font-bold uppercase tracking-wider"
      style={{
        border: `1px solid ${color}33`,
        background: subtle ? `${color}14` : `${color}18`,
        color,
      }}
    >
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: color }} />
      {label}
    </span>
  )
}

export function ProgressBar({ value, color }: { value: number; color: string }) {
  return (
    <div className="h-2.5 w-full rounded-full overflow-hidden border border-border bg-muted">
      <div
        className="h-full rounded-full"
        style={{ width: `${Math.min(value, 100)}%`, background: `linear-gradient(90deg, ${color}, hsl(var(--primary)))` }}
      />
    </div>
  )
}

export const tooltipStyle = {
  backgroundColor: 'hsl(var(--card))',
  border: '1px solid hsl(var(--border))',
  borderRadius: 'var(--radius)',
  color: 'hsl(var(--foreground))',
}
