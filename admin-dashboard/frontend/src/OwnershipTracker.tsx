import { cn } from '@/lib/utils'
import { StatCard } from '@/components/ui/stat-card'
import { ChartPanel, chartTooltipStyle } from '@/components/ui/chart-panel'
import { PageHeader } from '@/components/ui/page-header'
import { ProgressBar } from '@/components/ui/progress-bar'
import { PieChart, Pie, Cell, Tooltip, ResponsiveContainer } from 'recharts'

/* ── Data Constants ── */

const MEMBERS = ['Blake', 'Connor', 'Preston', 'Ian', 'Yousef'] as const
type Member = (typeof MEMBERS)[number]

const OWNERSHIP: { name: Member; pct: number }[] = MEMBERS.map(name => ({ name, pct: 20 }))

interface Expense {
  description: string
  amount: number
  owedTo: Member[]
  repaid: number
}

const EXPENSES: Expense[] = [
  { description: "Connor's Mac Mini", amount: 600, owedTo: ['Connor'], repaid: 0 },
  { description: "2x Connor's Hosting Fee", amount: 400, owedTo: ['Connor'], repaid: 0 },
  { description: "1x Blake Hosting Fee", amount: 200, owedTo: ['Blake'], repaid: 0 },
  { description: 'Ian/Connor/Blake/Preston Initial Capital', amount: 200, owedTo: ['Ian', 'Connor', 'Blake', 'Preston'], repaid: 0 },
  { description: "Blake/Ian's Scaled Capital", amount: 600, owedTo: ['Blake', 'Ian'], repaid: 0 },
]

const TOTAL_EXPENSES = EXPENSES.reduce((s, e) => s + e.amount, 0)
const TOTAL_REPAID = EXPENSES.reduce((s, e) => s + e.repaid, 0)
const TOTAL_PROFIT = 0 // placeholder

const CHART_COLORS = [
  'hsl(var(--primary))',
  'hsl(var(--chart-2))',
  'hsl(var(--chart-3))',
  'hsl(var(--chart-4))',
  'hsl(var(--chart-5))',
]

/* ── Helpers ── */

function fmtMoney(v: number) {
  return v.toLocaleString(undefined, { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 0 })
}

function expenseColor(repaid: number, total: number) {
  if (repaid >= total) return 'hsl(var(--success, 142 71% 45%))'
  if (repaid > 0) return 'hsl(45 93% 47%)'
  return 'hsl(var(--muted-foreground))'
}

/* ── Component ── */

export default function OwnershipTracker({ mobile }: { mobile: boolean }) {
  const expensesRemaining = TOTAL_EXPENSES - TOTAL_REPAID
  const netDistributable = Math.max(TOTAL_PROFIT - expensesRemaining, 0)
  const perMemberShare = netDistributable / MEMBERS.length

  return (
    <div className={cn('h-full overflow-y-auto', mobile ? 'space-y-4' : 'space-y-5')}>
      <PageHeader title="Ownership" subtitle="Bot ownership, expense repayment, and profit distribution" />

      {/* Summary Cards */}
      <div className={cn('grid gap-3', mobile ? 'grid-cols-2' : 'grid-cols-4')}>
        <StatCard label="Total Profit" value={fmtMoney(TOTAL_PROFIT)} subtitle="All-time gross" />
        <StatCard label="Expenses Remaining" value={fmtMoney(expensesRemaining)} accent subtitle={`of ${fmtMoney(TOTAL_EXPENSES)} total`} />
        <StatCard label="Net Distributable" value={fmtMoney(netDistributable)} subtitle="After expense repayment" />
        <StatCard label="Per-Member Share" value={fmtMoney(perMemberShare)} subtitle="20% each" />
      </div>

      {/* Ownership + Waterfall row */}
      <div className={cn('grid gap-3', mobile ? 'grid-cols-1' : 'grid-cols-2')}>
        {/* Ownership Pie */}
        <ChartPanel title="Ownership Split" subtitle="Equal 5-way">
          <div className="flex items-center gap-4">
            <div className="w-[180px] h-[180px] shrink-0">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie data={OWNERSHIP} dataKey="pct" nameKey="name" cx="50%" cy="50%" innerRadius={50} outerRadius={80} paddingAngle={2} strokeWidth={0}>
                    {OWNERSHIP.map((_, i) => (
                      <Cell key={i} fill={CHART_COLORS[i]} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={chartTooltipStyle} formatter={(v) => `${v}%`} />
                </PieChart>
              </ResponsiveContainer>
            </div>
            <div className="flex flex-col gap-2 flex-1 min-w-0">
              {OWNERSHIP.map((m, i) => (
                <div key={m.name} className="flex items-center gap-2.5">
                  <div className="w-3 h-3 rounded-full shrink-0" style={{ background: CHART_COLORS[i] }} />
                  <span className="text-sm text-foreground font-medium">{m.name}</span>
                  <span className="ml-auto text-sm text-muted-foreground font-mono">{m.pct}%</span>
                </div>
              ))}
            </div>
          </div>
        </ChartPanel>

        {/* Profit Waterfall */}
        <ChartPanel title="Profit Waterfall" subtitle="Distribution logic">
          <div className="flex flex-col gap-3">
            <WaterfallStep step={1} label="Gross Profit" detail="Revenue from all bot activity" icon="↓" />
            <WaterfallStep step={2} label={`Repay ${fmtMoney(TOTAL_EXPENSES)} in Expenses`} detail="Infrastructure & capital costs (in order)" icon="↓" />
            <WaterfallStep step={3} label="Split Remaining 5 Ways" detail="20% each — Blake, Connor, Preston, Ian, Yousef" icon="→" last />
          </div>
        </ChartPanel>
      </div>

      {/* Expense Repayment Tracker */}
      <ChartPanel title="Expense Repayment" subtitle={`${fmtMoney(TOTAL_REPAID)} of ${fmtMoney(TOTAL_EXPENSES)} repaid`}>
        <div className="flex flex-col gap-3">
          {EXPENSES.map((exp, i) => {
            const pctRepaid = exp.amount > 0 ? (exp.repaid / exp.amount) * 100 : 0
            return (
              <div key={i} className="rounded-lg border border-border bg-muted/30 p-3">
                <div className="flex items-start justify-between gap-2 mb-2">
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-foreground truncate">{exp.description}</div>
                    <div className="text-xs text-muted-foreground mt-0.5">
                      Owed to {exp.owedTo.join(', ')}
                    </div>
                  </div>
                  <div className="text-right shrink-0">
                    <div className="text-sm font-mono font-semibold text-foreground">{fmtMoney(exp.amount)}</div>
                    <div className="text-xs text-muted-foreground">{fmtMoney(exp.repaid)} repaid</div>
                  </div>
                </div>
                <ProgressBar value={pctRepaid} color={expenseColor(exp.repaid, exp.amount)} />
              </div>
            )
          })}

          {/* Total bar */}
          <div className="rounded-lg border border-border bg-muted/50 p-3 mt-1">
            <div className="flex items-center justify-between mb-2">
              <span className="text-sm font-bold text-foreground">Total</span>
              <span className="text-sm font-mono font-bold text-foreground">
                {fmtMoney(TOTAL_REPAID)} / {fmtMoney(TOTAL_EXPENSES)}
              </span>
            </div>
            <ProgressBar
              value={TOTAL_EXPENSES > 0 ? (TOTAL_REPAID / TOTAL_EXPENSES) * 100 : 0}
              color={expenseColor(TOTAL_REPAID, TOTAL_EXPENSES)}
            />
          </div>
        </div>
      </ChartPanel>
    </div>
  )
}

/* ── Waterfall Step Sub-component ── */

function WaterfallStep({ step, label, detail, icon, last }: { step: number; label: string; detail: string; icon: string; last?: boolean }) {
  return (
    <div className="flex items-start gap-3">
      <div className="flex flex-col items-center">
        <div className="w-8 h-8 rounded-full bg-primary/15 flex items-center justify-center text-sm font-bold text-primary shrink-0">
          {step}
        </div>
        {!last && <div className="w-px flex-1 bg-border mt-1 min-h-[16px]" />}
      </div>
      <div className="pt-0.5 pb-2 min-w-0">
        <div className="text-sm font-medium text-foreground">{label}</div>
        <div className="text-xs text-muted-foreground mt-0.5">{detail}</div>
      </div>
      {!last && <span className="ml-auto text-muted-foreground text-lg self-center">{icon}</span>}
    </div>
  )
}
