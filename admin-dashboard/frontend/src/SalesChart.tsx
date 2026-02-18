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
}

const SQFT_BUCKETS = [
  { label: 'All', min: 0, max: 99999 },
  { label: '< 800 sqft', min: 0, max: 799 },
  { label: '800–1000 sqft', min: 800, max: 1000 },
  { label: '1000–1300 sqft', min: 1000, max: 1300 },
  { label: '1300–1600 sqft', min: 1300, max: 1600 },
  { label: '> 1600 sqft', min: 1601, max: 99999 },
];

const fmt = (v: number) => `$${Math.round(v).toLocaleString()}`;

export default function SalesChart() {
  const [sales, setSales] = useState<Sale[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [bucket, setBucket] = useState(0); // index into SQFT_BUCKETS

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

  const chartData = useMemo(() => {
    const b = SQFT_BUCKETS[bucket];
    const filtered = sales.filter(s => s.sqft >= b.min && s.sqft <= b.max);

    // Group by year
    const byYear: Record<string, { totalPrice: number; totalPpsf: number; count: number }> = {};
    for (const s of filtered) {
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
  }, [sales, bucket]);

  if (loading) return <div style={{ color: '#aaa', padding: 40 }}>Loading chart data...</div>;
  if (error) return <div style={{ color: '#ff6b6b', padding: 40 }}>{error}</div>;

  return (
    <div style={{ padding: 24 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 24, flexWrap: 'wrap' }}>
        <h2 style={{ color: '#fff', margin: 0, fontSize: 18 }}>
          Whitney Glen Sales Analysis
        </h2>
        <div style={{ display: 'flex', gap: 8 }}>
          {SQFT_BUCKETS.map((b, i) => (
            <button
              key={i}
              onClick={() => setBucket(i)}
              style={{
                padding: '6px 14px',
                borderRadius: 6,
                border: 'none',
                cursor: 'pointer',
                fontSize: 13,
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

      <div style={{ width: '100%', height: 420 }}>
        <ResponsiveContainer>
          <ComposedChart data={chartData} margin={{ top: 10, right: 40, left: 20, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#333" />
            <XAxis dataKey="year" tick={{ fill: '#aaa', fontSize: 12 }} />
            <YAxis
              yAxisId="price"
              tick={{ fill: '#aaa', fontSize: 12 }}
              tickFormatter={(v: number) => `$${(v / 1000).toFixed(0)}K`}
              label={{ value: 'Avg Sale Price', angle: -90, position: 'insideLeft', fill: '#aaa', fontSize: 12 }}
            />
            <YAxis
              yAxisId="ppsf"
              orientation="right"
              tick={{ fill: '#aaa', fontSize: 12 }}
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
            <Legend
              formatter={(value: string) =>
                value === 'avgPrice' ? 'Avg Sale Price' : 'Avg Price/SqFt'
              }
            />
            <Bar yAxisId="price" dataKey="avgPrice" fill="#6c5ce7" radius={[4, 4, 0, 0]} barSize={32} />
            <Line yAxisId="ppsf" dataKey="avgPpsf" stroke="#00cec9" strokeWidth={2.5} dot={{ r: 4, fill: '#00cec9' }} />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}
