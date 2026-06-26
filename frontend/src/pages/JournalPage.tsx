import { useState, useEffect } from 'react'
import { api } from '@/services/api'
import type { Trade, Outcome } from '@/types/api'
import { formatPrice, formatDate } from '@/utils/format'

interface JournalFilters {
  pair: string
  outcome: string
  from: string
  to: string
}

function formatPnL(value: number): string {
  const abs = Math.abs(value).toFixed(2)
  return value >= 0 ? `+$${abs}` : `-$${abs}`
}

function formatR(r: number): string {
  return `${r >= 0 ? '+' : ''}${r.toFixed(2)}R`
}

// Stat card component
function StatCard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }) {
  return (
    <div style={{
      background: '#12121a', border: '1px solid #1e2035', borderRadius: 10,
      padding: '14px 18px', flex: 1,
    }}>
      <div style={{ fontSize: 11, color: '#55556a', fontWeight: 600, letterSpacing: '0.05em', marginBottom: 8 }}>
        {label.toUpperCase()}
      </div>
      <div style={{ fontSize: 22, fontWeight: 700, color: color ?? '#e8e8ef', fontFamily: 'var(--font-mono)', fontVariantNumeric: 'normal', fontVariantEmoji: 'text' }}>
        {value}
      </div>
      {sub && <div style={{ fontSize: 11, color: '#55556a', marginTop: 4 }}>{sub}</div>}
    </div>
  )
}

export default function JournalPage() {
  const [trades, setTrades] = useState<Trade[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [filters, setFilters] = useState<JournalFilters>({ pair: '', outcome: '', from: '', to: '' })
  const [selectedTrade, setSelectedTrade] = useState<Trade | null>(null)

  useEffect(() => {
    setIsLoading(true)
    api.trades.list({
      pair: filters.pair || undefined,
      outcome: (filters.outcome as Outcome) || undefined,
      from: filters.from || undefined,
      to: filters.to || undefined,
      per_page: 100,
    })
      .then((result) => setTrades(Array.isArray(result) ? result : []))
      .catch(() => setTrades([]))
      .finally(() => setIsLoading(false))
  }, [filters])

  const safeTrades = Array.isArray(trades) ? trades : []
  const wins = safeTrades.filter((t) => t.outcome === 'WIN').length
  const losses = safeTrades.filter((t) => t.outcome === 'LOSS').length
  const closed = safeTrades.filter((t) => t.outcome !== 'OPEN')
  const winRate = closed.length > 0 ? (wins / closed.length) * 100 : 0
  const avgR = closed.length > 0
    ? closed.reduce((s, t) => s + (t.r_multiple ? Number(t.r_multiple) : 0), 0) / closed.length
    : 0
  const netPnl = closed.reduce((s, t) => s + (t.pnl_dollars ? Number(t.pnl_dollars) : 0), 0)

  const hasFilters = filters.pair || filters.outcome || filters.from || filters.to

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: '#0a0a0f' }}>
      {/* Page header */}
      <div style={{
        padding: '16px 24px 12px', borderBottom: '1px solid #1e2035',
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexShrink: 0,
        background: '#0d0d14',
      }}>
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 700, color: '#e8e8ef', marginBottom: 2 }}>Trade Journal</h1>
          <span style={{ fontSize: 12, color: '#55556a' }}>{safeTrades.length} trades</span>
        </div>
        <button
          onClick={() => {
            api.trades.exportCsv({ from: filters.from || undefined, to: filters.to || undefined })
              .then((r) => r.blob())
              .then((b) => {
                const url = URL.createObjectURL(b)
                const a = document.createElement('a')
                a.href = url
                a.download = 'trades.csv'
                a.click()
                URL.revokeObjectURL(url)
              })
              .catch(() => {})
          }}
          style={{
            display: 'flex', alignItems: 'center', gap: 6, padding: '7px 14px',
            border: '1px solid #252540', borderRadius: 7, background: 'transparent',
            color: '#8888a0', fontSize: 12, cursor: 'pointer',
          }}
        >
          ↓ Export CSV
        </button>
      </div>

      {/* Stat cards */}
      <div style={{
        display: 'flex', gap: 12, padding: '14px 24px', flexShrink: 0,
        borderBottom: '1px solid #1e2035',
      }}>
        <StatCard label="Total Trades" value={String(safeTrades.length)} sub={`${wins}W / ${losses}L`} />
        <StatCard
          label="Win Rate"
          value={closed.length > 0 ? `${winRate.toFixed(1)}%` : '—'}
          sub={`${wins} wins`}
          color={winRate >= 55 ? '#00d68f' : winRate >= 40 ? '#f59e0b' : winRate > 0 ? '#ff3b5c' : undefined}
        />
        <StatCard
          label="Avg R"
          value={closed.length > 0 ? formatR(avgR) : '—'}
          sub={`${closed.length} closed trades`}
          color={avgR > 0 ? '#00d68f' : avgR < 0 ? '#ff3b5c' : undefined}
        />
        <StatCard
          label="Net PnL"
          value={closed.length > 0 ? formatPnL(netPnl) : '—'}
          sub="realized"
          color={netPnl > 0 ? '#00d68f' : netPnl < 0 ? '#ff3b5c' : undefined}
        />
      </div>

      {/* Filters */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '10px 24px',
        borderBottom: '1px solid #1e2035', flexShrink: 0, background: '#0d0d14',
      }}>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span style={{ fontSize: 10, color: '#55556a', fontWeight: 600, letterSpacing: '0.05em' }}>PAIR</span>
          <input
            type="text"
            placeholder="EUR/USD"
            value={filters.pair}
            onChange={(e) => setFilters((f) => ({ ...f, pair: e.target.value }))}
            style={{ width: 100 }}
          />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span style={{ fontSize: 10, color: '#55556a', fontWeight: 600, letterSpacing: '0.05em' }}>OUTCOME</span>
          <select value={filters.outcome} onChange={(e) => setFilters((f) => ({ ...f, outcome: e.target.value }))}>
            <option value="">All Outcomes</option>
            <option value="WIN">WIN</option>
            <option value="LOSS">LOSS</option>
            <option value="BE">BE</option>
            <option value="OPEN">OPEN</option>
          </select>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span style={{ fontSize: 10, color: '#55556a', fontWeight: 600, letterSpacing: '0.05em' }}>FROM</span>
          <input type="date" value={filters.from} onChange={(e) => setFilters((f) => ({ ...f, from: e.target.value }))} />
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
          <span style={{ fontSize: 10, color: '#55556a', fontWeight: 600, letterSpacing: '0.05em' }}>TO</span>
          <input type="date" value={filters.to} onChange={(e) => setFilters((f) => ({ ...f, to: e.target.value }))} />
        </div>

        {hasFilters && (
          <button
            onClick={() => setFilters({ pair: '', outcome: '', from: '', to: '' })}
            style={{
              marginTop: 14, padding: '5px 12px', border: '1px solid #252540', borderRadius: 6,
              background: 'transparent', color: '#8888a0', fontSize: 12, cursor: 'pointer',
            }}
          >
            Clear
          </button>
        )}
      </div>

      {/* Table */}
      <div style={{ flex: 1, overflow: 'auto' }}>
        {/* Column headers */}
        <div style={{
          display: 'grid',
          gridTemplateColumns: '40px 110px 80px 60px 90px 90px 60px 80px 90px 110px 80px',
          padding: '8px 24px', borderBottom: '1px solid #1e2035', position: 'sticky', top: 0,
          background: '#0d0d14', gap: 8,
        }}>
          {['#', 'Opened', 'Pair', 'Dir', 'Entry', 'Exit', 'R', 'PnL', 'Session', 'Setup Tag', 'Outcome'].map((h) => (
            <span key={h} style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.08em', color: '#55556a', textTransform: 'uppercase' }}>
              {h}
            </span>
          ))}
        </div>

        {isLoading ? (
          <div style={{ padding: '40px 24px', textAlign: 'center', color: '#55556a' }}>Loading...</div>
        ) : safeTrades.length === 0 ? (
          <div style={{ padding: '40px 24px', textAlign: 'center' }}>
            <div style={{ fontSize: 13, color: '#55556a', marginBottom: 6 }}>No trades found</div>
            <div style={{ fontSize: 12, color: '#3a3a50' }}>Adjust your filters or connect a broker to start logging trades.</div>
          </div>
        ) : safeTrades.map((trade, i) => {
          const pnl = trade.pnl_dollars ? Number(trade.pnl_dollars) : null
          const r = trade.r_multiple ? Number(trade.r_multiple) : null
          const isWin = trade.outcome === 'WIN'
          const isLoss = trade.outcome === 'LOSS'
          const isLong = trade.direction === 'LONG'
          const isSelected = selectedTrade?.id === trade.id

          return (
            <div key={trade.id}>
            <div
              onClick={() => setSelectedTrade(isSelected ? null : trade)}
              style={{
                display: 'grid',
                gridTemplateColumns: '40px 110px 80px 60px 90px 90px 60px 80px 90px 110px 80px',
                padding: '9px 24px', gap: 8, alignItems: 'center',
                borderBottom: '1px solid #13131e',
                cursor: 'pointer',
                background: isSelected ? '#16162a' : 'transparent',
                transition: 'background 100ms',
              }}
              onMouseEnter={(e) => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = '#12121a' }}
              onMouseLeave={(e) => { if (!isSelected) (e.currentTarget as HTMLDivElement).style.background = 'transparent' }}
            >
              <span style={{ fontSize: 11, color: '#3a3a50', fontFamily: 'var(--font-mono)' }}>{i + 1}</span>
              <span style={{ fontSize: 11, color: '#8888a0', fontFamily: 'var(--font-mono)' }}>
                {formatDate(trade.entry_time)}
              </span>
              <span style={{ fontSize: 12, fontWeight: 600, color: '#e8e8ef' }}>{trade.pair}</span>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, textAlign: 'center',
                background: isLong ? '#00d68f22' : '#ff3b5c22',
                color: isLong ? '#00d68f' : '#ff3b5c',
                border: `1px solid ${isLong ? '#00d68f33' : '#ff3b5c33'}`,
                display: 'inline-block',
              }}>{trade.direction}</span>
              <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: '#8888a0' }}>
                {formatPrice(Number(trade.entry_price))}
              </span>
              <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: '#8888a0' }}>
                {trade.exit_price ? formatPrice(Number(trade.exit_price)) : '—'}
              </span>
              <span style={{
                fontSize: 11, fontFamily: 'var(--font-mono)', fontWeight: 600,
                color: r === null ? '#55556a' : r > 0 ? '#00d68f' : '#ff3b5c',
              }}>
                {r !== null ? formatR(r) : '—'}
              </span>
              <span style={{
                fontSize: 12, fontFamily: 'var(--font-mono)', fontWeight: 700,
                color: pnl === null ? '#55556a' : pnl > 0 ? '#00d68f' : '#ff3b5c',
              }}>
                {pnl !== null ? formatPnL(pnl) : '—'}
              </span>
              <span style={{ fontSize: 11, color: '#55556a', textTransform: 'capitalize' }}>
                {trade.session ?? '—'}
              </span>
              <span style={{
                fontSize: 10, color: '#8888a0',
                background: trade.setup_tag ? '#1e2035' : 'transparent',
                padding: trade.setup_tag ? '2px 7px' : 0,
                borderRadius: 4, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
              }}>
                {trade.setup_tag ?? '—'}
              </span>
              <span style={{
                fontSize: 10, fontWeight: 700, padding: '2px 8px', borderRadius: 4, textAlign: 'center',
                background: isWin ? '#00d68f22' : isLoss ? '#ff3b5c22' : '#1e2035',
                color: isWin ? '#00d68f' : isLoss ? '#ff3b5c' : '#8888a0',
                display: 'inline-block',
              }}>{trade.outcome}</span>
            </div>
            {isSelected && (
              <div style={{
                background: '#0d0d14',
                borderBottom: '1px solid #1e2035',
                padding: '18px 24px',
                display: 'grid',
                gridTemplateColumns: 'repeat(4, 1fr)',
                gap: 18,
              }}>
                {[
                  { label: 'Entry', value: formatPrice(Number(trade.entry_price)) },
                  { label: 'Exit', value: trade.exit_price ? formatPrice(Number(trade.exit_price)) : '—' },
                  { label: 'Stop Loss', value: trade.sl ? formatPrice(Number(trade.sl)) : '—', color: '#ff3b5c' },
                  { label: 'Take Profit', value: trade.tp ? formatPrice(Number(trade.tp)) : '—', color: '#00d68f' },
                  { label: 'Lot Size', value: Number(trade.lot_size).toFixed(2) },
                  { label: 'R Multiple', value: r !== null ? formatR(r) : '—', color: r === null ? undefined : r > 0 ? '#00d68f' : '#ff3b5c' },
                  { label: 'PnL', value: pnl !== null ? formatPnL(pnl) : '—', color: pnl === null ? undefined : pnl > 0 ? '#00d68f' : '#ff3b5c' },
                  { label: 'Session', value: trade.session ?? '—' },
                  { label: 'Setup Tag', value: trade.setup_tag ?? '—' },
                  { label: 'Broker', value: trade.broker ?? '—' },
                  { label: 'Opened', value: formatDate(trade.entry_time) },
                  { label: 'Closed', value: trade.exit_time ? formatDate(trade.exit_time) : '—' },
                ].map(({ label, value, color }) => (
                  <div key={label}>
                    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.08em', color: '#55556a', marginBottom: 4, textTransform: 'uppercase' }}>{label}</div>
                    <div style={{ fontSize: 13, fontFamily: 'var(--font-mono)', color: color ?? '#e8e8ef' }}>{value}</div>
                  </div>
                ))}
                {trade.notes && (
                  <div style={{ gridColumn: '1 / -1', marginTop: 4 }}>
                    <div style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.08em', color: '#55556a', marginBottom: 4, textTransform: 'uppercase' }}>Notes</div>
                    <div style={{ fontSize: 12, color: '#8888a0', lineHeight: 1.5 }}>{trade.notes}</div>
                  </div>
                )}
                <div style={{ gridColumn: '1 / -1', marginTop: 6, fontSize: 11, color: '#3a3a50', fontStyle: 'italic' }}>
                  Phase 2 will surface: linked screenshots, AI analysis JSON, the alert that triggered this trade, and the edit-diff history.
                </div>
              </div>
            )}
            </div>
          )
        })}
      </div>
    </div>
  )
}
