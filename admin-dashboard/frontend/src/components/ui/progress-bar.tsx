import { cn } from '@/lib/utils'

interface ProgressBarProps {
  value: number
  color?: string
  className?: string
}

export function ProgressBar({ value, color, className }: ProgressBarProps) {
  return (
    <div className={cn('h-2.5 w-full overflow-hidden rounded-full border border-border bg-muted', className)}>
      <div
        className="h-full rounded-full transition-all duration-300"
        style={{
          width: `${Math.min(value, 100)}%`,
          background: color
            ? `linear-gradient(90deg, ${color}, hsl(var(--chart-3)))`
            : 'linear-gradient(90deg, hsl(var(--primary)), hsl(var(--chart-3)))',
        }}
      />
    </div>
  )
}
