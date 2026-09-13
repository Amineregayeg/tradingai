import { useEffect, useState } from 'react'
import { wsService } from '@/services/ws'
import { authHeaders } from '@/services/api'

interface EngineStatus {
  running: boolean
  paused: boolean
  /**
   * WHY the engine stopped trading, when something other than an operator stopped it.
   *
   * `B413`/`T-0141`: a partial fill we could not size halts the run, and `running` stays `true`
   * while `paused` stays `false` — so before this field the dot below went on pulsing GREEN over
   * an engine that would never take another entry. That is `B179`'s shape: *the flag is off* read
   * as *it works and there was nothing to do*.
   */
  halt_reason?: string | null
  mode: string
  symbols: string[]
  equity: number
  balance: number
  total_pnl: number
  total_pnl_pct: number
  // B431: NULL when the engine could not COUNT, which is not the same as counting zero. A
  // broker without a realized-trade ledger (any real venue adapter) with the database also
  // unreachable leaves these unknown, and the backend now says so instead of sending 0.
  win_rate: number | null
  closed_trades: number | null
  wins: number | null
  losses: number | null
  counts_unavailable?: string[]
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

  const load = () => fetch('/api/engine/status', { headers: authHeaders() }).then((r) => r.json()).then(setS).catch(() => {})

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
    fetch('/api/engine/' + (s?.paused ? 'resume' : 'pause'), { method: 'POST', headers: authHeaders() })
      .then((r) => r.json()).then(setS).catch(() => {})

  if (!s) return <div style={{ padding: 14, color: '#55556a', fontSize: 11 }}>Loading engine…</div>

  const pnlPos = (s.total_pnl ?? 0) >= 0
  // A HALT IS NOT LIVE. Three states, not two: live, paused by an operator, and halted for a
  // reason the engine found itself. Reading only `paused` collapses the third into the first.
  const halted = !!s.halt_reason
  const live = s.running && !s.paused && !halted

  return (
    <div style={{ padding: '12px 14px', borderBottom: '1px solid #1e2035', flexShrink: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 11 }}>
        <span
          className={live ? 'pulse-dot' : ''}
          style={{
            width: 8, height: 8, borderRadius: '50%',
            background: halted ? '#ff3b5c' : s.paused ? '#f59e0b' : live ? '#00d68f' : '#55556a',
            boxShadow: `0 0 8px ${halted ? '#ff3b5c' : s.paused ? '#f59e0b' : live ? '#00d68f' : 'transparent'}`,
          }}
        />
        <span style={{ fontSize: 12, fontWeight: 700, color: '#e8e8ef', letterSpacing: '0.02em' }}>LIVE ENGINE</span>
        <span style={{ fontSize: 9, fontWeight: 700, padding: '2px 7px', borderRadius: 4, background: 'rgba(0,214,143,0.12)', color: '#00d68f' }}>
          {s.mode}
        </span>
        <span style={{ marginLeft: 'auto', fontSize: 10, color: '#55556a' }}>{s.symbols.join(' · ')}</span>
      </div>

      {/* The REASON, not just the state. An unnamed halt is indistinguishable from an operator
          pause, from the order-path gate and from a prop-firm halt — three causes, one flag. */}
      {halted && (
        <div
          role="alert"
          style={{
            marginBottom: 11, padding: '7px 9px', borderRadius: 6,
            border: '1px solid #5c1526', background: 'rgba(255,59,92,0.10)',
            color: '#ff3b5c', fontSize: 11, fontWeight: 600, lineHeight: 1.4,
          }}
        >
          HALTED — {s.halt_reason}
        </div>
      )}

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '11px 8px', marginBottom: 11 }}>
        <Stat k="Equity" v={money(s.equity)} />
        <Stat k="P&L" v={(pnlPos ? '+' : '') + money(s.total_pnl)} c={pnlPos ? '#00d68f' : '#ff3b5c'} />
        <Stat k="Return" v={`${s.total_pnl_pct >= 0 ? '+' : ''}${s.total_pnl_pct}%`} c={pnlPos ? '#00d68f' : '#ff3b5c'} />
        <Stat k="Win rate" v={s.closed_trades ? `${s.win_rate}%` : '—'} c="#e3b341" />
        <Stat
          k="Wins / Losses"
          // `${s.wins}W` on a null renders the literal string "nullW", and `null >= null` is
          // TRUE in JS — so the unknown case would have printed nullW · nullL in the colour that
          // means winning. An em dash is the only honest render of a number nobody has.
          v={s.wins == null || s.losses == null ? '—' : `${s.wins}W · ${s.losses}L`}
          c={s.wins == null || s.losses == null ? '#55556a'
             : s.wins >= s.losses ? '#00d68f' : '#ff3b5c'}
        />
        <Stat k="Open" v={String(s.open_positions)} />
      </div>

      {/* **B431, THIRD ITERATION OF ONE CLASS.** The sequence is worth keeping:
              original    the panel 500'd
              first fix   0, explained by a key that could not name what was missing
              second fix  an em dash, explained by a key that was never RENDERED
          A type declaration is not a consumer. Without this line the operator sees a dash and
          cannot tell a database outage from a broker that keeps no ledger — and it is BOTH, every
          time, because this state is only reachable when the DB read failed AND the broker has no
          realized-trade ledger. Saying so is the whole remedy. */}
      {s.counts_unavailable && s.counts_unavailable.length > 0 && (
        <div style={{ fontSize: 10, color: '#f59e0b', marginTop: -4, marginBottom: 9, lineHeight: 1.4 }}>
          Trade counts unavailable — the database read failed and this broker keeps no realized-trade
          ledger ({s.counts_unavailable.join(', ')}). The dashes above are unknown, not zero.
        </div>
      )}

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
