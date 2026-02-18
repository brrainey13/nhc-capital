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
  { label: '< 1000 sqft', min: 0, max: 999 },
  { label: '1250 sqft', min: 1250, max: 1250 },
  { label: '> 1250 sqft', min: 1251, max: 99999 },
];

const fmt = (v: number) => `$${Math.round(v).toLocaleString()}`;

export default function SalesChart() {
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

  const cellStyle = { padding: '8px 12px', borderBottom: '1px solid #2a2d35', fontSize: 13, color: '#ccc' };
  const headerStyle = { ...cellStyle, color: '#888', fontWeight: 600, fontSize: 12, textTransform: 'uppercase' as const, position: 'sticky' as const, top: 0, background: '#181a20', zIndex: 1 };

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24, flexWrap: 'wrap' }}>
        <h2 style={{ color: '#fff', margin: 0, fontSize: 18 }}>
          Whitney Glen Sales Analysis
        </h2>
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {SQFT_BUCKETS.map((b, i) => (
            <button
              key={i}
              onClick={() => setBucket(i)}
              style={{
                padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: 13,
                fontWeight: bucket === i ? 700 : 400,
                background: bucket === i ? '#6c5ce7' : '#2a2d35',
                color: bucket === i ? '#fff' : '#aaa',
              }}
            >
              {b.label}
            </button>
          ))}
        </div>
        <span style={{ color: '#666', fontSize: 13 }}>
          {chartData.reduce((s, d) => s + d.count, 0)} sales shown
        </span>
      </div>

      <div style={{ width: '100%', height: 380 }}>
        <ResponsiveContainer>
          <ComposedChart
            data={chartData}
            margin={{ top: 10, right: 40, left: 20, bottom: 0 }}
            onClick={(e) => {
              if (e?.activeLabel) setSelectedYear(prev => prev === String(e.activeLabel) ? null : String(e.activeLabel));
            }}
            style={{ cursor: 'pointer' }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
            <XAxis dataKey="year" tick={{ fill: '#aaa', fontSize: 12 }} />
            <YAxis
              yAxisId="price" tick={{ fill: '#aaa', fontSize: 12 }}
              tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}K`}
              label={{ value: 'Avg Sale Price', angle: -90, position: 'insideLeft', fill: '#aaa', fontSize: 12 }}
            />
            <YAxis
              yAxisId="ppsf" orientation="right" tick={{ fill: '#aaa', fontSize: 12 }}
              tickFormatter={(v: number) => `$${v}`}
              label={{ value: 'Price / SqFt', angle: 90, position: 'insideRight', fill: '#aaa', fontSize: 12 }}
            />
            <Tooltip
              contentStyle={{ background: '#1e1e2e', border: '1px solid #333', borderRadius: 8 }}
              labelStyle={{ color: '#fff' }}
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              formatter={(value: any, name: any) => [
                name === 'avgPrice' ? fmt(Number(value)) : `$${value}/sqft`,
                name === 'avgPrice' ? 'Avg Sale Price' : 'Price/SqFt',
              ]}
            />
            <Legend formatter={(value: string) => value === 'avgPrice' ? 'Avg Sale Price' : 'Avg Price/SqFt'} />
            <Bar yAxisId="price" dataKey="avgPrice" fill="#6c5ce7" radius={[4, 4, 0, 0]} barSize={32} />
            <Line yAxisId="ppsf" dataKey="avgPpsf" stroke="#00cec9" strokeWidth={2.5} dot={{ r: 4, fill: '#00cec9' }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>

      {/* Detail table */}
      <div style={{ marginTop: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
          <h3 style={{ color: '#fff', margin: 0, fontSize: 15 }}>
            {selectedYear ? `Sales in ${selectedYear}` : 'All Sales'}
          </h3>
          {selectedYear && (
            <button
              onClick={() => setSelectedYear(null)}
              style={{
                padding: '4px 10px', borderRadius: 4, border: 'none', cursor: 'pointer',
                background: '#2a2d35', color: '#aaa', fontSize: 12,
              }}
            >
              ✕ Clear filter
            </button>
          )}
          <span style={{ color: '#666', fontSize: 12 }}>
            {detailSales.length} transactions · Click a bar/point to filter by year
          </span>
        </div>
        <div style={{ maxHeight: 360, overflow: 'auto', borderRadius: 8, border: '1px solid #2a2d35' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse' }}>
            <thead>
              <tr>
                <th style={headerStyle}>Address</th>
                <th style={{ ...headerStyle, textAlign: 'right' }}>Sale Price</th>
                <th style={{ ...headerStyle, textAlign: 'right' }}>$/SqFt</th>
                <th style={{ ...headerStyle, textAlign: 'right' }}>SqFt</th>
                <th style={headerStyle}>Date</th>
                <th style={headerStyle}>Buyer</th>
              </tr>
            </thead>
            <tbody>
              {detailSales.map((s, i) => (
                <tr key={i} style={{ background: i % 2 === 0 ? '#15171e' : '#1a1c24' }}>
                  <td style={cellStyle}>{s.address}</td>
                  <td style={{ ...cellStyle, textAlign: 'right', color: '#6c5ce7', fontWeight: 600 }}>{fmt(s.sale_price)}</td>
                  <td style={{ ...cellStyle, textAlign: 'right', color: '#00cec9' }}>${Math.round(s.sale_price / s.sqft)}</td>
                  <td style={{ ...cellStyle, textAlign: 'right' }}>{s.sqft.toLocaleString()}</td>
                  <td style={cellStyle}>{new Date(s.sale_date).toLocaleDateString()}</td>
                  <td style={{ ...cellStyle, fontSize: 12, color: '#888' }}>{s.buyer}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
