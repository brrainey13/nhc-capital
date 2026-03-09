import { useCallback, useId, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { chartTooltipStyle } from '@/components/ui/chart-panel'
import { cn } from '@/lib/utils'

export interface BarSeriesConfig {
  dataKey: string
  color: string
  label: string
  colorByValue?: boolean
  positiveColor?: string
  negativeColor?: string
}

type SortMode = 'original' | 'asc' | 'desc'

interface InteractiveBarChartProps {
  data: Record<string, unknown>[]
  bars: BarSeriesConfig[]
  xKey: string
  layout?: 'horizontal' | 'vertical'
  formatX?: (value: string) => string
  formatY?: (value: number) => string
  height?: number
  showSortToggle?: boolean
  animationDuration?: number
}

export function InteractiveBarChart({
  data,
  bars,
  xKey,
  layout = 'horizontal',
  formatX,
  formatY,
  height = 300,
  showSortToggle = false,
  animationDuration = 800,
}: InteractiveBarChartProps) {
  const id = useId()
  const [sortMode, setSortMode] = useState<SortMode>('original')
  const [activeIndex, setActiveIndex] = useState<number | null>(null)

  const sortedData = useMemo(() => {
    if (sortMode === 'original' || bars.length === 0) return data
    const key = bars[0].dataKey
    return data.slice().sort((a, b) => {
      const av = Number(a[key] ?? 0)
      const bv = Number(b[key] ?? 0)
      return sortMode === 'asc' ? av - bv : bv - av
    })
  }, [data, bars, sortMode])

  const cycleSortMode = useCallback(() => {
    setSortMode((prev) => {
      if (prev === 'original') return 'desc'
      if (prev === 'desc') return 'asc'
      return 'original'
    })
  }, [])

  const sortLabel = sortMode === 'original' ? 'Sort' : sortMode === 'desc' ? 'Sort ↓' : 'Sort ↑'

  const isVertical = layout === 'vertical'

  return (
    <div>
      {showSortToggle && (
        <div className="mb-2 flex justify-end">
          <button
            onClick={cycleSortMode}
            className={cn(
              'cursor-pointer rounded-lg border px-2.5 py-1 text-[11px] font-semibold transition-colors',
              sortMode !== 'original'
                ? 'border-primary bg-primary/10 text-primary'
                : 'border-border bg-muted text-muted-foreground hover:text-foreground'
            )}
          >
            {sortLabel}
          </button>
        </div>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <BarChart
          data={sortedData}
          layout={isVertical ? 'vertical' : 'horizontal'}
          margin={isVertical
            ? { top: 8, right: 20, bottom: 8, left: 64 }
            : { top: 10, right: 8, left: 0, bottom: 0 }
          }
          onMouseMove={(e) => {
            if (e?.activeTooltipIndex != null) setActiveIndex(Number(e.activeTooltipIndex))
          }}
          onMouseLeave={() => setActiveIndex(null)}
        >
          <defs>
            {bars.map((bar) => (
              <linearGradient key={bar.dataKey} id={`${id}-bar-grad-${bar.dataKey}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={bar.color} stopOpacity={0.95} />
                <stop offset="100%" stopColor={bar.color} stopOpacity={0.6} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid stroke="hsl(var(--border))" vertical={isVertical} horizontal={!isVertical} />
          {isVertical ? (
            <>
              <XAxis type="number" stroke="hsl(var(--muted-foreground))" tick={{ fontSize: 11 }} tickFormatter={formatY ? (v) => formatY(Number(v)) : undefined} />
              <YAxis type="category" dataKey={xKey} stroke="hsl(var(--muted-foreground))" tick={{ fontSize: 11 }} width={150} tickFormatter={formatX} />
            </>
          ) : (
            <>
              <XAxis dataKey={xKey} stroke="hsl(var(--muted-foreground))" tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }} tickFormatter={formatX} />
              <YAxis stroke="hsl(var(--muted-foreground))" tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }} tickFormatter={formatY ? (v) => formatY(Number(v)) : undefined} width={72} />
            </>
          )}
          <Tooltip
            contentStyle={chartTooltipStyle}
            cursor={{ fill: 'hsl(var(--primary) / 0.06)' }}
            formatter={(value: unknown, name: unknown) => {
              const label = bars.find((b) => b.dataKey === String(name))?.label ?? String(name)
              return [formatY ? formatY(Number(value)) : String(value), label]
            }}
          />
          {bars.map((bar) => (
            <Bar
              key={bar.dataKey}
              dataKey={bar.dataKey}
              radius={isVertical ? [0, 6, 6, 0] : [6, 6, 0, 0]}
              isAnimationActive
              animationDuration={animationDuration}
              fill={`url(#${id}-bar-grad-${bar.dataKey})`}
            >
              {sortedData.map((entry, index) => {
                const val = Number(entry[bar.dataKey] ?? 0)
                let fill = `url(#${id}-bar-grad-${bar.dataKey})`
                if (bar.colorByValue) {
                  fill = val >= 0 ? (bar.positiveColor ?? 'hsl(var(--success))') : (bar.negativeColor ?? 'hsl(var(--destructive))')
                }
                const isActive = activeIndex === index
                return (
                  <Cell
                    key={index}
                    fill={fill}
                    fillOpacity={isActive ? 1 : 0.85}
                  />
                )
              })}
            </Bar>
          ))}
          {bars.length > 1 && (
            <Legend
              wrapperStyle={{ fontSize: 11 }}
            />
          )}
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}
