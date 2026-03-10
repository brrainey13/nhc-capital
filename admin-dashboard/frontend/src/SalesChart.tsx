import { useEffect, useMemo, useState } from 'react'
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts'
import { chartTooltipStyle } from '@/components/ui/chart-panel'
import { cn, useIsMobile } from '@/lib/utils'
import { InteractiveScatterChart } from '@/components/charts/interactive-scatter-chart'

interface ForeclosureSite {
  id: number
  town: string
  address: string
  sale_date: string
  property_type: string
  has_rules: boolean
}

interface Comp {
  pid: number
  address: string
  town: string
  use_desc: string
  sqft: number | null
  bedrooms: number | null
  bathrooms: number | null
  year_built: number | null
  units: number | null
  sale_price: number
  sale_date: string
  price_per_sqft: number | null
  owner: string
  book_page: string
  distance_mi: number | null
  comp_score: number
  sale_era: string | null
  is_outlier: boolean
  outlier_reason: string | null
}

interface Subject {
  id: number
  town: string
  address: string
  property_type: string
  check_amount: string | null
  sale_date: string | null
  inferred_class: string
  sqft: number | null
  bedrooms: number | null
  year_built: number | null
  has_coords: boolean
}

interface Summary {
  total_comps: number
  clean_comps: number
  outliers: number
  median_ppsf: number | null
  min_price: number | null
  max_price: number | null
  median_price: number | null
  avg_ppsf: number | null
  min_ppsf: number | null
  max_ppsf: number | null
  era_breakdown?: Record<string, number>
  radius_used_mi?: number | null
}

const fmt = (v: number) => `$${Math.round(v).toLocaleString()}`
const fmtK = (v: number) => v >= 1000000 ? `$${(v / 1000000).toFixed(1)}M` : `$${(v / 1000).toFixed(0)}K`

function scoreColorClass(score: number): string {
  if (score >= 80) return 'text-success'
  if (score >= 60) return 'text-[hsl(var(--chart-2))]'
  if (score >= 40) return 'text-warning'
  return 'text-destructive'
}

export default function SalesChart({
  selectedForeclosureId,
  onSelectedForeclosure,
}: {
  selectedForeclosureId?: number | null
  onSelectedForeclosure?: (id: number) => void
}) {
  const mobile = useIsMobile()
  const [sites, setSites] = useState<ForeclosureSite[]>([])
  const [selectedId, setSelectedId] = useState<number | null>(selectedForeclosureId ?? null)
  const [comps, setComps] = useState<Comp[]>([])
  const [subject, setSubject] = useState<Subject | null>(null)
  const [summary, setSummary] = useState<Summary | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [selectedYear, setSelectedYear] = useState<string | null>(null)
  const [showOutliers, setShowOutliers] = useState(true)
  const [viewMode, setViewMode] = useState<'chart' | 'scatter'>('chart')

  useEffect(() => {
    fetch('/api/real-estate/foreclosures?limit=500')
      .then(r => r.json())
      .then((rows: ForeclosureSite[]) => {
        setSites(rows || [])
        if (!selectedForeclosureId && rows?.length) {
          setSelectedId(rows[0].id)
          onSelectedForeclosure?.(rows[0].id)
        }
      })
      .catch(e => setError(String(e)))
  }, [])

  useEffect(() => {
    if (selectedForeclosureId && selectedForeclosureId !== selectedId) {
      setSelectedId(selectedForeclosureId)
    }
  }, [selectedForeclosureId])

  useEffect(() => {
    if (!selectedId) return
    setLoading(true)
    setError(null)
    fetch(`/api/real-estate/comps?foreclosure_id=${selectedId}&limit=500`)
      .then(r => r.json())
      .then(json => {
        if (json.detail) { setError(json.detail); return }
        setSubject(json.subject || null)
        setSummary(json.summary || null)
        setComps(json.comps || [])
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false))
  }, [selectedId])

  const visibleComps = useMemo(() => {
    return showOutliers ? comps : comps.filter(c => !c.is_outlier)
  }, [comps, showOutliers])

  const chartData = useMemo(() => {
    const clean = visibleComps.filter(c => !c.is_outlier)
    const byYear: Record<string, { totalPrice: number; totalPpsf: number; count: number }> = {}
    for (const s of clean) {
      if (!s.sale_date || !s.price_per_sqft || s.price_per_sqft <= 0) continue
      const year = s.sale_date.substring(0, 4)
      if (!byYear[year]) byYear[year] = { totalPrice: 0, totalPpsf: 0, count: 0 }
      byYear[year].totalPrice += s.sale_price
      byYear[year].totalPpsf += s.price_per_sqft
      byYear[year].count += 1
    }
    return Object.entries(byYear)
      .map(([year, d]) => ({
        year,
        avgPrice: Math.round(d.totalPrice / d.count),
        avgPpsf: Math.round(d.totalPpsf / d.count),
        count: d.count,
      }))
      .sort((a, b) => a.year.localeCompare(b.year))
  }, [visibleComps])

  const scatterData = useMemo(() => {
    return visibleComps
      .filter(c => c.sqft && c.sale_price && c.price_per_sqft)
      .map(c => ({
        sqft: c.sqft!,
        price: c.sale_price,
        ppsf: c.price_per_sqft!,
        address: c.address,
        score: c.comp_score,
        outlier: c.is_outlier,
        year: c.sale_date?.substring(0, 4),
      }))
  }, [visibleComps])

  const detailComps = useMemo(() => {
    let filtered = visibleComps
    if (selectedYear) {
      filtered = filtered.filter(c => c.sale_date?.startsWith(selectedYear))
    }
    return filtered
  }, [visibleComps, selectedYear])

  if (loading && !comps.length) return <div className="p-10 text-muted-foreground">Loading comp data...</div>
  if (error) return <div className="p-10 text-destructive">{error}</div>

  return (
    <div className={cn('page-enter', mobile ? 'p-3' : 'p-6')}>
      {/* Foreclosure selector */}
      <div className="mb-4 flex flex-wrap items-center gap-2.5">
        <select
          value={selectedId ?? ''}
          onChange={(e) => {
            const id = Number(e.target.value)
            setSelectedId(id)
            onSelectedForeclosure?.(id)
            setSelectedYear(null)
          }}
          className={cn(
            'rounded-lg border border-border bg-muted px-2.5 py-2 text-foreground',
            mobile ? 'min-w-full' : 'min-w-[420px]'
          )}
        >
          {sites.map(s => (
            <option key={s.id} value={s.id}>
              {s.address} ({s.town})
            </option>
          ))}
        </select>
      </div>

      {/* Subject property card */}
      {subject && (
        <div className={cn(
          'card-hover mb-4 rounded-lg border border-border bg-card',
          mobile ? 'p-3' : 'p-4'
        )}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className={cn(
                'mb-1 font-bold text-foreground',
                mobile ? 'text-base' : 'text-lg'
              )}>
                {subject.address}
              </h2>
              <div className="mb-2 text-xs text-muted-foreground">
                {subject.town} · {subject.inferred_class?.replace(/_/g, ' ')} · {subject.property_type || 'N/A'}
              </div>
            </div>
            {subject.check_amount && (
              <div className="rounded-lg border border-destructive/25 bg-destructive/10 px-3 py-1.5">
                <div className="text-[10px] font-semibold uppercase text-destructive">Foreclosure Amount</div>
                <div className="text-lg font-bold text-destructive">{fmt(Number(subject.check_amount))}</div>
              </div>
            )}
          </div>
          <div className={cn('mt-2 flex flex-wrap', mobile ? 'gap-4' : 'gap-6')}>
            {subject.sqft && (
              <div>
                <div className="text-[10px] font-semibold uppercase text-muted-foreground">Sqft</div>
                <div className="text-sm font-semibold text-foreground">{subject.sqft.toLocaleString()}</div>
              </div>
            )}
            {subject.bedrooms && (
              <div>
                <div className="text-[10px] font-semibold uppercase text-muted-foreground">Beds</div>
                <div className="text-sm font-semibold text-foreground">{String(subject.bedrooms)}</div>
              </div>
            )}
            {subject.year_built && (
              <div>
                <div className="text-[10px] font-semibold uppercase text-muted-foreground">Year Built</div>
                <div className="text-sm font-semibold text-foreground">{String(subject.year_built)}</div>
              </div>
            )}
            {subject.sale_date && (
              <div>
                <div className="text-[10px] font-semibold uppercase text-muted-foreground">Sale Date</div>
                <div className="text-sm font-semibold text-foreground">{subject.sale_date}</div>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Summary stats */}
      {summary && (
        <div className="mb-4 grid grid-cols-2 gap-2.5 sm:grid-cols-5">
          <div className="card-hover rounded-lg border border-border bg-card px-3 py-2.5 text-center">
            <div className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">Clean Comps</div>
            <div className="text-base font-bold text-success">{String(summary.clean_comps)}</div>
          </div>
          <div className="card-hover rounded-lg border border-border bg-card px-3 py-2.5 text-center">
            <div className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">Outliers</div>
            <div className="text-base font-bold text-warning">{String(summary.outliers)}</div>
          </div>
          <div className="card-hover rounded-lg border border-border bg-card px-3 py-2.5 text-center">
            <div className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">Median Price</div>
            <div className="text-base font-bold text-[hsl(var(--chart-3))]">{summary.median_price ? fmtK(summary.median_price) : 'N/A'}</div>
          </div>
          <div className="card-hover rounded-lg border border-border bg-card px-3 py-2.5 text-center">
            <div className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">Median $/sqft</div>
            <div className="text-base font-bold text-[hsl(var(--chart-2))]">{summary.median_ppsf ? `$${Math.round(summary.median_ppsf)}` : 'N/A'}</div>
          </div>
          <div className="card-hover rounded-lg border border-border bg-card px-3 py-2.5 text-center">
            <div className="mb-1 text-[10px] font-semibold uppercase text-muted-foreground">Price Range</div>
            <div className="text-base font-bold text-muted-foreground">{summary.min_price && summary.max_price ? `${fmtK(summary.min_price)} – ${fmtK(summary.max_price)}` : 'N/A'}</div>
          </div>
        </div>
      )}

      {/* Era breakdown + radius info */}
      {summary && (summary.era_breakdown || summary.radius_used_mi) && (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
          {summary.radius_used_mi && (
            <span className="rounded-md border border-border bg-muted px-2 py-1 text-muted-foreground">
              📍 {summary.radius_used_mi}mi radius
              {summary.radius_used_mi > 0.25 && <span className="ml-1 text-warning">(auto-expanded)</span>}
            </span>
          )}
          {summary.era_breakdown && Object.entries(summary.era_breakdown).map(([era, count]) => {
            const labels: Record<string, string> = {
              'last_12mo': '< 1yr',
              '1_3yr': '1-3yr',
              '3_5yr': '3-5yr',
              '5plus_yr': '5+ yr',
              'unknown': '?',
            }
            const colors: Record<string, string> = {
              'last_12mo': 'border-success/50 text-success',
              '1_3yr': 'border-[hsl(var(--chart-2))]/50 text-[hsl(var(--chart-2))]',
              '3_5yr': 'border-warning/50 text-warning',
              '5plus_yr': 'border-muted-foreground/50 text-muted-foreground',
              'unknown': 'border-border text-muted-foreground',
            }
            return (
              <span key={era} className={cn('rounded-md border bg-muted px-2 py-1 font-semibold', colors[era] || '')}>
                {labels[era] || era}: {count}
              </span>
            )
          })}
        </div>
      )}

      {/* Controls */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <div className="flex">
          <button
            onClick={() => setViewMode('chart')}
            className={cn(
              'cursor-pointer rounded-l-md px-3.5 py-2.5 text-xs font-semibold transition-colors min-h-[44px]',
              viewMode === 'chart'
                ? 'bg-[hsl(var(--chart-3))] text-white'
                : 'border border-border bg-muted text-muted-foreground hover:text-foreground'
            )}
          >
            Trend Chart
          </button>
          <button
            onClick={() => setViewMode('scatter')}
            className={cn(
              'cursor-pointer rounded-r-md px-3.5 py-2.5 text-xs font-semibold transition-colors min-h-[44px]',
              viewMode === 'scatter'
                ? 'bg-[hsl(var(--chart-3))] text-white'
                : 'border border-border bg-muted text-muted-foreground hover:text-foreground'
            )}
          >
            Scatter Plot
          </button>
        </div>
        <label className="ml-auto flex cursor-pointer items-center gap-1.5 text-xs text-muted-foreground">
          <input type="checkbox" checked={showOutliers} onChange={() => setShowOutliers(!showOutliers)} />
          Show outliers ({summary?.outliers || 0})
        </label>
      </div>

      {/* Charts */}
      {viewMode === 'chart' && (
        <div className={cn(
          'w-full rounded-lg border border-border bg-card p-3',
          mobile ? 'h-[260px]' : 'h-[380px]'
        )}>
          {chartData.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
              <div className="text-3xl">🏠</div>
              <div className="text-sm text-muted-foreground">No comp data available for chart</div>
            </div>
          ) : (
            <ResponsiveContainer>
              <ComposedChart
                data={chartData}
                margin={mobile ? { top: 5, right: 10, left: -10, bottom: 0 } : { top: 10, right: 40, left: 20, bottom: 0 }}
                onClick={(e) => {
                  if (e?.activeLabel) setSelectedYear(prev => prev === String(e.activeLabel) ? null : String(e.activeLabel))
                }}
                style={{ cursor: 'pointer' }}
              >
                <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                <XAxis dataKey="year" tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: mobile ? 10 : 12 }} />
                <YAxis
                  yAxisId="price" tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: mobile ? 10 : 12 }}
                  tickFormatter={(v: number) => fmtK(v)}
                  width={mobile ? 55 : 65}
                />
                {!mobile && (
                  <YAxis
                    yAxisId="ppsf" orientation="right" tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 12 }}
                    tickFormatter={(v: number) => `$${v}`}
                  />
                )}
                <Tooltip
                  contentStyle={{ ...chartTooltipStyle, fontSize: mobile ? 12 : 14 }}
                  labelStyle={{ color: 'hsl(var(--foreground))' }}
                  formatter={(value: number | string | undefined, name: string | undefined) => {
                    const n = Number(value ?? 0)
                    const key = name ?? ''
                    return [
                      key === 'avgPrice' ? fmt(n) : `$${n}/sqft`,
                      key === 'avgPrice' ? 'Avg Sale Price' : 'Avg $/SqFt',
                    ]
                  }}
                />
                <Legend formatter={(value: string) => value === 'avgPrice' ? 'Avg Price' : 'Avg $/SqFt'} />
                <Bar
                  yAxisId="price"
                  dataKey="avgPrice"
                  fill="hsl(var(--chart-3))"
                  radius={[6, 6, 0, 0]}
                  barSize={mobile ? 20 : 32}
                  isAnimationActive
                  animationDuration={800}
                />
                <Line
                  yAxisId={mobile ? 'price' : 'ppsf'}
                  dataKey="avgPpsf"
                  stroke="hsl(var(--chart-2))"
                  strokeWidth={2.5}
                  dot={{ r: mobile ? 3 : 4, fill: 'hsl(var(--chart-2))' }}
                  isAnimationActive
                  animationDuration={1000}
                />
              </ComposedChart>
            </ResponsiveContainer>
          )}
        </div>
      )}

      {viewMode === 'scatter' && (
        <div className={cn(
          'w-full rounded-lg border border-border bg-card p-3',
          mobile ? 'h-[300px]' : 'h-[400px]'
        )}>
          {scatterData.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
              <div className="text-3xl">📊</div>
              <div className="text-sm text-muted-foreground">No scatter data available</div>
            </div>
          ) : (
            <InteractiveScatterChart
              data={scatterData.filter(d => !d.outlier) as Record<string, unknown>[]}
              xKey="sqft"
              yKey="price"
              zKey="score"
              xLabel="Sqft"
              yLabel="Price"
              formatX={(v) => `${(v / 1000).toFixed(1)}K`}
              formatY={(v) => fmtK(v)}
              height={mobile ? 280 : 380}
              showQuadrantLines
              color="hsl(var(--chart-3))"
              tooltipContent={(d) => (
                <div className="rounded-lg border border-border bg-card p-2.5 text-xs text-foreground">
                  <div className="mb-1 font-bold">{String(d.address)}</div>
                  <div>{fmt(Number(d.price))} · {Number(d.sqft).toLocaleString()} sqft · ${Number(d.ppsf)}/sf</div>
                  <div className="text-muted-foreground">Score: {String(d.score)} · {String(d.year)}</div>
                </div>
              )}
            />
          )}
        </div>
      )}

      <div className="mt-2 text-center text-[11px] text-muted-foreground">
        {selectedYear ? `Showing ${selectedYear} — click bar again to clear` : 'Click a bar to filter by year'}
        {' · '} Clean comps only in chart (outliers excluded from averages)
      </div>

      {/* Detail table */}
      <div className="mt-5">
        <div className="mb-2.5 flex items-center justify-between">
          <h3 className={cn(
            'font-semibold text-foreground',
            mobile ? 'text-sm' : 'text-[15px]'
          )}>
            {selectedYear ? `Sales in ${selectedYear}` : 'All Comps'}
          </h3>
          <span className="text-xs text-muted-foreground">{detailComps.length} transactions</span>
        </div>

        {detailComps.length === 0 ? (
          <div className="flex flex-col items-center gap-2 rounded-lg border border-border py-8 text-center">
            <div className="text-3xl">🔍</div>
            <div className="text-sm text-muted-foreground">No comparable sales found</div>
            <div className="text-xs text-muted-foreground">Try selecting a different property or adjusting filters</div>
          </div>
        ) : (
          <div className="max-h-[460px] overflow-auto rounded-lg border border-border">
            <table className="w-full border-collapse text-sm">
              <thead>
                <tr>
                  {['Score', 'Address', 'Price', '$/SqFt', 'SqFt', 'Beds', 'Year', 'Date', 'Era', ...(mobile ? [] : ['Dist'])].map((h) => (
                    <th key={h} className="sticky top-0 z-[1] whitespace-nowrap border-b-2 border-border bg-card px-2 py-2.5 text-left text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {detailComps.map((c, i) => {
                  const isOutlier = c.is_outlier

                  return (
                    <tr
                      key={`${c.pid}-${c.sale_date}-${i}`}
                      className={cn('transition-colors hover:bg-muted/30', isOutlier && 'bg-destructive/5')}
                      title={c.outlier_reason || undefined}
                    >
                      <td className={cn('border-b border-border px-2 py-2 text-xs font-bold text-[13px]', scoreColorClass(c.comp_score))}>
                        {isOutlier ? '!!' : c.comp_score.toFixed(0)}
                      </td>
                      <td className={cn(
                        'max-w-[200px] truncate border-b border-border px-2 py-2 text-xs',
                        isOutlier ? 'text-muted-foreground' : 'text-foreground'
                      )}>
                        {c.address}
                        {isOutlier && <span className="ml-1 text-[10px] text-destructive">outlier</span>}
                      </td>
                      <td className={cn(
                        'border-b border-border px-2 py-2 text-xs font-semibold',
                        isOutlier ? 'text-muted-foreground' : 'text-[hsl(var(--chart-3))]'
                      )}>
                        {fmt(c.sale_price)}
                      </td>
                      <td className={cn(
                        'border-b border-border px-2 py-2 text-xs',
                        isOutlier ? 'text-muted-foreground' : 'text-[hsl(var(--chart-2))]'
                      )}>
                        ${c.price_per_sqft ? Math.round(c.price_per_sqft) : '-'}
                      </td>
                      <td className={cn(
                        'border-b border-border px-2 py-2 text-xs',
                        isOutlier ? 'text-muted-foreground' : 'text-foreground'
                      )}>
                        {c.sqft?.toLocaleString() || '-'}
                      </td>
                      <td className={cn(
                        'border-b border-border px-2 py-2 text-xs',
                        isOutlier ? 'text-muted-foreground' : 'text-foreground'
                      )}>
                        {c.bedrooms ?? '-'}
                      </td>
                      <td className={cn(
                        'border-b border-border px-2 py-2 text-xs',
                        isOutlier ? 'text-muted-foreground' : 'text-foreground'
                      )}>
                        {c.year_built ?? '-'}
                      </td>
                      <td className={cn(
                        'border-b border-border px-2 py-2 text-xs',
                        isOutlier ? 'text-muted-foreground' : 'text-foreground'
                      )}>
                        {c.sale_date ? new Date(c.sale_date).toLocaleDateString() : '-'}
                      </td>
                      <td className="border-b border-border px-2 py-2 text-[10px]">
                        {c.sale_era === 'last_12mo' && <span className="text-success font-semibold">{'<1yr'}</span>}
                        {c.sale_era === '1_3yr' && <span className="text-[hsl(var(--chart-2))] font-semibold">1-3yr</span>}
                        {c.sale_era === '3_5yr' && <span className="text-warning">3-5yr</span>}
                        {c.sale_era === '5plus_yr' && <span className="text-muted-foreground">5+yr</span>}
                      </td>
                      {!mobile && (
                        <td className="border-b border-border px-2 py-2 text-[11px] text-muted-foreground">
                          {c.distance_mi ? `${c.distance_mi.toFixed(2)}mi` : '-'}
                        </td>
                      )}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
