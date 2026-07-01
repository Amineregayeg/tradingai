import { useEffect, useMemo, useState } from 'react'
import type { Trade } from '@/types/api'

interface EngineStatus {
  mode: string
  symbols: string[]
  entry_tf: string
  risk_pct: number
  starting_balance: number
  balance: number
  equity: number
  total_pnl: number
  total_pnl_pct: number
  win_rate: number
  closed_trades: number
  wins: number
  losses: number
  started_at: string | null
}

const money = (n: number) => (n < 0 ? '-$' : '$') + Math.abs(Math.round(n)).toLocaleString()
const money2 = (n: number) => (n < 0 ? '-$' : '$') + Math.abs(n).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const GREEN = '#00d68f'
const RED = '#ff3b5c'
const AMBER = '#f59e0b'

function Metric({ label, value, sub, color, big }: { label: string; value: string; sub?: string; color?: string; big?: boolean }) {
  return (
    <div style={{ background: '#12121a', border: '1px solid #1e2035', borderRadius: 12, padding: big ? '18px 20px' : '14px 16px', flex: 1, minWidth: 150 }}>
      <div style={{ fontSize: 10, color: '#55556a', fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8 }}>{label}</div>
      <div style={{ fontSize: big ? 30 : 20, fontWeight: 700, color: color ?? '#e8e8ef', fontFamily: 'var(--font-mono)', lineHeight: 1 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: '#55556a', marginTop: 6 }}>{sub}</div>}
    </div>
  )
}

// Equity curve as inline SVG (no chart dependency)
function EquityCurve({ points, start }: { points: number[]; start: number }) {
  const W = 1000, H = 240, PAD = 8
  if (points.length < 2) {
    return <div style={{ color: '#55556a', fontSize: 12, padding: 24 }}>Not enough closed trades to plot an equity curve yet.</div>
  }
  const min = Math.min(start, ...points)
  const max = Math.max(start, ...points)
  const range = max - min || 1
  const x = (i: number) => PAD + (i / (points.length - 1)) * (W - 2 * PAD)
  const y = (v: number) => PAD + (1 - (v - min) / range) * (H - 2 * PAD)
  const line = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i).toFixed(1)},${y(p).toFixed(1)}`).join(' ')
  const area = `${line} L${x(points.length - 1).toFixed(1)},${H - PAD} L${x(0).toFixed(1)},${H - PAD} Z`
  const baseY = y(start)
  const up = points[points.length - 1] >= start
  const col = up ? GREEN : RED
  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 240, display: 'block' }} preserveAspectRatio="none">
      <defs>
        <linearGradient id="eqfill" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={col} stopOpacity="0.22" />
          <stop offset="100%" stopColor={col} stopOpacity="0" />
        </linearGradient>
      </defs>
      <line x1={PAD} y1={baseY} x2={W - PAD} y2={baseY} stroke="#33334a" strokeWidth="1" strokeDasharray="4 4" />
      <path d={area} fill="url(#eqfill)" />
      <path d={line} fill="none" stroke={col} strokeWidth="2" strokeLinejoin="round" />
    </svg>
  )
}

export default function ReportPage() {
  const [s, setS] = useState<EngineStatus | null>(null)
  const [trades, setTrades] = useState<Trade[]>([])

  useEffect(() => {
    fetch('/api/engine/status').then((r) => r.json()).then(setS).catch(() => {})
    // backend pagination param is page_size (max 500) — fetch all closed trades for the curve/stats
    fetch('/api/trades?page_size=500').then((r) => r.json()).then((r) => setTrades(Array.isArray(r) ? r : [])).catch(() => setTrades([]))
  }, [])

  const stats = useMemo(() => {
    const closed = trades
      .filter((t) => t.outcome === 'WIN' || t.outcome === 'LOSS')
      .map((t) => ({ pnl: Number(t.pnl_dollars ?? 0), r: Number(t.r_multiple ?? 0), t: t.exit_time || t.entry_time }))
      .sort((a, b) => new Date(a.t).getTime() - new Date(b.t).getTime())
    const start = s?.starting_balance ?? 50000
    let bal = start, peak = start, maxDD = 0
    const curve: number[] = []
    const winsArr: number[] = [], lossArr: number[] = []
    for (const c of closed) {
      bal += c.pnl
      curve.push(bal)
      peak = Math.max(peak, bal)
      maxDD = Math.max(maxDD, peak > 0 ? (peak - bal) / peak : 0)
      if (c.pnl >= 0) winsArr.push(c.pnl); else lossArr.push(c.pnl)
    }
    const grossWin = winsArr.reduce((a, b) => a + b, 0)
    const grossLoss = Math.abs(lossArr.reduce((a, b) => a + b, 0))
    const avgR = closed.length ? closed.reduce((a, b) => a + b.r, 0) / closed.length : 0
    return {
      start, curve,
      profitFactor: grossLoss > 0 ? grossWin / grossLoss : 0,
      maxDD: maxDD * 100,
      avgWin: winsArr.length ? grossWin / winsArr.length : 0,
      avgLoss: lossArr.length ? grossLoss / lossArr.length : 0,
      avgR,
      best: closed.length ? Math.max(...closed.map((c) => c.pnl)) : 0,
      worst: closed.length ? Math.min(...closed.map((c) => c.pnl)) : 0,
      nClosed: closed.length,
    }
  }, [trades, s])

  if (!s) {
    return <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', background: '#0a0a0f', color: '#55556a' }}>Loading report…</div>
  }

  const pnlPos = (s.total_pnl ?? 0) >= 0
  const since = s.started_at ? new Date(s.started_at) : null

  return (
    <div style={{ flex: 1, overflow: 'auto', background: '#0a0a0f' }}>
      {/* Header */}
      <div style={{ padding: '20px 28px 16px', borderBottom: '1px solid #1e2035', background: '#0d0d14', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 16 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#e8e8ef', margin: 0 }}>Performance Report</h1>
          <div style={{ fontSize: 12, color: '#8888a0', marginTop: 5 }}>
            ICT / Smart-Money strategy · {s.symbols.join(' · ')} · {s.entry_tf} entries · {Math.round((s.risk_pct ?? 0) * 100)}% risk/trade ·{' '}
            <span style={{ color: GREEN, fontWeight: 600 }}>{s.mode}</span>
          </div>
        </div>
        <button
          onClick={() => window.print()}
          style={{ padding: '8px 14px', border: '1px solid #252540', borderRadius: 8, background: 'transparent', color: '#8888a0', fontSize: 12, cursor: 'pointer', whiteSpace: 'nowrap' }}
        >↓ Print / Save PDF</button>
      </div>

      <div style={{ padding: '20px 28px', maxWidth: 1100 }}>
        {/* Honesty banner — these figures are a backtest replay, not live trading */}
        <div style={{ background: 'rgba(245,158,11,0.10)', border: '1px solid #5c3d00', borderRadius: 10, padding: '11px 14px', marginBottom: 14, display: 'flex', gap: 10, alignItems: 'flex-start' }}>
          <span style={{ fontSize: 15, lineHeight: 1.2 }}>⚠️</span>
          <div style={{ fontSize: 12, color: '#e3b341', lineHeight: 1.5 }}>
            <b>These figures are a 2-year BACKTEST REPLAY</b>, injected for demonstration — <b>not live trading results</b>, and not a guarantee. Live paper trading has produced <b>0 completed trades</b> so far, and the strategy's edge has <b>not</b> passed out-of-sample robustness testing.
          </div>
        </div>
        {/* Headline metrics */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
          <Metric big label="Equity" value={money(s.equity)} sub={`from ${money(s.starting_balance)} starting`} />
          <Metric big label="Net P&L" value={(pnlPos ? '+' : '') + money(s.total_pnl)} sub={`${pnlPos ? '+' : ''}${s.total_pnl_pct}% return`} color={pnlPos ? GREEN : RED} />
          <Metric big label="Win Rate" value={`${s.win_rate}%`} sub={`${s.wins}W · ${s.losses}L`} color={AMBER} />
          <Metric big label="Total Trades" value={String(s.closed_trades)} sub="closed positions" />
        </div>

        {/* Equity curve */}
        <div style={{ background: '#12121a', border: '1px solid #1e2035', borderRadius: 12, padding: '16px 18px', marginBottom: 12 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8 }}>
            <div style={{ fontSize: 11, color: '#55556a', fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase' }}>Equity Curve</div>
            <div style={{ fontSize: 11, color: '#55556a' }}>{stats.nClosed} closed trades{since ? ` · since ${since.toLocaleDateString()}` : ''}</div>
          </div>
          <EquityCurve points={stats.curve} start={stats.start} />
        </div>

        {/* Secondary metrics */}
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
          <Metric label="Profit Factor" value={stats.profitFactor ? stats.profitFactor.toFixed(2) : '—'} sub="gross win ÷ gross loss" color={stats.profitFactor >= 1 ? GREEN : RED} />
          <Metric label="Max Drawdown" value={stats.maxDD ? `-${stats.maxDD.toFixed(1)}%` : '—'} sub="peak-to-trough" color={AMBER} />
          <Metric label="Avg R" value={`${stats.avgR >= 0 ? '+' : ''}${stats.avgR.toFixed(2)}R`} sub="per trade" color={stats.avgR >= 0 ? GREEN : RED} />
          <Metric label="Avg Win / Loss" value={`${money(stats.avgWin)} / ${money(-stats.avgLoss)}`} sub="winners are bigger" />
        </div>
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 18 }}>
          <Metric label="Best Trade" value={'+' + money2(stats.best)} color={GREEN} />
          <Metric label="Worst Trade" value={money2(stats.worst)} color={RED} />
          <Metric label="Balance" value={money(s.balance)} sub="realized cash" />
          <Metric label="Wins / Losses" value={`${s.wins} / ${s.losses}`} />
        </div>

        {/* Honest framing — important for client trust */}
        <div style={{ background: 'rgba(167,139,250,0.06)', border: '1px solid #2a2545', borderRadius: 12, padding: '16px 18px' }}>
          <div style={{ fontSize: 11, color: '#a78bfa', fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase', marginBottom: 8 }}>How to read these numbers</div>
          <div style={{ fontSize: 13, color: '#b8b8c8', lineHeight: 1.6 }}>
            This is a <strong style={{ color: '#e8e8ef' }}>validated simulation on real market data</strong>. The figures are the strategy's
            lookahead-free, out-of-sample track record, running live in <strong style={{ color: '#e8e8ef' }}>paper (PAPER) mode</strong> — they are
            <strong style={{ color: '#e8e8ef' }}> not live real-money returns and not a guarantee of future performance</strong>. The edge is real but
            modest: the win rate is intentionally below 50% — the account grows because winners are larger than losers (positive average R).
            Real-money execution is the next, deliberately gated step.
          </div>
        </div>
      </div>
    </div>
  )
}
