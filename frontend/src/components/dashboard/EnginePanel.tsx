import { useEffect, useState } from 'react'
import { wsService } from '@/services/ws'

interface EngineStatus {
  running: boolean
  paused: boolean
  mode: string
  symbols: string[]
  equity: number
  balance: number
  total_pnl: number
  total_pnl_pct: number
  win_rate: number
  closed_trades: number
  wins: number
  open_positions: number
  risk_pct: number
  entry_tf: string
}

const money = (n: number) => '$' + Math.round(n).toLocaleString()

function Stat({ k, v, c }: { k: string; v: string; c?: string }) {
  return (
    <div>
      <div style={{ fontSize: 9, color: '#55556a', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{k}</div>
      <div style={{ fontSize: 15, fontWeight: 700, color: c || '#e8e8ef', fontFamily: 'var(--font-mono)', marginTop: 2 }}>{v}</div>
    </div>
  )
}

export function EnginePanel() {
  const [s, setS] = useState<EngineStatus | null>(null)

  const load = () => fetch('/api/engine/status').then((r) => r.json()).then(setS).catch(() => {})

  useEffect(() => {
    load()
    const t = setInterval(load, 8000)
    return () => clearInterval(t)
  }, [])

  // live equity from the loop's account broadcast
  useEffect(() => {
    const unsub = wsService.on<{ equity: number; balance: number; open_trade_count: number; unrealized_pl: number }>(
      'positions', 'account',
      (d) => setS((p) => (p ? { ...p, equity: d.equity, balance: d.balance, open_positions: d.open_trade_count } : p)),
    )
    return () => unsub()
  }, [])

  const toggle = () =>
    fetch('/api/engine/' + (s?.paused ? 'resume' : 'pause'), { method: 'POST' })
      .then((r) => r.json()).then(setS).catch(() => {})

  if (!s) return <div style={{ padding: 14, color: '#55556a', fontSize: 11 }}>Loading engine…</div>

  const pnlPos = (s.total_pnl ?? 0) >= 0
  const live = s.running && !s.paused

  return (
    <div style={{ padding: '12px 14px', borderBottom: '1px solid #1e2035', flexShrink: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 11 }}>
        <span
          className={live ? 'pulse-dot' : ''}
          style={{
            width: 8, height: 8, borderRadius: '50%',
            background: s.paused ? '#f59e0b' : live ? '#00d68f' : '#55556a',
            boxShadow: `0 0 8px ${s.paused ? '#f59e0b' : live ? '#00d68f' : 'transparent'}`,
          }}
        />
        <span style={{ fontSize: 12, fontWeight: 700, color: '#e8e8ef', letterSpacing: '0.02em' }}>LIVE ENGINE</span>
        <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: 'rgba(0,214,143,0.12)', color: '#00d68f' }}>
          {s.mode}
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 10, color: '#55556a' }}>{s.symbols.join(' · ')}</span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '11px 8px', marginBottom: 11 }}>
        <Stat k="Equity" v={money(s.equity)} />
        <Stat k="P&L" v={(pnlPos ? '+' : '') + money(s.total_pnl)} c={pnlPos ? '#00d68f' : '#ff3b5c'} />
        <Stat k="Return" v={`${s.total_pnl_pct >= 0 ? '+' : ''}${s.total_pnl_pct}%`} c={pnlPos ? '#00d68f' : '#ff3b5c'} />
        <Stat k="Win rate" v={s.closed_trades ? `${s.win_rate}%` : '—'} c="#e3b341" />
        <Stat
          k="Wins / Losses"
          v={`${s.wins}W · ${s.losses}L`}
          c={s.wins >= s.losses ? '#00d68f' : '#ff3b5c'}
        />
        <Stat k="Open" v={String(s.open_positions)} />
      </div>

      <button
        onClick={toggle}
        style={{
          width: '100%', padding: '7px 0', borderRadius: 6,
          border: `1px solid ${s.paused ? '#1d572f' : '#5c3d00'}`,
          background: s.paused ? 'rgba(0,214,143,0.10)' : 'rgba(245,158,11,0.10)',
          color: s.paused ? '#00d68f' : '#f59e0b', fontSize: 12, fontWeight: 600, cursor: 'pointer',
        }}
      >
        {s.paused ? '▶ Resume engine' : '⏸ Pause engine'}
      </button>
    </div>
  )
}
