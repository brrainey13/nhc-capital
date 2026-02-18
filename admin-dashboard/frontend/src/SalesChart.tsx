import { useEffect, useMemo, useState } from 'react';
import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
  ResponsiveContainer,
} from 'recharts';

interface Sale {
  sale_price: number;
  sale_date: string;
  sqft: number;
  address: string;
  buyer: string;
  book_page: string;
}

const SQFT_BUCKETS = [
  { label: 'All', min: 0, max: 99999 },
  { label: '< 1000', min: 0, max: 999 },
  { label: '1250', min: 1250, max: 1250 },
  { label: '> 1250', min: 1251, max: 99999 },
];

const fmt = (v: number) => `$${Math.round(v).toLocaleString()}`;

function useIsMobile(bp = 768) {
  const [m, setM] = useState(window.innerWidth < bp);
  useEffect(() => {
    const h = () => setM(window.innerWidth < bp);
    window.addEventListener('resize', h);
    return () => window.removeEventListener('resize', h);
  }, [bp]);
  return m;
}

export default function SalesChart() {
  const mobile = useIsMobile();
  const [sales, setSales] = useState<Sale[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bucket, setBucket] = useState(0);
  const [selectedYear, setSelectedYear] = useState<string | null>(null);

  useEffect(() => {
    fetch('/api/tables/whitney_glen_sales/data?limit=500')
      .then(r => r.json())
      .then(json => {
        const rows = (json.rows || json.data || []).filter(
          (r: Sale) => r.sale_price > 0 && r.sqft > 0 && r.sale_date
        );
        setSales(rows);
      })
      .catch(e => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const filteredSales = useMemo(() => {
    const b = SQFT_BUCKETS[bucket];
    return sales.filter(s => s.sqft >= b.min && s.sqft <= b.max);
  }, [sales, bucket]);

  const chartData = useMemo(() => {
    const byYear: Record<string, { totalPrice: number; totalPpsf: number; count: number }> = {};
    for (const s of filteredSales) {
      const year = new Date(s.sale_date).getFullYear().toString();
      if (!byYear[year]) byYear[year] = { totalPrice: 0, totalPpsf: 0, count: 0 };
      byYear[year].totalPrice += s.sale_price;
      byYear[year].totalPpsf += s.sale_price / s.sqft;
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
  }, [filteredSales]);

  const detailSales = useMemo(() => {
    if (!selectedYear) return filteredSales.slice().sort((a, b) => b.sale_date.localeCompare(a.sale_date));
    return filteredSales
      .filter(s => new Date(s.sale_date).getFullYear().toString() === selectedYear)
      .sort((a, b) => b.sale_date.localeCompare(a.sale_date));
  }, [filteredSales, selectedYear]);

  if (loading) return <div style={{ color: '#aaa', padding: 40 }}>Loading chart data...</div>;
  if (error) return <div style={{ color: '#ff6b6b', padding: 40 }}>{error}</div>;

  const C = {
    bg: '#0f1117', surface: '#181a20', border: '#2a2d37', text: '#e4e5e9',
    muted: '#5f6370', secondary: '#8b8f9a', accent: '#6c5ce7', teal: '#00cec9', white: '#fff',
  };

  // Summary stats
  const totalSales = chartData.reduce((s, d) => s + d.count, 0);
  const latestYear = chartData.length > 0 ? chartData[chartData.length - 1] : null;

  return (
    <div style={{ padding: mobile ? 12 : 24 }}>
      {/* Header */}
      <h2 style={{ color: C.white, margin: '0 0 4px', fontSize: mobile ? 16 : 18, fontWeight: 700 }}>
        Whitney Glen Sales Analysis
      </h2>
      <div style={{ color: C.muted, fontSize: 12, marginBottom: 16 }}>
        {totalSales} total sales
        {latestYear && <> · Latest avg: <strong style={{ color: C.accent }}>{fmt(latestYear.avgPrice)}</strong> ({latestYear.year})</>}
      </div>

      {/* Stat cards */}
      {mobile && chartData.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 16 }}>
          {[
            { label: 'Avg Price', value: latestYear ? fmt(latestYear.avgPrice) : '—', color: C.accent },
            { label: 'Avg $/SqFt', value: latestYear ? `$${latestYear.avgPpsf}` : '—', color: C.teal },
          ].map((s, i) => (
            <div key={i} style={{ background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 12 }}>
              <div style={{ fontSize: 10, color: C.muted, textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600 }}>{s.label}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: s.color, marginTop: 2 }}>{s.value}</div>
              <div style={{ fontSize: 10, color: C.muted }}>{latestYear?.year}</div>
            </div>
          ))}
        </div>
      )}

      {/* SqFt filter buttons */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 16, flexWrap: 'wrap' }}>
        {SQFT_BUCKETS.map((b, i) => (
          <button
            key={i}
            onClick={() => setBucket(i)}
            style={{
              padding: mobile ? '10px 16px' : '6px 14px',
              borderRadius: 8, border: 'none', cursor: 'pointer',
              fontSize: mobile ? 14 : 13,
              fontWeight: bucket === i ? 700 : 400,
              background: bucket === i ? C.accent : '#2a2d35',
              color: bucket === i ? '#fff' : '#aaa',
              minHeight: mobile ? 44 : 'auto',
            }}
          >
            {b.label}{!mobile && ' sqft'}
          </button>
        ))}
      </div>

      {/* Chart */}
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
              tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}K`}
              width={mobile ? 50 : 60}
              label={mobile ? undefined : { value: 'Avg Sale Price', angle: -90, position: 'insideLeft', fill: '#aaa', fontSize: 12 }}
            />
            {!mobile && (
              <YAxis
                yAxisId="ppsf" orientation="right" tick={{ fill: '#aaa', fontSize: 12 }}
                tickFormatter={(v: number) => `$${v}`}
                label={{ value: 'Price / SqFt', angle: 90, position: 'insideRight', fill: '#aaa', fontSize: 12 }}
              />
            )}
            <Tooltip
              contentStyle={{ background: '#1e1e2e', border: '1px solid #333', borderRadius: 8, fontSize: mobile ? 12 : 14 }}
              labelStyle={{ color: '#fff' }}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              formatter={(value: any, name: any) => [
                name === 'avgPrice' ? fmt(Number(value)) : `$${value}/sqft`,
                name === 'avgPrice' ? 'Avg Sale Price' : 'Price/SqFt',
              ]}
            />
            <Legend
              formatter={(value: string) => value === 'avgPrice' ? 'Avg Price' : 'Avg $/SqFt'}
              wrapperStyle={{ fontSize: mobile ? 11 : 13 }}
            />
            <Bar yAxisId="price" dataKey="avgPrice" fill={C.accent} radius={[4, 4, 0, 0]} barSize={mobile ? 20 : 32} />
            <Line yAxisId={mobile ? 'price' : 'ppsf'} dataKey="avgPpsf" stroke={C.teal} strokeWidth={2.5} dot={{ r: mobile ? 3 : 4, fill: C.teal }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Year filter hint */}
      <div style={{ fontSize: 11, color: C.muted, marginTop: 8, textAlign: 'center' }}>
        {selectedYear ? `Showing ${selectedYear}` : 'Tap a bar to filter by year'}
        {selectedYear && (
          <button onClick={() => setSelectedYear(null)}
            style={{ marginLeft: 8, background: 'none', border: 'none', color: C.accent, cursor: 'pointer', fontSize: 11 }}>
            ✕ Clear
          </button>
        )}
      </div>

      {/* Sales detail */}
      <div style={{ marginTop: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <h3 style={{ color: C.white, margin: 0, fontSize: mobile ? 14 : 15, fontWeight: 600 }}>
            {selectedYear ? `Sales in ${selectedYear}` : 'All Sales'}
          </h3>
          <span style={{ color: C.muted, fontSize: 12 }}>{detailSales.length} transactions</span>
        </div>

        {/* Mobile: card view */}
        {mobile ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {detailSales.slice(0, 50).map((s, i) => (
              <div key={i} style={{
                background: C.surface, border: `1px solid ${C.border}`, borderRadius: 10, padding: 14,
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
                  <div style={{ fontSize: 13, color: C.white, fontWeight: 600, flex: 1 }}>{s.address}</div>
                  <div style={{ fontSize: 15, color: C.accent, fontWeight: 700, marginLeft: 8 }}>{fmt(s.sale_price)}</div>
                </div>
                <div style={{ display: 'flex', gap: 16, fontSize: 12 }}>
                  <span style={{ color: C.teal }}>${Math.round(s.sale_price / s.sqft)}/sqft</span>
                  <span style={{ color: C.secondary }}>{s.sqft.toLocaleString()} sqft</span>
                  <span style={{ color: C.muted }}>{new Date(s.sale_date).toLocaleDateString()}</span>
                </div>
                {s.buyer && <div style={{ fontSize: 11, color: C.muted, marginTop: 4 }}>Buyer: {s.buyer}</div>}
              </div>
            ))}
            {detailSales.length > 50 && (
              <div style={{ textAlign: 'center', color: C.muted, fontSize: 12, padding: 12 }}>
                Showing 50 of {detailSales.length}
              </div>
            )}
          </div>
        ) : (
          /* Desktop: table view */
          <div style={{ maxHeight: 360, overflow: 'auto', borderRadius: 8, border: `1px solid ${C.border}` }}>
            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
              <thead>
                <tr>
                  {['Address', 'Sale Price', '$/SqFt', 'SqFt', 'Date', 'Buyer'].map((h, i) => (
                    <th key={h} style={{
                      padding: '10px 12px', borderBottom: `2px solid ${C.border}`, fontSize: 11, fontWeight: 600,
                      color: C.secondary, background: C.surface, textAlign: i >= 1 && i <= 3 ? 'right' : 'left',
                      position: 'sticky', top: 0, zIndex: 1, textTransform: 'uppercase', letterSpacing: '0.04em',
                    }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {detailSales.map((s, i) => (
                  <tr key={i}
                    onMouseEnter={e => (e.currentTarget.style.background = '#1e2028')}
                    onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                    <td style={{ padding: '8px 12px', borderBottom: `1px solid ${C.border}`, fontSize: 13, color: C.text }}>{s.address}</td>
                    <td style={{ padding: '8px 12px', borderBottom: `1px solid ${C.border}`, fontSize: 13, color: C.accent, fontWeight: 600, textAlign: 'right' }}>{fmt(s.sale_price)}</td>
                    <td style={{ padding: '8px 12px', borderBottom: `1px solid ${C.border}`, fontSize: 13, color: C.teal, textAlign: 'right' }}>${Math.round(s.sale_price / s.sqft)}</td>
                    <td style={{ padding: '8px 12px', borderBottom: `1px solid ${C.border}`, fontSize: 13, color: C.text, textAlign: 'right' }}>{s.sqft.toLocaleString()}</td>
                    <td style={{ padding: '8px 12px', borderBottom: `1px solid ${C.border}`, fontSize: 13, color: C.text }}>{new Date(s.sale_date).toLocaleDateString()}</td>
                    <td style={{ padding: '8px 12px', borderBottom: `1px solid ${C.border}`, fontSize: 12, color: C.muted }}>{s.buyer}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
