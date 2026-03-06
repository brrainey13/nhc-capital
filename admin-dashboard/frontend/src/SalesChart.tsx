import { useEffect, useMemo, useState } from 'react';
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer, ScatterChart, Scatter, ZAxis,
} from 'recharts';

interface ForeclosureSite {
  id: number;
  town: string;
  address: string;
  sale_date: string;
  property_type: string;
  has_rules: boolean;
}

interface Comp {
  pid: number;
  address: string;
  town: string;
  use_desc: string;
  sqft: number | null;
  bedrooms: number | null;
  bathrooms: number | null;
  year_built: number | null;
  units: number | null;
  sale_price: number;
  sale_date: string;
  price_per_sqft: number | null;
  owner: string;
  book_page: string;
  distance_mi: number | null;
  comp_score: number;
  is_outlier: boolean;
  outlier_reason: string | null;
}

interface Subject {
  id: number;
  town: string;
  address: string;
  property_type: string;
  check_amount: string | null;
  sale_date: string | null;
  inferred_class: string;
  sqft: number | null;
  bedrooms: number | null;
  year_built: number | null;
  has_coords: boolean;
}

interface Summary {
  total_comps: number;
  clean_comps: number;
  outliers: number;
  median_ppsf: number | null;
  min_price: number | null;
  max_price: number | null;
  median_price: number | null;
  avg_ppsf: number | null;
  min_ppsf: number | null;
  max_ppsf: number | null;
}

const fmt = (v: number) => `$${Math.round(v).toLocaleString()}`;
const fmtK = (v: number) => v >= 1000000 ? `$${(v / 1000000).toFixed(1)}M` : `$${(v / 1000).toFixed(0)}K`;

function useIsMobile(bp = 768) {
  const [m, setM] = useState(window.innerWidth < bp);
  useEffect(() => {
    const h = () => setM(window.innerWidth < bp);
    window.addEventListener('resize', h);
    return () => window.removeEventListener('resize', h);
  }, [bp]);
  return m;
}

const C = {
  bg: '#0f1117', surface: '#181a20', border: '#2a2d37', text: '#e4e5e9',
  muted: '#5f6370', secondary: '#8b8f9a', accent: '#6c5ce7', teal: '#00cec9',
  white: '#fff', red: '#ff4757', yellow: '#ffa502', green: '#2ed573',
};

export default function SalesChart({
  selectedForeclosureId,
  onSelectedForeclosure,
}: {
  selectedForeclosureId?: number | null;
  onSelectedForeclosure?: (id: number) => void;
}) {
  const mobile = useIsMobile();
  const [sites, setSites] = useState<ForeclosureSite[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(selectedForeclosureId ?? null);
  const [comps, setComps] = useState<Comp[]>([]);
  const [subject, setSubject] = useState<Subject | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedYear, setSelectedYear] = useState<string | null>(null);
  const [showOutliers, setShowOutliers] = useState(true);
  const [viewMode, setViewMode] = useState<'chart' | 'scatter'>('chart');

  useEffect(() => {
    fetch('/api/real-estate/foreclosures?limit=500')
      .then(r => r.json())
      .then((rows: ForeclosureSite[]) => {
        setSites(rows || []);
        if (!selectedForeclosureId && rows?.length) {
          setSelectedId(rows[0].id);
          onSelectedForeclosure?.(rows[0].id);
        }
      })
      .catch(e => setError(String(e)));
  }, []);

  useEffect(() => {
    if (selectedForeclosureId && selectedForeclosureId !== selectedId) {
      setSelectedId(selectedForeclosureId);
    }
  }, [selectedForeclosureId]);

  useEffect(() => {
    if (!selectedId) return;
    setLoading(true);
    setError(null);
    fetch(`/api/real-estate/comps?foreclosure_id=${selectedId}&limit=500`)
      .then(r => r.json())
      .then(json => {
        if (json.detail) { setError(json.detail); return; }
        setSubject(json.subject || null);
        setSummary(json.summary || null);
        setComps(json.comps || []);
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, [selectedId]);

  const visibleComps = useMemo(() => {
    return showOutliers ? comps : comps.filter(c => !c.is_outlier);
  }, [comps, showOutliers]);

  const chartData = useMemo(() => {
    const clean = visibleComps.filter(c => !c.is_outlier);
    const byYear: Record<string, { totalPrice: number; totalPpsf: number; count: number }> = {};
    for (const s of clean) {
      if (!s.sale_date || !s.price_per_sqft || s.price_per_sqft <= 0) continue;
      const year = s.sale_date.substring(0, 4);
      if (!byYear[year]) byYear[year] = { totalPrice: 0, totalPpsf: 0, count: 0 };
      byYear[year].totalPrice += s.sale_price;
      byYear[year].totalPpsf += s.price_per_sqft;
      byYear[year].count += 1;
    }
    return Object.entries(byYear)
      .map(([year, d]) => ({
        year,
        avgPrice: Math.round(d.totalPrice / d.count),
        avgPpsf: Math.round(d.totalPpsf / d.count),
        count: d.count,
      }))
      .sort((a, b) => a.year.localeCompare(b.year));
  }, [visibleComps]);

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
      }));
  }, [visibleComps]);

  const detailComps = useMemo(() => {
    let filtered = visibleComps;
    if (selectedYear) {
      filtered = filtered.filter(c => c.sale_date?.startsWith(selectedYear));
    }
    return filtered;
  }, [visibleComps, selectedYear]);

  if (loading && !comps.length) return <div style={{ color: '#aaa', padding: 40 }}>Loading comp data...</div>;
  if (error) return <div style={{ color: '#ff6b6b', padding: 40 }}>{error}</div>;

  return (
    <div style={{ padding: mobile ? 12 : 24 }}>
      {/* Foreclosure selector */}
      <div style={{ display: 'flex', gap: 10, alignItems: 'center', marginBottom: 16, flexWrap: 'wrap' }}>
        <select
          value={selectedId ?? ''}
          onChange={(e) => {
            const id = Number(e.target.value);
            setSelectedId(id);
            onSelectedForeclosure?.(id);
            setSelectedYear(null);
          }}
          style={{ background: '#23262f', color: '#fff', border: '1px solid #333', borderRadius: 8, padding: '8px 10px', minWidth: mobile ? '100%' : 420 }}
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
        <div style={{
          background: C.surface, borderRadius: 10, border: `1px solid ${C.border}`,
          padding: mobile ? 12 : 16, marginBottom: 16,
        }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
            <div>
              <h2 style={{ color: C.white, margin: '0 0 4px', fontSize: mobile ? 16 : 18, fontWeight: 700 }}>
                {subject.address}
              </h2>
              <div style={{ color: C.muted, fontSize: 12, marginBottom: 8 }}>
                {subject.town} · {subject.inferred_class?.replace(/_/g, ' ')} · {subject.property_type || 'N/A'}
              </div>
            </div>
            {subject.check_amount && (
              <div style={{ background: C.red + '22', border: `1px solid ${C.red}44`, borderRadius: 8, padding: '6px 12px' }}>
                <div style={{ fontSize: 10, color: C.red, fontWeight: 600, textTransform: 'uppercase' }}>Foreclosure Amount</div>
                <div style={{ fontSize: 18, color: C.red, fontWeight: 700 }}>{fmt(Number(subject.check_amount))}</div>
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: mobile ? 16 : 24, flexWrap: 'wrap', marginTop: 8 }}>
            {subject.sqft && <Stat label="Sqft" value={subject.sqft.toLocaleString()} />}
            {subject.bedrooms && <Stat label="Beds" value={String(subject.bedrooms)} />}
            {subject.year_built && <Stat label="Year Built" value={String(subject.year_built)} />}
            {subject.sale_date && <Stat label="Sale Date" value={subject.sale_date} />}
          </div>
        </div>
      )}

      {/* Summary stats */}
      {summary && (
        <div style={{
          display: 'grid', gridTemplateColumns: mobile ? 'repeat(2, 1fr)' : 'repeat(5, 1fr)',
          gap: 10, marginBottom: 16,
        }}>
          <StatCard label="Clean Comps" value={String(summary.clean_comps)} color={C.green} />
          <StatCard label="Outliers" value={String(summary.outliers)} color={C.yellow} />
          <StatCard label="Median Price" value={summary.median_price ? fmtK(summary.median_price) : 'N/A'} color={C.accent} />
          <StatCard label="Median $/sqft" value={summary.median_ppsf ? `$${Math.round(summary.median_ppsf)}` : 'N/A'} color={C.teal} />
          <StatCard label="Price Range" value={summary.min_price && summary.max_price ? `${fmtK(summary.min_price)} – ${fmtK(summary.max_price)}` : 'N/A'} color={C.secondary} />
        </div>
      )}

      {/* Controls */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ display: 'flex', gap: 0 }}>
          <button onClick={() => setViewMode('chart')} style={{ ...tabBtn, borderRadius: '6px 0 0 6px', ...(viewMode === 'chart' ? tabActive : {}) }}>Trend Chart</button>
          <button onClick={() => setViewMode('scatter')} style={{ ...tabBtn, borderRadius: '0 6px 6px 0', ...(viewMode === 'scatter' ? tabActive : {}) }}>Scatter Plot</button>
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, color: C.muted, fontSize: 12, cursor: 'pointer', marginLeft: 'auto' }}>
          <input type="checkbox" checked={showOutliers} onChange={() => setShowOutliers(!showOutliers)} />
          Show outliers ({summary?.outliers || 0})
        </label>
      </div>

      {/* Charts */}
      {viewMode === 'chart' && (
        <div style={{
          width: '100%', height: mobile ? 260 : 380,
          background: C.surface, borderRadius: 10, border: `1px solid ${C.border}`,
          padding: mobile ? '8px 0' : '12px 0',
        }}>
          <ResponsiveContainer>
            <ComposedChart
              data={chartData}
              margin={mobile ? { top: 5, right: 10, left: -10, bottom: 0 } : { top: 10, right: 40, left: 20, bottom: 0 }}
              onClick={(e) => {
                if (e?.activeLabel) setSelectedYear(prev => prev === String(e.activeLabel) ? null : String(e.activeLabel));
              }}
              style={{ cursor: 'pointer' }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="year" tick={{ fill: '#aaa', fontSize: mobile ? 10 : 12 }} />
              <YAxis
                yAxisId="price" tick={{ fill: '#aaa', fontSize: mobile ? 10 : 12 }}
                tickFormatter={(v: number) => fmtK(v)}
                width={mobile ? 55 : 65}
              />
              {!mobile && (
                <YAxis
                  yAxisId="ppsf" orientation="right" tick={{ fill: '#aaa', fontSize: 12 }}
                  tickFormatter={(v: number) => `$${v}`}
                />
              )}
              <Tooltip
                contentStyle={{ background: '#1e1e2e', border: '1px solid #333', borderRadius: 8, fontSize: mobile ? 12 : 14 }}
                labelStyle={{ color: '#fff' }}
                formatter={(value: number | string | undefined, name: string | undefined) => {
                  const n = Number(value ?? 0);
                  const key = name ?? '';
                  return [
                    key === 'avgPrice' ? fmt(n) : `$${n}/sqft`,
                    key === 'avgPrice' ? 'Avg Sale Price' : 'Avg $/SqFt',
                  ];
                }}
              />
              <Legend formatter={(value: string) => value === 'avgPrice' ? 'Avg Price' : 'Avg $/SqFt'} />
              <Bar yAxisId="price" dataKey="avgPrice" fill={C.accent} radius={[4, 4, 0, 0]} barSize={mobile ? 20 : 32} />
              <Line yAxisId={mobile ? 'price' : 'ppsf'} dataKey="avgPpsf" stroke={C.teal} strokeWidth={2.5} dot={{ r: mobile ? 3 : 4, fill: C.teal }} />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {viewMode === 'scatter' && (
        <div style={{
          width: '100%', height: mobile ? 300 : 400,
          background: C.surface, borderRadius: 10, border: `1px solid ${C.border}`,
          padding: mobile ? '8px 0' : '12px 0',
        }}>
          <ResponsiveContainer>
            <ScatterChart margin={mobile ? { top: 10, right: 10, left: -10, bottom: 10 } : { top: 10, right: 30, left: 20, bottom: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#333" />
              <XAxis dataKey="sqft" name="Sqft" tick={{ fill: '#aaa', fontSize: 11 }} tickFormatter={(v: number) => `${(v / 1000).toFixed(1)}K`} label={{ value: 'Sqft', position: 'bottom', fill: '#666', fontSize: 11 }} />
              <YAxis dataKey="price" name="Price" tick={{ fill: '#aaa', fontSize: 11 }} tickFormatter={(v: number) => fmtK(v)} />
              <ZAxis dataKey="score" range={[30, 150]} />
              <Tooltip
                contentStyle={{ background: '#1e1e2e', border: '1px solid #333', borderRadius: 8, fontSize: 12 }}
                formatter={(value: number | string | undefined, name: string | undefined) => {
                  const n = Number(value ?? 0);
                  const key = name ?? '';
                  if (key === 'Price') return [fmt(n), key];
                  if (key === 'Sqft') return [n.toLocaleString(), key];
                  return [n, key];
                }}
                labelFormatter={() => ''}
                content={({ payload }) => {
                  if (!payload?.length) return null;
                  const d = payload[0]?.payload;
                  if (!d) return null;
                  return (
                    <div style={{ background: '#1e1e2e', border: '1px solid #333', borderRadius: 8, padding: 10, fontSize: 12, color: '#fff' }}>
                      <div style={{ fontWeight: 700, marginBottom: 4 }}>{d.address}</div>
                      <div>{fmt(d.price)} · {d.sqft.toLocaleString()} sqft · ${d.ppsf}/sf</div>
                      <div style={{ color: '#888' }}>Score: {d.score} · {d.year}{d.outlier ? ' · ⚠️ Outlier' : ''}</div>
                    </div>
                  );
                }}
              />
              <Scatter
                data={scatterData.filter(d => !d.outlier)}
                fill={C.accent}
                fillOpacity={0.7}
              />
              {showOutliers && (
                <Scatter
                  data={scatterData.filter(d => d.outlier)}
                  fill={C.red}
                  fillOpacity={0.5}
                  shape="triangle"
                />
              )}
            </ScatterChart>
          </ResponsiveContainer>
        </div>
      )}

      <div style={{ fontSize: 11, color: C.muted, marginTop: 8, textAlign: 'center' }}>
        {selectedYear ? `Showing ${selectedYear} — click bar again to clear` : 'Click a bar to filter by year'}
        {' · '} Clean comps only in chart (outliers excluded from averages)
      </div>

      {/* Detail table */}
      <div style={{ marginTop: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <h3 style={{ color: C.white, margin: 0, fontSize: mobile ? 14 : 15, fontWeight: 600 }}>
            {selectedYear ? `Sales in ${selectedYear}` : 'All Comps'}
          </h3>
          <span style={{ color: C.muted, fontSize: 12 }}>{detailComps.length} transactions</span>
        </div>

        <div style={{ maxHeight: 460, overflow: 'auto', borderRadius: 8, border: `1px solid ${C.border}` }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                {['Score', 'Address', 'Price', '$/SqFt', 'SqFt', 'Beds', 'Year', 'Date', ...(mobile ? [] : ['Dist'])].map((h) => (
                  <th key={h} style={{
                    padding: '10px 8px', borderBottom: `2px solid ${C.border}`, fontSize: 10, fontWeight: 600,
                    color: C.secondary, background: C.surface, textAlign: 'left',
                    position: 'sticky', top: 0, zIndex: 1, textTransform: 'uppercase', letterSpacing: '0.04em',
                    whiteSpace: 'nowrap',
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {detailComps.map((c, i) => {
                const isOutlier = c.is_outlier;
                const rowBg = isOutlier ? 'rgba(255,71,87,0.06)' : 'transparent';
                const textColor = isOutlier ? C.muted : C.text;
                const scoreColor = c.comp_score >= 80 ? C.green : c.comp_score >= 60 ? C.teal : c.comp_score >= 40 ? C.yellow : C.red;

                return (
                  <tr key={`${c.pid}-${c.sale_date}-${i}`} style={{ background: rowBg }}
                    title={c.outlier_reason || undefined}>
                    <td style={{ ...cellStyle, color: scoreColor, fontWeight: 700, fontSize: 13 }}>
                      {isOutlier ? '⚠️' : c.comp_score.toFixed(0)}
                    </td>
                    <td style={{ ...cellStyle, color: textColor, maxWidth: 200, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {c.address}
                      {isOutlier && <span style={{ fontSize: 10, color: C.red, marginLeft: 4 }}>outlier</span>}
                    </td>
                    <td style={{ ...cellStyle, color: isOutlier ? C.muted : C.accent, fontWeight: 600 }}>{fmt(c.sale_price)}</td>
                    <td style={{ ...cellStyle, color: isOutlier ? C.muted : C.teal }}>${c.price_per_sqft ? Math.round(c.price_per_sqft) : '-'}</td>
                    <td style={{ ...cellStyle, color: textColor }}>{c.sqft?.toLocaleString() || '-'}</td>
                    <td style={{ ...cellStyle, color: textColor }}>{c.bedrooms ?? '-'}</td>
                    <td style={{ ...cellStyle, color: textColor }}>{c.year_built ?? '-'}</td>
                    <td style={{ ...cellStyle, color: textColor }}>{c.sale_date ? new Date(c.sale_date).toLocaleDateString() : '-'}</td>
                    {!mobile && <td style={{ ...cellStyle, color: C.muted, fontSize: 11 }}>{c.distance_mi ? `${c.distance_mi.toFixed(2)}mi` : '-'}</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

const cellStyle: React.CSSProperties = {
  padding: '8px', borderBottom: '1px solid #2a2d37', fontSize: 12,
};

const tabBtn: React.CSSProperties = {
  background: '#23262f', color: '#8b8f9a', border: '1px solid #333',
  padding: '6px 14px', cursor: 'pointer', fontSize: 12, fontWeight: 600,
};

const tabActive: React.CSSProperties = {
  background: '#6c5ce7', color: '#fff', borderColor: '#6c5ce7',
};

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 10, color: '#5f6370', textTransform: 'uppercase', fontWeight: 600 }}>{label}</div>
      <div style={{ fontSize: 14, color: '#e4e5e9', fontWeight: 600 }}>{value}</div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{
      background: '#181a20', borderRadius: 8, border: '1px solid #2a2d37',
      padding: '10px 12px', textAlign: 'center',
    }}>
      <div style={{ fontSize: 10, color: '#5f6370', textTransform: 'uppercase', fontWeight: 600, marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 16, color, fontWeight: 700 }}>{value}</div>
    </div>
  );
}
