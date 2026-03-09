import { cn } from '@/lib/utils'

export type TimeRange = '7d' | '30d' | '90d' | '1y' | 'all'
export type ChartType = 'line' | 'bar' | 'area'

interface ChartControlsProps {
  timeRange?: TimeRange
  onTimeRangeChange?: (range: TimeRange) => void
  chartType?: ChartType
  onChartTypeChange?: (type: ChartType) => void
  showBrush?: boolean
  onBrushToggle?: (show: boolean) => void
  exportData?: () => void
}

const timeRanges: { value: TimeRange; label: string }[] = [
  { value: '7d', label: '7D' },
  { value: '30d', label: '30D' },
  { value: '90d', label: '90D' },
  { value: '1y', label: '1Y' },
  { value: 'all', label: 'ALL' },
]

const chartTypes: { value: ChartType; label: string; icon: string }[] = [
  { value: 'line', label: 'Line', icon: '📈' },
  { value: 'bar', label: 'Bar', icon: '📊' },
  { value: 'area', label: 'Area', icon: '📉' },
]

export function ChartControls({
  timeRange,
  onTimeRangeChange,
  chartType,
  onChartTypeChange,
  showBrush,
  onBrushToggle,
  exportData,
}: ChartControlsProps) {
  return (
    <div className="flex flex-wrap items-center gap-2">
      {onTimeRangeChange && (
        <div className="flex rounded-lg border border-border bg-muted">
          {timeRanges.map((range) => (
            <button
              key={range.value}
              onClick={() => onTimeRangeChange(range.value)}
              className={cn(
                'cursor-pointer px-2.5 py-1 text-[11px] font-bold tracking-wide transition-colors first:rounded-l-md last:rounded-r-md',
                timeRange === range.value
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {range.label}
            </button>
          ))}
        </div>
      )}

      {onChartTypeChange && (
        <div className="flex rounded-lg border border-border bg-muted">
          {chartTypes.map((type) => (
            <button
              key={type.value}
              onClick={() => onChartTypeChange(type.value)}
              title={type.label}
              className={cn(
                'cursor-pointer px-2 py-1 text-xs transition-colors first:rounded-l-md last:rounded-r-md',
                chartType === type.value
                  ? 'bg-primary text-primary-foreground'
                  : 'text-muted-foreground hover:text-foreground'
              )}
            >
              {type.icon}
            </button>
          ))}
        </div>
      )}

      {onBrushToggle && (
        <button
          onClick={() => onBrushToggle(!showBrush)}
          className={cn(
            'cursor-pointer rounded-lg border px-2.5 py-1 text-[11px] font-semibold transition-colors',
            showBrush
              ? 'border-primary bg-primary/10 text-primary'
              : 'border-border bg-muted text-muted-foreground hover:text-foreground'
          )}
        >
          Range
        </button>
      )}

      {exportData && (
        <button
          onClick={exportData}
          className="cursor-pointer rounded-lg border border-border bg-muted px-2.5 py-1 text-[11px] font-semibold text-muted-foreground transition-colors hover:text-foreground"
        >
          Export
        </button>
      )}
    </div>
  )
}

export function downloadCSV(data: Record<string, unknown>[], filename = 'chart-data.csv') {
  if (!data.length) return
  const headers = Object.keys(data[0])
  const csv = [
    headers.join(','),
    ...data.map((row) =>
      headers.map((h) => {
        const val = row[h]
        if (val == null) return ''
        if (typeof val === 'string' && val.includes(',')) return `"${val}"`
        return String(val)
      }).join(',')
    ),
  ].join('\n')

  const blob = new Blob([csv], { type: 'text/csv' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}
