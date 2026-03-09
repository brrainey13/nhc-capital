import { useMemo } from 'react'
import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts'
import { chartTooltipStyle } from '@/components/ui/chart-panel'
import type { ReactNode } from 'react'

interface InteractiveScatterChartProps {
  data: Record<string, unknown>[]
  xKey: string
  yKey: string
  zKey?: string
  xLabel?: string
  yLabel?: string
  formatX?: (value: number) => string
  formatY?: (value: number) => string
  height?: number
  showQuadrantLines?: boolean
  sizeRange?: [number, number]
  color?: string
  tooltipContent?: (payload: Record<string, unknown>) => ReactNode
}

export function InteractiveScatterChart({
  data,
  xKey,
  yKey,
  zKey,
  xLabel,
  yLabel,
  formatX,
  formatY,
  height = 300,
  showQuadrantLines = false,
  sizeRange = [30, 150],
  color = 'hsl(var(--chart-1))',
  tooltipContent,
}: InteractiveScatterChartProps) {
  const averages = useMemo(() => {
    if (!showQuadrantLines || !data.length) return null
    const xVals = data.map((d) => Number(d[xKey] ?? 0))
    const yVals = data.map((d) => Number(d[yKey] ?? 0))
    return {
      x: xVals.reduce((a, b) => a + b, 0) / xVals.length,
      y: yVals.reduce((a, b) => a + b, 0) / yVals.length,
    }
  }, [data, xKey, yKey, showQuadrantLines])

  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 10, right: 30, left: 20, bottom: 10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
        <XAxis
          dataKey={xKey}
          name={xLabel ?? xKey}
          tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }}
          tickFormatter={formatX ? (v) => formatX(Number(v)) : undefined}
          label={xLabel ? { value: xLabel, position: 'bottom', fill: 'hsl(var(--muted-foreground))', fontSize: 11 } : undefined}
        />
        <YAxis
          dataKey={yKey}
          name={yLabel ?? yKey}
          tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 11 }}
          tickFormatter={formatY ? (v) => formatY(Number(v)) : undefined}
        />
        {zKey && <ZAxis dataKey={zKey} range={sizeRange} />}
        {averages && (
          <>
            <ReferenceLine x={averages.x} stroke="hsl(var(--muted-foreground) / 0.3)" strokeDasharray="4 4" />
            <ReferenceLine y={averages.y} stroke="hsl(var(--muted-foreground) / 0.3)" strokeDasharray="4 4" />
          </>
        )}
        <Tooltip
          contentStyle={chartTooltipStyle}
          content={tooltipContent ? ({ payload }) => {
            if (!payload?.length) return null
            const d = payload[0]?.payload
            if (!d) return null
            return tooltipContent(d as Record<string, unknown>)
          } : undefined}
          formatter={(value: unknown, name: unknown) => {
            const n = String(name)
            if (n === (xLabel ?? xKey) && formatX) return [formatX(Number(value)), n]
            if (n === (yLabel ?? yKey) && formatY) return [formatY(Number(value)), n]
            return [String(value), n]
          }}
        />
        <Scatter
          data={data}
          fill={color}
          fillOpacity={0.7}
          isAnimationActive
          animationDuration={800}
        />
      </ScatterChart>
    </ResponsiveContainer>
  )
}
