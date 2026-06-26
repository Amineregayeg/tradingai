import { useState, useEffect } from 'react'
import { api } from '@/services/api'
import type { Trade } from '@/types/api'
import { formatDate } from '@/utils/format'

function formatPnL(v: number) {
  const abs = Math.abs(v).toFixed(2)
  return v >= 0 ? `+$${abs}` : `-$${abs}`
}
function formatR(r: number) {
  return `${r >= 0 ? '+' : ''}${r.toFixed(2)}R`
}

function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{ background: '#12121a', border: '1px solid #1e2035', borderRadius: 10, padding: '14px 18px', flex: 1, minWidth: 120 }}>
      <div style={{ fontSize: 10, color: '#55556a', fontWeight: 700, letterSpacing: '0.06em', marginBottom: 8 }}>{label.toUpperCase()}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: color ?? '#e8e8ef', fontFamily: 'var(--font-mono)' }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: '#55556a', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

// Build ISO week label: "May 12–18"
function weekLabel(from: Date, to: Date) {
  const fmt = (d: Date) => d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  return `${fmt(from)} – ${fmt(to)}`
}

function getWeekBounds(offset = 0) {
  const now = new Date()
  const day = now.getDay() // 0=Sun
  const monday = new Date(now)
  monday.setDate(now.getDate() - ((day + 6) % 7) + offset * 7)
  monday.setHours(0, 0, 0, 0)
  const sunday = new Date(monday)
  sunday.setDate(monday.getDate() + 6)
  sunday.setHours(23, 59, 59, 999)
  return { from: monday, to: sunday }
}

export default function WeeklyReviewPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [weekOffset, setWeekOffset] = useState(0) // 0 = current week, -1 = last week

  const { from, to } = getWeekBounds(weekOffset)

  useEffect(() => {
    setIsLoading(true)
    api.trades.list({
      from: from.toISOString().split('T')[0],
      to: to.toISOString().split('T')[0],
      per_page: 200,
    })
      .then((r) => setTrades(Array.isArray(r) ? r : []))
      .catch(() => setTrades([]))
      .finally(() => setIsLoading(false))
  }, [weekOffset]) // eslint-disable-line react-hooks/exhaustive-deps

  const closed = trades.filter((t) => t.outcome !== 'OPEN')
  const wins = closed.filter((t) => t.outcome === 'WIN').length
  const losses = closed.filter((t) => t.outcome === 'LOSS').length
  const bes = closed.filter((t) => t.outcome === 'BE').length
  const winRate = closed.length > 0 ? (wins / closed.length) * 100 : 0
  const avgR = closed.length > 0 ? closed.reduce((s, t) => s + (t.r_multiple ? Number(t.r_multiple) : 0), 0) / closed.length : 0
  const netPnl = closed.reduce((s, t) => s + (t.pnl_dollars ? Number(t.pnl_dollars) : 0), 0)

  // Best and worst trade
  const sortedByR = [...closed].sort((a, b) => Number(b.r_multiple ?? 0) - Number(a.r_multiple ?? 0))
  const best = sortedByR[0]
  const worst = sortedByR[sortedByR.length - 1]

  // Per-pair breakdown
  const pairMap: Record<string, { trades: number; wins: number; pnl: number }> = {}
  closed.forEach((t) => {
    const p = pairMap[t.pair] ?? { trades: 0, wins: 0, pnl: 0 }
    p.trades++
    if (t.outcome === 'WIN') p.wins++
    p.pnl += t.pnl_dollars ? Number(t.pnl_dollars) : 0
    pairMap[t.pair] = p
  })
  const pairRows = Object.entries(pairMap).sort((a, b) => b[1].trades - a[1].trades)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: '#0a0a0f' }}>
      {/* Header */}
      <div style={{ padding: '16px 24px 12px', borderBottom: '1px solid #1e2035', background: '#0d0d14', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h1 style={{ fontSize: 18, fontWeight: 700, color: '#e8e8ef', marginBottom: 2 }}>Weekly Review</h1>
            <span style={{ fontSize: 12, color: '#55556a' }}>{weekLabel(from, to)}</span>
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button onClick={() => setWeekOffset((w) => w - 1)} style={{ padding: '6px 14px', border: '1px solid #252540', borderRadius: 7, background: 'transparent', color: '#8888a0', fontSize: 12, cursor: 'pointer' }}>← Prev</button>
            {weekOffset < 0 && <button onClick={() => setWeekOffset((w) => w + 1)} style={{ padding: '6px 14px', border: '1px solid #252540', borderRadius: 7, background: 'transparent', color: '#8888a0', fontSize: 12, cursor: 'pointer' }}>Next →</button>}
          </div>
        </div>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
        {isLoading ? (
          <div style={{ textAlign: 'center', color: '#55556a', padding: 40 }}>Loading…</div>
        ) : trades.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '60px 24px' }}>
            <div style={{ fontSize: 32, marginBottom: 16 }}>📊</div>
            <div style={{ fontSize: 15, fontWeight: 600, color: '#e8e8ef', marginBottom: 8 }}>No trades this week</div>
            <div style={{ fontSize: 12, color: '#55556a' }}>Connect a broker to start logging trades automatically.</div>
          </div>
        ) : (
          <>
            {/* Stats row */}
            <div style={{ display: 'flex', gap: 12, marginBottom: 24, flexWrap: 'wrap' }}>
              <StatCard label="Trades" value={String(closed.length)} sub={`${wins}W / ${losses}L / ${bes}BE`} />
              <StatCard label="Win Rate" value={closed.length > 0 ? `${winRate.toFixed(1)}%` : '—'} color={winRate >= 55 ? '#00d68f' : winRate >= 40 ? '#f59e0b' : '#ff3b5c'} />
              <StatCard label="Avg R" value={closed.length > 0 ? formatR(avgR) : '—'} color={avgR > 0 ? '#00d68f' : avgR < 0 ? '#ff3b5c' : undefined} />
              <StatCard label="Net PnL" value={closed.length > 0 ? formatPnL(netPnl) : '—'} color={netPnl > 0 ? '#00d68f' : netPnl < 0 ? '#ff3b5c' : undefined} />
            </div>

            {/* Best / worst */}
            {(best || worst) && (
              <div style={{ display: 'flex', gap: 12, marginBottom: 24 }}>
                {best && (
                  <div style={{ flex: 1, background: 'rgba(0,214,143,0.04)', border: '1px solid rgba(0,214,143,0.2)', borderRadius: 10, padding: '14px 18px' }}>
                    <div style={{ fontSize: 10, color: '#00d68f', fontWeight: 700, letterSpacing: '0.06em', marginBottom: 8 }}>BEST TRADE</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: '#e8e8ef', marginBottom: 4 }}>{best.pair}</div>
                    <div style={{ fontSize: 12, color: '#00d68f' }}>{best.r_multiple ? formatR(Number(best.r_multiple)) : '—'} {best.pnl_dollars ? `· ${formatPnL(Number(best.pnl_dollars))}` : ''}</div>
                    <div style={{ fontSize: 11, color: '#55556a', marginTop: 4 }}>{formatDate(best.entry_time)}</div>
                  </div>
                )}
                {worst && worst !== best && (
                  <div style={{ flex: 1, background: 'rgba(255,59,92,0.04)', border: '1px solid rgba(255,59,92,0.2)', borderRadius: 10, padding: '14px 18px' }}>
                    <div style={{ fontSize: 10, color: '#ff3b5c', fontWeight: 700, letterSpacing: '0.06em', marginBottom: 8 }}>WORST TRADE</div>
                    <div style={{ fontSize: 14, fontWeight: 700, color: '#e8e8ef', marginBottom: 4 }}>{worst.pair}</div>
                    <div style={{ fontSize: 12, color: '#ff3b5c' }}>{worst.r_multiple ? formatR(Number(worst.r_multiple)) : '—'} {worst.pnl_dollars ? `· ${formatPnL(Number(worst.pnl_dollars))}` : ''}</div>
                    <div style={{ fontSize: 11, color: '#55556a', marginTop: 4 }}>{formatDate(worst.entry_time)}</div>
                  </div>
                )}
              </div>
            )}

            {/* Per-pair table */}
            {pairRows.length > 0 && (
              <div style={{ background: '#12121a', border: '1px solid #1e2035', borderRadius: 10, overflow: 'hidden' }}>
                <div style={{ padding: '12px 18px', borderBottom: '1px solid #1e2035' }}>
                  <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', color: '#55556a' }}>PERFORMANCE BY PAIR</span>
                </div>
                {pairRows.map(([pair, data]) => (
                  <div key={pair} style={{ display: 'flex', alignItems: 'center', padding: '11px 18px', borderBottom: '1px solid #13131e' }}>
                    <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: '#e8e8ef' }}>{pair}</span>
                    <span style={{ fontSize: 11, color: '#55556a', minWidth: 70 }}>{data.trades} trades</span>
                    <span style={{ fontSize: 11, color: '#8888a0', minWidth: 60 }}>{data.trades > 0 ? `${Math.round((data.wins / data.trades) * 100)}% WR` : '—'}</span>
                    <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', fontWeight: 700, color: data.pnl > 0 ? '#00d68f' : data.pnl < 0 ? '#ff3b5c' : '#55556a', minWidth: 80, textAlign: 'right' }}>
                      {data.pnl !== 0 ? formatPnL(data.pnl) : '—'}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
