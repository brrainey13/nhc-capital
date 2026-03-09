import { useCallback, useId, useMemo, useState } from 'react'
import {
  Area,
  AreaChart,
  Brush,
  CartesianGrid,
  Legend,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { chartTooltipStyle } from '@/components/ui/chart-panel'

export interface AreaSeriesConfig {
  dataKey: string
  color: string
  label: string
}

interface InteractiveAreaChartProps {
  data: Record<string, unknown>[]
  areas: AreaSeriesConfig[]
  xKey: string
  formatX?: (value: string) => string
  formatY?: (value: number) => string
  showBrush?: boolean
  stacked?: boolean
  height?: number
  animationDuration?: number
}

export function InteractiveAreaChart({
  data,
  areas,
  xKey,
  formatX,
  formatY,
  showBrush = false,
  stacked = false,
  height = 300,
  animationDuration = 1200,
}: InteractiveAreaChartProps) {
  const id = useId()
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set())
  const [hoverX, setHoverX] = useState<string | null>(null)

  const toggleSeries = useCallback((dataKey: string) => {
    setHiddenSeries((prev) => {
      const next = new Set(prev)
      if (next.has(dataKey)) next.delete(dataKey)
      else next.add(dataKey)
      return next
    })
  }, [])

  const legendPayload = useMemo(
    () =>
      areas.map((a) => ({
        value: a.label,
        type: 'rect' as const,
        color: hiddenSeries.has(a.dataKey) ? 'hsl(var(--muted-foreground))' : a.color,
        dataKey: a.dataKey,
      })),
    [areas, hiddenSeries],
  )

  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart
        data={data}
        margin={{ top: 10, right: 8, left: 0, bottom: 0 }}
        onMouseMove={(e) => {
          if (e?.activeLabel != null) setHoverX(String(e.activeLabel))
        }}
        onMouseLeave={() => setHoverX(null)}
      >
        <defs>
          {areas.map((area) => (
            <linearGradient key={area.dataKey} id={`${id}-grad-${area.dataKey}`} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={area.color} stopOpacity={0.5} />
              <stop offset="100%" stopColor={area.color} stopOpacity={0.02} />
            </linearGradient>
          ))}
        </defs>
        <CartesianGrid stroke="hsl(var(--border))" vertical={false} />
        <XAxis
          dataKey={xKey}
          stroke="hsl(var(--muted-foreground))"
          tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }}
          tickFormatter={formatX}
        />
        <YAxis
          stroke="hsl(var(--muted-foreground))"
          tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }}
          tickFormatter={formatY ? (v) => formatY(Number(v)) : undefined}
          width={72}
        />
        <Tooltip
          contentStyle={chartTooltipStyle}
          cursor={{ stroke: 'hsl(var(--primary) / 0.3)', strokeWidth: 1 }}
          formatter={(value: unknown, name: unknown) => {
            const label = areas.find((a) => a.dataKey === String(name))?.label ?? String(name)
            return [formatY ? formatY(Number(value)) : String(value), label]
          }}
        />
        {hoverX != null && (
          <ReferenceLine x={hoverX} stroke="hsl(var(--primary) / 0.25)" strokeDasharray="3 3" />
        )}
        {areas.map((area, i) =>
          hiddenSeries.has(area.dataKey) ? null : (
            <Area
              key={area.dataKey}
              type="monotone"
              dataKey={area.dataKey}
              stroke={area.color}
              strokeWidth={2.5}
              fill={`url(#${id}-grad-${area.dataKey})`}
              stackId={stacked ? 'stack' : undefined}
              isAnimationActive
              animationDuration={animationDuration}
              animationBegin={i * 150}
            />
          ),
        )}
        {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
        <Legend
          {...{ payload: legendPayload } as any}
          onClick={(e: { dataKey?: string }) => {
            if (e?.dataKey) toggleSeries(e.dataKey)
          }}
          wrapperStyle={{ cursor: 'pointer', fontSize: 11 }}
        />
        {showBrush && (
          <Brush
            dataKey={xKey}
            height={28}
            stroke="hsl(var(--primary))"
            fill="hsl(var(--muted))"
            tickFormatter={formatX}
          />
        )}
      </AreaChart>
    </ResponsiveContainer>
  )
}
