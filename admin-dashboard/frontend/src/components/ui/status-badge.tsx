import { cn } from '@/lib/utils'

type StatusVariant = 'success' | 'warning' | 'error' | 'info' | 'muted'

interface StatusBadgeProps {
  label: string
  variant?: StatusVariant
  color?: string
  subtle?: boolean
  className?: string
}

const variantColors: Record<StatusVariant, string> = {
  success: 'hsl(var(--success))',
  warning: 'hsl(var(--warning))',
  error: 'hsl(var(--destructive))',
  info: 'hsl(var(--primary))',
  muted: 'hsl(var(--muted-foreground))',
}

export function StatusBadge({ label, variant = 'muted', color: colorProp, subtle, className }: StatusBadgeProps) {
  const color = colorProp ?? variantColors[variant]

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1.5 text-[11px] font-bold uppercase tracking-wider',
        className
      )}
      style={{
        border: `1px solid ${color}33`,
        background: subtle ? `${color}14` : `${color}18`,
        color,
      }}
    >
      <span
        className="h-1.5 w-1.5 rounded-full"
        style={{ background: color }}
      />
      {label}
    </span>
  )
}
