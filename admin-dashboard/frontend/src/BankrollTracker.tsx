import React, { useEffect, useState } from 'react'
import { cn } from '@/lib/utils'
import { ChartPanel } from '@/components/ui/chart-panel'
import { InteractiveLineChart } from '@/components/charts/interactive-line-chart'
import { InteractiveBarChart } from '@/components/charts/interactive-bar-chart'
import { ChartControls, downloadCSV } from '@/components/charts/chart-controls'
import { useCountUp } from '@/components/charts/use-count-up'

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

function AnimatedMoney({ value }: { value: number }) {
  const animated = useCountUp(value, 1000)
  return <>{fmtMoney(animated)}</>
}

const inputClasses = 'w-full rounded-lg border border-border bg-muted px-3 py-2.5 text-sm text-foreground font-sans'

export default function BankrollTracker({ mobile }: { mobile: boolean }) {
  const [ledger, setLedger] = useState<LedgerResponse | null>(null)
  const [summary, setSummary] = useState<SummaryResponse | null>(null)
  const [eventType, setEventType] = useState<'deposit' | 'withdrawal'>('deposit')
  const [amount, setAmount] = useState('')
  const [sportsbook, setSportsbook] = useState('DraftKings')
  const [notes, setNotes] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showBalanceBrush, setShowBalanceBrush] = useState(false)

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
    return <div className="p-6 text-muted-foreground">Loading bankroll…</div>
  }

  return (
    <div className="page-enter flex h-full flex-col gap-4 overflow-auto pb-6">
      <div className={cn('grid gap-3', mobile ? 'grid-cols-1' : 'grid-cols-[1.4fr_1fr]')}>
        <section className="card-hover rounded-xl border border-border bg-card p-4">
          <div className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">Current Balance</div>
          <div className={cn('font-extrabold tracking-tighter text-foreground', mobile ? 'text-4xl' : 'text-5xl')}>
            <AnimatedMoney value={ledger.current_balance} />
          </div>
          <div className="mt-4 grid grid-cols-4 gap-2.5">
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">Win Rate</div>
              <div className="text-lg font-bold tabular-nums text-foreground">{fmtPct(summary.win_rate)}</div>
            </div>
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">ROI</div>
              <div className="text-lg font-bold tabular-nums text-foreground">{fmtPct(summary.roi)}</div>
            </div>
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">W-L</div>
              <div className="text-lg font-bold tabular-nums text-foreground">{`${summary.wins}-${summary.losses}`}</div>
            </div>
            <div>
              <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">P/L</div>
              <div className={cn('text-lg font-bold tabular-nums', summary.total_pl >= 0 ? 'text-success' : 'text-destructive')}>{fmtMoney(summary.total_pl)}</div>
            </div>
          </div>
        </section>

        <section className="rounded-xl border border-border bg-card p-4">
          <div className="mb-2.5 text-xs uppercase tracking-wider text-muted-foreground">Manual Entry</div>
          <form onSubmit={submitManualEntry} className="flex flex-col gap-2.5">
            <div className="flex gap-2">
              <button
                type="button"
                onClick={() => setEventType('deposit')}
                className={cn(
                  'flex-1 rounded-lg border px-3 py-2.5 text-sm font-semibold cursor-pointer font-sans transition-colors',
                  eventType === 'deposit'
                    ? 'bg-primary border-primary text-primary-foreground'
                    : 'bg-muted border-border text-muted-foreground'
                )}
              >
                Deposit
              </button>
              <button
                type="button"
                onClick={() => setEventType('withdrawal')}
                className={cn(
                  'flex-1 rounded-lg border px-3 py-2.5 text-sm font-semibold cursor-pointer font-sans transition-colors',
                  eventType === 'withdrawal'
                    ? 'bg-primary border-primary text-primary-foreground'
                    : 'bg-muted border-border text-muted-foreground'
                )}
              >
                Withdrawal
              </button>
            </div>
            <input value={amount} onChange={(e) => setAmount(e.target.value)} type="number" min="0" step="0.01" placeholder="Amount" className={inputClasses} required />
            <input value={sportsbook} onChange={(e) => setSportsbook(e.target.value)} placeholder="Sportsbook" className={inputClasses} />
            <textarea value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Notes" rows={3} className={cn(inputClasses, 'resize-y')} />
            <button
              type="submit"
              className="rounded-lg bg-primary px-3 py-2.5 text-sm font-bold text-primary-foreground hover:bg-primary/90 cursor-pointer font-sans transition-colors"
              disabled={submitting}
            >
              {submitting ? 'Saving…' : `Add ${eventType}`}
            </button>
            {error && <div className="text-xs text-destructive">{error}</div>}
          </form>
        </section>
      </div>

      <ChartPanel
        title="Balance Over Time"
        subtitle={`${summary.balance_chart.length} daily points`}
        height={mobile ? 260 : 320}
        actions={
          <ChartControls
            showBrush={showBalanceBrush}
            onBrushToggle={setShowBalanceBrush}
            exportData={() => downloadCSV(summary.balance_chart as Record<string, unknown>[], 'balance-history.csv')}
          />
        }
      >
        <InteractiveLineChart
          data={summary.balance_chart}
          lines={[{ dataKey: 'balance', color: 'hsl(var(--primary))', label: 'Balance' }]}
          xKey="date"
          formatY={(v) => `$${Math.round(v)}`}
          showBrush={showBalanceBrush}
          height={mobile ? 240 : 300}
          gradientFill
        />
      </ChartPanel>

      {/* Daily P/L Waterfall */}
      <ChartPanel
        title="Daily P/L"
        subtitle="Profit and loss by day"
        height={mobile ? 200 : 240}
        actions={
          <ChartControls
            exportData={() => downloadCSV(summary.daily_pl as Record<string, unknown>[], 'daily-pl.csv')}
          />
        }
      >
        <InteractiveBarChart
          data={summary.daily_pl}
          bars={[{
            dataKey: 'pnl',
            color: 'hsl(var(--chart-1))',
            label: 'P/L',
            colorByValue: true,
            positiveColor: 'hsl(var(--success))',
            negativeColor: 'hsl(var(--destructive))',
          }]}
          xKey="date"
          formatY={(v) => fmtMoney(v)}
          height={mobile ? 180 : 220}
        />
      </ChartPanel>

      <div className={cn('grid gap-3', mobile ? 'grid-cols-1' : 'grid-cols-[1fr_1.2fr]')}>
        <section className="rounded-xl border border-border bg-card p-4">
          <div className="mb-3 text-xs uppercase tracking-wider text-muted-foreground">Daily P/L History</div>
          {summary.daily_pl.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-6 text-center">
              <div className="text-3xl">💰</div>
              <div className="text-sm text-muted-foreground">No daily P/L data yet</div>
            </div>
          ) : (
            <div className="flex max-h-80 flex-col gap-2 overflow-auto">
              {summary.daily_pl.slice().reverse().map((row) => (
                <div key={row.date} className="flex items-center justify-between gap-3 border-b border-border/50 pb-2 transition-colors hover:bg-muted/30">
                  <span className="text-sm text-foreground">{row.date}</span>
                  <span className={cn('font-bold tabular-nums', row.pnl >= 0 ? 'text-success' : 'text-destructive')}>
                    {row.pnl >= 0 ? '+' : '-'}{fmtMoney(Math.abs(row.pnl))}
                  </span>
                </div>
              ))}
            </div>
          )}
        </section>

        <section className="rounded-xl border border-border bg-card p-4">
          <div className="mb-3 text-xs uppercase tracking-wider text-muted-foreground">Transaction History</div>
          {ledger.transactions.length === 0 ? (
            <div className="flex flex-col items-center gap-2 py-6 text-center">
              <div className="text-3xl">📝</div>
              <div className="text-sm text-muted-foreground">No transactions recorded yet</div>
            </div>
          ) : (
            <div className="max-h-80 overflow-auto rounded-lg border border-border">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs font-bold uppercase tracking-wider text-muted-foreground">
                    <th className="sticky top-0 bg-card px-3 py-2.5">Date</th>
                    <th className="sticky top-0 bg-card px-3 py-2.5">Type</th>
                    <th className="sticky top-0 bg-card px-3 py-2.5">Amount</th>
                    <th className="sticky top-0 bg-card px-3 py-2.5">Balance</th>
                    <th className="sticky top-0 bg-card px-3 py-2.5">Book</th>
                  </tr>
                </thead>
                <tbody>
                  {ledger.transactions.map((row) => (
                    <tr key={row.id} className="border-b border-border/50 transition-colors hover:bg-muted/50">
                      <td className="px-3 py-2.5 tabular-nums text-foreground">{row.event_date}</td>
                      <td className="px-3 py-2.5 tabular-nums text-foreground">{row.event_type}</td>
                      <td className={cn('px-3 py-2.5 tabular-nums', row.amount >= 0 ? 'text-success' : 'text-destructive')}>{fmtMoney(row.amount)}</td>
                      <td className="px-3 py-2.5 tabular-nums text-foreground">{fmtMoney(row.balance)}</td>
                      <td className="px-3 py-2.5 tabular-nums text-foreground">{row.sportsbook || row.notes || '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
