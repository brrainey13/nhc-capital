import { cn } from '@/lib/utils'
import type { ReactNode } from 'react'

interface ChartPanelProps {
  title: string
  subtitle?: string
  children: ReactNode
  height?: number
  className?: string
  actions?: ReactNode
}

export function ChartPanel({ title, subtitle, children, height, className, actions }: ChartPanelProps) {
  return (
    <section className={cn('rounded-xl border border-border bg-card p-4 shadow-lg', className)}>
      <div className="mb-3.5 flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-baseline gap-3">
          <div className="text-xs font-bold uppercase tracking-wider text-muted-foreground">{title}</div>
          {subtitle && <div className="text-xs text-muted-foreground">{subtitle}</div>}
        </div>
        {actions}
      </div>
      <div style={height ? { height } : undefined}>
        {children}
      </div>
    </section>
  )
}

export const chartTooltipStyle = {
  backgroundColor: 'hsl(var(--card))',
  border: '1px solid hsl(var(--border))',
  color: 'hsl(var(--foreground))',
  borderRadius: 'var(--radius)',
}
