import { useCallback, useId, useMemo, useState } from 'react'
import {
  Brush,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ReferenceArea,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { chartTooltipStyle } from '@/components/ui/chart-panel'

export interface LineSeriesConfig {
  dataKey: string
  color: string
  label: string
}

interface InteractiveLineChartProps {
  data: Record<string, unknown>[]
  lines: LineSeriesConfig[]
  xKey: string
  formatX?: (value: string) => string
  formatY?: (value: number) => string
  showBrush?: boolean
  height?: number
  animationDuration?: number
  gradientFill?: boolean
}

export function InteractiveLineChart({
  data,
  lines,
  xKey,
  formatX,
  formatY,
  showBrush = false,
  height = 300,
  animationDuration = 1200,
  gradientFill = true,
}: InteractiveLineChartProps) {
  const id = useId()
  const [hiddenSeries, setHiddenSeries] = useState<Set<string>>(new Set())
  const [hoverX, setHoverX] = useState<string | null>(null)
  const [zoomLeft, setZoomLeft] = useState<string | null>(null)
  const [zoomRight, setZoomRight] = useState<string | null>(null)
  const [zoomRange, setZoomRange] = useState<[number, number] | null>(null)

  const toggleSeries = useCallback((dataKey: string) => {
    setHiddenSeries((prev) => {
      const next = new Set(prev)
      if (next.has(dataKey)) next.delete(dataKey)
      else next.add(dataKey)
      return next
    })
  }, [])

  const visibleData = useMemo(() => {
    if (!zoomRange) return data
    return data.slice(zoomRange[0], zoomRange[1] + 1)
  }, [data, zoomRange])

  const legendPayload = useMemo(
    () =>
      lines.map((l) => ({
        value: l.label,
        type: 'line' as const,
        color: hiddenSeries.has(l.dataKey) ? 'hsl(var(--muted-foreground))' : l.color,
        dataKey: l.dataKey,
      })),
    [lines, hiddenSeries],
  )

  function handleMouseDown(e: { activeLabel?: string | number }) {
    if (e?.activeLabel != null) setZoomLeft(String(e.activeLabel))
  }

  function handleMouseMove(e: { activeLabel?: string | number }) {
    if (e?.activeLabel != null) {
      setHoverX(String(e.activeLabel))
      if (zoomLeft) setZoomRight(String(e.activeLabel))
    }
  }

  function handleMouseUp() {
    if (zoomLeft && zoomRight && zoomLeft !== zoomRight) {
      const leftIdx = data.findIndex((d) => String(d[xKey]) === zoomLeft)
      const rightIdx = data.findIndex((d) => String(d[xKey]) === zoomRight)
      if (leftIdx >= 0 && rightIdx >= 0) {
        setZoomRange([Math.min(leftIdx, rightIdx), Math.max(leftIdx, rightIdx)])
      }
    }
    setZoomLeft(null)
    setZoomRight(null)
  }

  return (
    <div className="relative">
      {zoomRange && (
        <button
          onClick={() => setZoomRange(null)}
          className="absolute right-2 top-0 z-10 cursor-pointer rounded-md border border-border bg-muted px-2 py-0.5 text-[10px] font-semibold text-muted-foreground hover:text-foreground"
        >
          Reset zoom
        </button>
      )}
      <ResponsiveContainer width="100%" height={height}>
        <LineChart
          data={visibleData}
          margin={{ top: 10, right: 8, left: 0, bottom: 0 }}
          onMouseDown={handleMouseDown}
          onMouseMove={handleMouseMove}
          onMouseUp={handleMouseUp}
          onMouseLeave={() => {
            setHoverX(null)
            setZoomLeft(null)
            setZoomRight(null)
          }}
        >
          {gradientFill && (
            <defs>
              {lines.map((line) => (
                <linearGradient key={line.dataKey} id={`${id}-line-grad-${line.dataKey}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={line.color} stopOpacity={0.15} />
                  <stop offset="100%" stopColor={line.color} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
          )}
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
              const label = lines.find((l) => l.dataKey === String(name))?.label ?? String(name)
              return [formatY ? formatY(Number(value)) : String(value), label]
            }}
          />
          {hoverX != null && !zoomLeft && (
            <ReferenceLine x={hoverX} stroke="hsl(var(--primary) / 0.25)" strokeDasharray="3 3" />
          )}
          {zoomLeft && zoomRight && (
            <ReferenceArea x1={zoomLeft} x2={zoomRight} fill="hsl(var(--primary) / 0.08)" />
          )}
          {lines.map((line) =>
            hiddenSeries.has(line.dataKey) ? null : (
              <Line
                key={line.dataKey}
                type="monotone"
                dataKey={line.dataKey}
                stroke={line.color}
                strokeWidth={2.5}
                dot={false}
                activeDot={{ r: 5, fill: line.color, stroke: 'hsl(var(--card))', strokeWidth: 2 }}
                isAnimationActive
                animationDuration={animationDuration}
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
          {showBrush && !zoomRange && (
            <Brush
              dataKey={xKey}
              height={28}
              stroke="hsl(var(--primary))"
              fill="hsl(var(--muted))"
              tickFormatter={formatX}
            />
          )}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
