import React, { useEffect, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type LedgerRow = {
  id: number
  event_date: string
  event_type: string
  amount: number
  balance: number
  pick_id: number | null
  sportsbook: string | null
  notes: string | null
  created_at: string | null
}

type LedgerResponse = {
  current_balance: number
  transactions: LedgerRow[]
}

type SummaryResponse = {
  current_balance: number
  daily_pl: Array<{ date: string; pnl: number }>
  balance_chart: Array<{ date: string; balance: number }>
  wins: number
  losses: number
  graded_bets: number
  win_rate: number
  roi: number
  total_pl: number
  total_staked: number
}

const API = '/api/nhl/bankroll'

function fmtMoney(value: number) {
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function fmtPct(value: number) {
  return `${value.toFixed(1)}%`
}

export default function BankrollTracker({ mobile }: { mobile: boolean }) {
  const [ledger, setLedger] = useState<LedgerResponse | null>(null)
  const [summary, setSummary] = useState<SummaryResponse | null>(null)
  const [eventType, setEventType] = useState<'deposit' | 'withdrawal'>('deposit')
  const [amount, setAmount] = useState('')
  const [sportsbook, setSportsbook] = useState('DraftKings')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    const [ledgerRes, summaryRes] = await Promise.all([
      fetch(API),
      fetch(`${API}/summary`),
    ])
    const [ledgerJson, summaryJson] = await Promise.all([
      ledgerRes.json(),
      summaryRes.json(),
    ])
    setLedger(ledgerJson as LedgerResponse)
    setSummary(summaryJson as SummaryResponse)
  }

  useEffect(() => {
    load().catch((err) => setError(String(err)))
  }, [])

  async function submitManualEntry(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const res = await fetch(`${API}/${eventType}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          amount: Number(amount),
          sportsbook,
          notes: notes.trim() || null,
        }),
      })
      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail || `Request failed with ${res.status}`)
      }
      setAmount('')
      setNotes('')
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSubmitting(false)
    }
  }

  if (!ledger || !summary) {
    return <div style={{ color: '#8b8f9a', padding: 24 }}>Loading bankroll…</div>
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, height: '100%', overflow: 'auto', paddingBottom: 24 }}>
      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: mobile ? '1fr' : '1.4fr 1fr' }}>
        <section style={card}>
          <div style={{ fontSize: 11, color: '#8b8f9a', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Current Balance</div>
          <div style={{ fontSize: mobile ? 36 : 48, fontWeight: 800, color: '#f3f4f6', letterSpacing: '-0.04em' }}>{fmtMoney(ledger.current_balance)}</div>
          <div style={{ display: 'grid', gap: 10, gridTemplateColumns: 'repeat(4, minmax(0, 1fr))', marginTop: 18 }}>
            <Stat label="Win Rate" value={fmtPct(summary.win_rate)} />
            <Stat label="ROI" value={fmtPct(summary.roi)} />
            <Stat label="W-L" value={`${summary.wins}-${summary.losses}`} />
            <Stat label="P/L" value={fmtMoney(summary.total_pl)} />
          </div>
        </section>

        <section style={card}>
          <div style={{ fontSize: 11, color: '#8b8f9a', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10 }}>Manual Entry</div>
          <form onSubmit={submitManualEntry} style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="button" onClick={() => setEventType('deposit')} style={eventType === 'deposit' ? tabActive : tab}>Deposit</button>
              <button type="button" onClick={() => setEventType('withdrawal')} style={eventType === 'withdrawal' ? tabActive : tab}>Withdrawal</button>
            </div>
            <input value={amount} onChange={(e) => setAmount(e.target.value)} type="number" min="0" step="0.01" placeholder="Amount" style={input} required />
            <input value={sportsbook} onChange={(e) => setSportsbook(e.target.value)} placeholder="Sportsbook" style={input} />
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes" rows={3} style={{ ...input, resize: 'vertical' }} />
            <button type="submit" style={submitBtn} disabled={submitting}>
              {submitting ? 'Saving…' : `Add ${eventType}`}
            </button>
            {error && <div style={{ color: '#f87171', fontSize: 12 }}>{error}</div>}
          </form>
        </section>
      </div>

      <section style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12, gap: 8, flexWrap: 'wrap' }}>
          <div style={{ fontSize: 11, color: '#8b8f9a', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Balance Over Time</div>
          <div style={{ fontSize: 12, color: '#94a3b8' }}>{summary.balance_chart.length} daily points</div>
        </div>
        <div style={{ height: mobile ? 240 : 300 }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={summary.balance_chart}>
              <CartesianGrid stroke="#2a2d37" vertical={false} />
              <XAxis dataKey="date" stroke="#8b8f9a" tick={{ fontSize: 11 }} />
              <YAxis stroke="#8b8f9a" tick={{ fontSize: 11 }} tickFormatter={(v) => `$${Math.round(v)}`} width={70} />
              <Tooltip formatter={(value) => fmtMoney(Number(value ?? 0))} />
              <Line type="monotone" dataKey="balance" stroke="#4f8cff" strokeWidth={3} dot={false} />
            </LineChart>
          </ResponsiveContainer>
        </div>
      </section>

      <div style={{ display: 'grid', gap: 12, gridTemplateColumns: mobile ? '1fr' : '1fr 1.2fr' }}>
        <section style={card}>
          <div style={{ fontSize: 11, color: '#8b8f9a', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 12 }}>Daily P/L</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 320, overflow: 'auto' }}>
            {summary.daily_pl.slice().reverse().map((row) => (
              <div key={row.date} style={{ display: 'flex', justifyContent: 'space-between', gap: 12, paddingBottom: 8, borderBottom: '1px solid #2a2d37' }}>
                <span style={{ color: '#cbd5e1', fontSize: 13 }}>{row.date}</span>
                <span style={{ color: row.pnl >= 0 ? '#4ade80' : '#f87171', fontWeight: 700, fontVariantNumeric: 'tabular-nums' }}>
                  {row.pnl >= 0 ? '+' : '-'}{fmtMoney(Math.abs(row.pnl))}
                </span>
              </div>
            ))}
          </div>
        </section>

        <section style={card}>
          <div style={{ fontSize: 11, color: '#8b8f9a', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 12 }}>Transaction History</div>
          <div style={{ maxHeight: 320, overflow: 'auto', border: '1px solid #2a2d37', borderRadius: 10 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr>
                  <th style={th}>Date</th>
                  <th style={th}>Type</th>
                  <th style={th}>Amount</th>
                  <th style={th}>Balance</th>
                  <th style={th}>Book</th>
                </tr>
              </thead>
              <tbody>
                {ledger.transactions.map((row) => (
                  <tr key={row.id}>
                    <td style={td}>{row.event_date}</td>
                    <td style={td}>{row.event_type}</td>
                    <td style={{ ...td, color: row.amount >= 0 ? '#4ade80' : '#f87171' }}>{fmtMoney(row.amount)}</td>
                    <td style={td}>{fmtMoney(row.balance)}</td>
                    <td style={td}>{row.sportsbook || row.notes || '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: '#8b8f9a', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: '#f8fafc', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )
}

const card: React.CSSProperties = {
  background: '#181a20',
  border: '1px solid #2a2d37',
  borderRadius: 14,
  padding: 16,
}

const input: React.CSSProperties = {
  background: '#252830',
  border: '1px solid #333642',
  borderRadius: 10,
  color: '#f8fafc',
  padding: '10px 12px',
  fontFamily: 'inherit',
  fontSize: 14,
}

const tab: React.CSSProperties = {
  flex: 1,
  background: '#252830',
  border: '1px solid #333642',
  borderRadius: 10,
  color: '#94a3b8',
  padding: '10px 12px',
  cursor: 'pointer',
  fontFamily: 'inherit',
  fontSize: 13,
  fontWeight: 600,
}

const tabActive: React.CSSProperties = {
  ...tab,
  background: '#4f8cff',
  borderColor: '#4f8cff',
  color: '#ffffff',
}

const submitBtn: React.CSSProperties = {
  background: '#4f8cff',
  border: '1px solid #4f8cff',
  borderRadius: 10,
  color: '#ffffff',
  padding: '10px 12px',
  cursor: 'pointer',
  fontFamily: 'inherit',
  fontSize: 14,
  fontWeight: 700,
}

const th: React.CSSProperties = {
  textAlign: 'left',
  color: '#8b8f9a',
  fontSize: 11,
  fontWeight: 700,
  letterSpacing: '0.04em',
  textTransform: 'uppercase',
  padding: '10px 12px',
  position: 'sticky',
  top: 0,
  background: '#181a20',
  borderBottom: '1px solid #2a2d37',
}

const td: React.CSSProperties = {
  color: '#e2e8f0',
  padding: '10px 12px',
  borderBottom: '1px solid #2a2d37',
  fontVariantNumeric: 'tabular-nums',
}
