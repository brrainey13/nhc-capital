import { cn } from '@/lib/utils'
import type { ReactNode } from 'react'

interface StatCardProps {
  label: string
  value: string | ReactNode
  subtitle?: string
  trend?: string
  trendUp?: boolean
  accent?: boolean
  accentColor?: string
  footer?: string
  children?: ReactNode
  className?: string
}

export function StatCard({ label, value, subtitle, trend, trendUp, accent, accentColor, footer, children, className }: StatCardProps) {
  const gradientColor = accentColor ?? (accent ? 'hsl(var(--primary))' : 'hsl(var(--muted))')

  return (
    <section
      className={cn(
        'relative overflow-hidden rounded-xl border border-border bg-card p-4 shadow-lg min-h-[182px]',
        className
      )}
    >
      <div
        className="pointer-events-none absolute inset-0"
        style={{ background: `radial-gradient(circle at top right, ${gradientColor} / 0.09, transparent 45%)` }}
      />
      <div className="relative flex h-full flex-col gap-3">
        <div className="text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{label}</div>
        <div className="flex flex-1 flex-col gap-3">
          {typeof value === 'string' ? (
            <div className="text-[30px] font-extrabold leading-none tracking-tight text-foreground">{value}</div>
          ) : value}
          {subtitle && <div className="text-xs text-muted-foreground">{subtitle}</div>}
          {trend && (
            <span className={cn('text-xs font-semibold', trendUp !== false ? 'text-success' : 'text-destructive')}>
              {trend}
            </span>
          )}
          {children}
        </div>
        {footer && <div className="text-[11px] text-muted-foreground">{footer}</div>}
      </div>
    </section>
  )
}
