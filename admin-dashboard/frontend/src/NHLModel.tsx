import React, { useEffect, useMemo, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

type ModelInfo = {
  model_type: string
  model_found: boolean
  model_path: string | null
  n_features: number
  n_training_samples: number
  training_date: string | null
  feature_importances: Array<{ feature: string; importance: number }>
}

type Pick = {
  pick_id: number
  pick_date: string | null
  player: string
  market: string
  side: string | null
  line: number
  odds: number | null
  book: string | null
  edge: number
  edge_pct: number
  model_prob: number
  model_prob_pct: number
  implied_prob: number
  implied_prob_pct: number
  stake: number
  stake_dollars: number
  strategy: string | null
  confidence: string | null
  result: string | null
  pnl: number
}

type TodayPicksResponse = {
  pick_date: string
  count: number
  total_stake: number
  total_stake_dollars: number
  picks: Pick[]
}

type HistoryResponse = {
  summary: {
    wins: number
    losses: number
    pushes: number
    pending: number
    record: string
    total_pl: number
    total_staked: number
    roi: number
  }
  strategies: string[]
  picks: Pick[]
}

type StrategyRow = {
  strategy: string
  pick_count: number
  wins: number
  losses: number
  pushes: number
  pending: number
  record: string
  roi: number
  avg_edge: number
  total_pl: number
  total_staked: number
}

type StrategyResponse = {
  strategies: StrategyRow[]
}

type OddsOffer = {
  book: string
  side: string
  line: number
  odds: number | null
  pulled_at: string | null
}

type OddsMarket = {
  player: string
  market: string
  offers: OddsOffer[]
  best_over_odds: OddsOffer | null
  best_under_odds: OddsOffer | null
}

type OddsGame = {
  game: string
  snapshot_date: string | null
  markets: OddsMarket[]
}

type OddsSnapshotResponse = {
  source: string
  snapshot_date: string | null
  games: OddsGame[]
}

type SortKey = 'player' | 'market' | 'line' | 'odds' | 'book' | 'edge_pct' | 'model_prob_pct' | 'stake'

const API = '/api/nhl'

function fmtMoney(value: number) {
  return value.toLocaleString(undefined, {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

function fmtPct(value: number, digits = 1) {
  return `${value.toFixed(digits)}%`
}

function fmtOdds(value: number | null) {
  if (value == null) return '—'
  return value > 0 ? `+${value}` : `${value}`
}

function fmtDate(value: string | null) {
  if (!value) return '—'
  return new Date(value).toLocaleDateString()
}

function edgeColor(edgePct: number) {
  if (edgePct > 10) return '#4ade80'
  if (edgePct >= 5) return '#facc15'
  return '#e5e7eb'
}

function resultColor(result: string | null) {
  if (result === 'W') return '#4ade80'
  if (result === 'L') return '#f87171'
  if (result === 'P') return '#cbd5e1'
  return '#94a3b8'
}

function sortPicks(picks: Pick[], key: SortKey, dir: 'asc' | 'desc') {
  const sorted = picks.slice().sort((a, b) => {
    const av = a[key]
    const bv = b[key]
    if (typeof av === 'number' && typeof bv === 'number') {
      return dir === 'asc' ? av - bv : bv - av
    }
    return dir === 'asc'
      ? String(av ?? '').localeCompare(String(bv ?? ''))
      : String(bv ?? '').localeCompare(String(av ?? ''))
  })
  return sorted
}

function HeaderStat({ label, value, accent }: { label: string; value: string; accent?: boolean }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: '#8b8f9a', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 20, fontWeight: 700, color: accent ? '#4f8cff' : '#f8fafc', fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )
}

export default function NHLModel({ mobile }: { mobile: boolean }) {
  const [modelInfo, setModelInfo] = useState<ModelInfo | null>(null)
  const [today, setToday] = useState<TodayPicksResponse | null>(null)
  const [history, setHistory] = useState<HistoryResponse | null>(null)
  const [strategies, setStrategies] = useState<StrategyResponse | null>(null)
  const [odds, setOdds] = useState<OddsSnapshotResponse | null>(null)
  const [strategyFilter, setStrategyFilter] = useState('All')
  const [sortKey, setSortKey] = useState<SortKey>('edge_pct')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [error, setError] = useState<string | null>(null)

  async function load(activeStrategy = strategyFilter) {
    const historyParams = new URLSearchParams({ days: '30' })
    if (activeStrategy !== 'All') historyParams.set('strategy', activeStrategy)
    const [infoRes, todayRes, historyRes, strategyRes, oddsRes] = await Promise.all([
      fetch(`${API}/model/info`),
      fetch(`${API}/picks/today`),
      fetch(`${API}/picks/history?${historyParams}`),
      fetch(`${API}/model/strategies?days=30`),
      fetch(`${API}/odds/snapshot`),
    ])
    const [infoJson, todayJson, historyJson, strategyJson, oddsJson] = await Promise.all([
      infoRes.json(),
      todayRes.json(),
      historyRes.json(),
      strategyRes.json(),
      oddsRes.json(),
    ])
    setModelInfo(infoJson as ModelInfo)
    setToday(todayJson as TodayPicksResponse)
    setHistory(historyJson as HistoryResponse)
    setStrategies(strategyJson as StrategyResponse)
    setOdds(oddsJson as OddsSnapshotResponse)
  }

  useEffect(() => {
    load(strategyFilter).catch((err) => setError(err instanceof Error ? err.message : String(err)))
  }, [strategyFilter])

  const sortedTodayPicks = useMemo(() => {
    if (!today) return []
    return sortPicks(today.picks, sortKey, sortDir)
  }, [today, sortKey, sortDir])

  const topFeatures = modelInfo?.feature_importances.slice(0, 15) ?? []
  const strategyOptions = useMemo(() => ['All', ...(history?.strategies ?? [])], [history])

  if (error) {
    return <div style={{ color: '#f87171', padding: 24 }}>Failed to load model outputs: {error}</div>
  }

  if (!modelInfo || !today || !history || !strategies || !odds) {
    return <div style={{ color: '#8b8f9a', padding: 24 }}>Loading model outputs…</div>
  }

  function toggleSort(nextKey: SortKey) {
    if (sortKey === nextKey) {
      setSortDir(sortDir === 'desc' ? 'asc' : 'desc')
      return
    }
    setSortKey(nextKey)
    setSortDir('desc')
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16, height: '100%', overflow: 'auto', paddingBottom: 24 }}>
      <section style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', marginBottom: 16 }}>
          <div>
            <div style={{ fontSize: 11, color: '#8b8f9a', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>Model Info</div>
            <div style={{ fontSize: mobile ? 24 : 30, fontWeight: 800, color: '#f8fafc', letterSpacing: '-0.04em' }}>{modelInfo.model_type}</div>
          </div>
          {!modelInfo.model_found && <div style={{ color: '#facc15', fontSize: 12 }}>Model artifact not found. Showing metadata fallbacks only.</div>}
        </div>
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: mobile ? '1fr 1fr' : 'repeat(4, minmax(0, 1fr))', marginBottom: 18 }}>
          <HeaderStat label="Features" value={String(modelInfo.n_features)} />
          <HeaderStat label="Training Rows" value={modelInfo.n_training_samples.toLocaleString()} />
          <HeaderStat label="Training Date" value={modelInfo.training_date || '—'} />
          <HeaderStat label="Artifact" value={modelInfo.model_path ? 'Found' : 'Missing'} accent />
        </div>
        <div style={{ height: mobile ? 320 : 360 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={topFeatures} layout="vertical" margin={{ top: 8, right: 20, bottom: 8, left: 64 }}>
              <CartesianGrid stroke="#2a2d37" horizontal={false} />
              <XAxis type="number" stroke="#8b8f9a" tick={{ fontSize: 11 }} />
              <YAxis type="category" dataKey="feature" stroke="#8b8f9a" tick={{ fontSize: 11 }} width={150} />
              <Tooltip formatter={(value) => Number(value).toFixed(0)} />
              <Bar dataKey="importance" radius={[0, 6, 6, 0]}>
                {topFeatures.map((item) => <Cell key={item.feature} fill="#4f8cff" />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: '#8b8f9a', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Today&apos;s Picks</div>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <span style={subtleText}>{today.count} picks</span>
            <span style={subtleText}>Stake {today.total_stake.toFixed(1)}u</span>
            <span style={subtleText}>{fmtMoney(today.total_stake_dollars)}</span>
          </div>
        </div>
        {today.picks.length === 0 ? (
          <div style={{ color: '#8b8f9a', padding: '14px 0' }}>No picks generated yet today</div>
        ) : (
          <div style={{ maxHeight: 420, overflow: 'auto', border: '1px solid #2a2d37', borderRadius: 12 }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr>
                  <th style={thBtn} onClick={() => toggleSort('player')}>Player</th>
                  <th style={thBtn} onClick={() => toggleSort('market')}>Market</th>
                  <th style={thBtn} onClick={() => toggleSort('line')}>Line</th>
                  <th style={thBtn} onClick={() => toggleSort('odds')}>Odds</th>
                  <th style={thBtn} onClick={() => toggleSort('book')}>Book</th>
                  <th style={thBtn} onClick={() => toggleSort('edge_pct')}>Edge%</th>
                  <th style={thBtn} onClick={() => toggleSort('model_prob_pct')}>Model Prob</th>
                  <th style={thBtn} onClick={() => toggleSort('stake')}>Stake</th>
                </tr>
              </thead>
              <tbody>
                {sortedTodayPicks.map((pick) => (
                  <tr key={pick.pick_id} style={{ background: 'rgba(255,255,255,0.01)' }}>
                    <td style={td}>{pick.player}</td>
                    <td style={td}>{pick.market}</td>
                    <td style={td}>{pick.line.toFixed(1)}</td>
                    <td style={td}>{fmtOdds(pick.odds)}</td>
                    <td style={td}>{pick.book || '—'}</td>
                    <td style={{ ...td, color: edgeColor(pick.edge_pct), fontWeight: 700 }}>{fmtPct(pick.edge_pct, 2)}</td>
                    <td style={td}>{pick.model_prob_pct > 0 ? fmtPct(pick.model_prob_pct, 1) : '—'}</td>
                    <td style={td}>{pick.stake.toFixed(1)}u</td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr>
                  <td style={tfootCell} colSpan={7}>Total Stake</td>
                  <td style={tfootCell}>{today.total_stake.toFixed(1)}u</td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </section>

      <section style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: mobile ? 'stretch' : 'baseline', gap: 12, flexDirection: mobile ? 'column' : 'row', marginBottom: 12 }}>
          <div>
            <div style={{ fontSize: 11, color: '#8b8f9a', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 6 }}>Pick History</div>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <span style={subtleText}>Record {history.summary.record}</span>
              <span style={subtleText}>ROI {fmtPct(history.summary.roi, 2)}</span>
              <span style={subtleText}>P/L {fmtMoney(history.summary.total_pl)}</span>
            </div>
          </div>
          <label style={{ display: 'flex', alignItems: 'center', gap: 8, color: '#cbd5e1', fontSize: 13 }}>
            Strategy
            <select value={strategyFilter} onChange={(e) => setStrategyFilter(e.target.value)} style={select}>
              {strategyOptions.map((option) => <option key={option} value={option}>{option}</option>)}
            </select>
          </label>
        </div>
        <div style={{ maxHeight: 420, overflow: 'auto', border: '1px solid #2a2d37', borderRadius: 12 }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
            <thead>
              <tr>
                <th style={th}>Date</th>
                <th style={th}>Player</th>
                <th style={th}>Market</th>
                <th style={th}>Result</th>
                <th style={th}>P/L</th>
              </tr>
            </thead>
            <tbody>
              {history.picks.map((pick) => (
                <tr key={pick.pick_id}>
                  <td style={td}>{fmtDate(pick.pick_date)}</td>
                  <td style={td}>{pick.player}</td>
                  <td style={td}>{pick.market}</td>
                  <td style={{ ...td, color: resultColor(pick.result), fontWeight: 700 }}>{pick.result || 'Pending'}</td>
                  <td style={{ ...td, color: pick.pnl >= 0 ? '#4ade80' : '#f87171' }}>{pick.result === 'Pending' ? '—' : fmtMoney(pick.pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section style={card}>
        <div style={{ fontSize: 11, color: '#8b8f9a', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 12 }}>Strategy Performance</div>
        <div style={{ display: 'grid', gap: 12, gridTemplateColumns: mobile ? '1fr' : 'repeat(auto-fit, minmax(180px, 1fr))', marginBottom: 16 }}>
          {strategies.strategies.map((row) => (
            <div key={row.strategy} style={miniCard}>
              <div style={{ fontSize: 12, color: '#8b8f9a', marginBottom: 6 }}>{row.strategy}</div>
              <div style={{ fontSize: 22, fontWeight: 700, color: '#f8fafc', marginBottom: 10 }}>{row.record}</div>
              <div style={cardStatRow}><span style={subtleText}>ROI</span><span style={{ color: row.roi >= 0 ? '#4ade80' : '#f87171' }}>{fmtPct(row.roi, 2)}</span></div>
              <div style={cardStatRow}><span style={subtleText}>Avg Edge</span><span style={{ color: '#facc15' }}>{fmtPct(row.avg_edge, 2)}</span></div>
              <div style={cardStatRow}><span style={subtleText}>Picks</span><span style={{ color: '#e2e8f0' }}>{row.pick_count}</span></div>
            </div>
          ))}
        </div>
        <div style={{ height: mobile ? 280 : 320 }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={strategies.strategies}>
              <CartesianGrid stroke="#2a2d37" vertical={false} />
              <XAxis dataKey="strategy" stroke="#8b8f9a" tick={{ fontSize: 11 }} />
              <YAxis stroke="#8b8f9a" tick={{ fontSize: 11 }} tickFormatter={(value) => `${value}%`} />
              <Tooltip formatter={(value) => fmtPct(Number(value), 2)} />
              <Bar dataKey="roi" radius={[6, 6, 0, 0]}>
                {strategies.strategies.map((row) => <Cell key={row.strategy} fill={row.roi >= 0 ? '#4ade80' : '#f87171'} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section style={card}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
          <div style={{ fontSize: 11, color: '#8b8f9a', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Odds Snapshot</div>
          <div style={subtleText}>Source {odds.source} · Snapshot {odds.snapshot_date || '—'}</div>
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {odds.games.length === 0 && <div style={{ color: '#8b8f9a' }}>No odds snapshot available.</div>}
          {odds.games.map((game) => (
            <div key={game.game} style={miniCard}>
              <div style={{ fontSize: 16, color: '#f8fafc', fontWeight: 700, marginBottom: 10 }}>{game.game}</div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
                {game.markets.map((market) => (
                  <div key={`${market.player}-${market.market}`} style={{ borderTop: '1px solid #2a2d37', paddingTop: 8 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 6 }}>
                      <span style={{ color: '#e2e8f0', fontWeight: 600 }}>{market.player}</span>
                      <span style={subtleText}>{market.market}</span>
                    </div>
                    <div style={{ display: 'grid', gap: 8, gridTemplateColumns: mobile ? '1fr' : 'repeat(auto-fit, minmax(140px, 1fr))' }}>
                      {market.offers.map((offer, idx) => {
                        const isBest = (offer.side === 'over' && market.best_over_odds?.book === offer.book && market.best_over_odds?.odds === offer.odds)
                          || (offer.side === 'under' && market.best_under_odds?.book === offer.book && market.best_under_odds?.odds === offer.odds)
                        return (
                          <div key={`${offer.book}-${offer.side}-${idx}`} style={{ ...offerCard, borderColor: isBest ? '#4ade80' : '#333642', background: isBest ? 'rgba(74,222,128,0.08)' : '#181a20' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                              <span style={{ color: '#f8fafc', fontWeight: 600 }}>{offer.book}</span>
                              <span style={{ color: '#94a3b8' }}>{offer.side.toUpperCase()}</span>
                            </div>
                            <div style={{ marginTop: 6, color: '#e2e8f0' }}>Line {offer.line.toFixed(1)} · {fmtOdds(offer.odds)}</div>
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* TODO Phase 2: LLM Model Interpretation
         - Call /api/nhl/model/interpret endpoint
         - Send raw model outputs (feature importances, today's picks, edges) to NVIDIA NIM or OpenRouter LLM
         - LLM generates plain-English interpretation of:
           1. Why the model likes certain picks (which features drove the prediction)
           2. Risk factors and confidence assessment
           3. Market context (line movement, sharp book signals)
         - Display in a "AI Analysis" card below the raw model outputs
         - Two views: "Raw Model Output" (data) + "AI Interpretation" (narrative)
         - Use NVIDIA_API_KEY from .env for LLM calls (same key as code review)
      */}
    </div>
  )
}

const card: React.CSSProperties = {
  background: '#181a20',
  border: '1px solid #2a2d37',
  borderRadius: 14,
  padding: 16,
}

const miniCard: React.CSSProperties = {
  background: '#151821',
  border: '1px solid #2a2d37',
  borderRadius: 12,
  padding: 14,
}

const offerCard: React.CSSProperties = {
  border: '1px solid #333642',
  borderRadius: 10,
  padding: 10,
}

const subtleText: React.CSSProperties = {
  color: '#8b8f9a',
  fontSize: 12,
}

const cardStatRow: React.CSSProperties = {
  display: 'flex',
  justifyContent: 'space-between',
  gap: 8,
  fontSize: 12,
  marginTop: 6,
}

const select: React.CSSProperties = {
  background: '#252830',
  border: '1px solid #333642',
  borderRadius: 8,
  color: '#f8fafc',
  padding: '8px 10px',
  fontFamily: 'inherit',
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

const thBtn: React.CSSProperties = {
  ...th,
  cursor: 'pointer',
}

const td: React.CSSProperties = {
  color: '#e2e8f0',
  padding: '10px 12px',
  borderBottom: '1px solid #2a2d37',
  fontVariantNumeric: 'tabular-nums',
}

const tfootCell: React.CSSProperties = {
  ...td,
  fontWeight: 700,
  background: '#151821',
}
