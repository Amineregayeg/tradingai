import { usePositionsStore } from '@/stores/positionsStore'
import { usePrices } from '@/hooks/usePrices'
import { formatPrice, formatPnL } from '@/utils/format'
import type { Position } from '@/types/api'

// ─── Individual position row ───────────────────────────────────────────────────

function PositionRow({ position }: { position: Position }) {
  const { bid, ask } = usePrices(position.pair)

  const livePrice =
    position.direction === 'LONG'
      ? (bid ?? position.current_price)
      : (ask ?? position.current_price)

  const currentPrice = livePrice ?? position.current_price ?? position.entry_price
  const decimals = 2 // crypto (USD)
  const isLong = position.direction === 'LONG'

  // Crypto PnL = units × price move (USD). Prefer a live recompute; fall back to
  // the server's unrealized_pnl. (No forex pip multipliers.)
  let unrealizedPnl = position.unrealized_pnl ?? 0
  let pips = 0 // repurposed: price-point move in USD
  if (livePrice && position.entry_price) {
    const diff = isLong ? livePrice - position.entry_price : position.entry_price - livePrice
    pips = Math.round(diff)
    unrealizedPnl = diff * position.lot_size
  }
  const pnlPositive = unrealizedPnl >= 0

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '90px 58px 54px 90px 90px 68px 80px 56px',
        padding: '6px 16px',
        gap: 6,
        alignItems: 'center',
        borderBottom: '1px solid #1e2035',
      }}
    >
      {/* Pair */}
      <span
        style={{
          fontSize: 12,
          fontWeight: 600,
          color: '#e8e8ef',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {position.pair}
      </span>

      {/* Direction pill */}
      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          padding: '2px 6px',
          borderRadius: 4,
          textAlign: 'center',
          background: isLong ? 'rgba(0,214,143,0.12)' : 'rgba(255,59,92,0.12)',
          color: isLong ? '#00d68f' : '#ff3b5c',
          border: `1px solid ${isLong ? 'rgba(0,214,143,0.3)' : 'rgba(255,59,92,0.3)'}`,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
        }}
      >
        {position.direction}
      </span>

      {/* Size */}
      <span
        style={{
          fontSize: 11,
          fontFamily: 'var(--font-mono)',
          color: '#8888a0',
        }}
      >
        {Number(position.lot_size).toFixed(2)}
      </span>

      {/* Entry */}
      <span
        style={{
          fontSize: 11,
          fontFamily: 'var(--font-mono)',
          color: '#8888a0',
        }}
      >
        {formatPrice(Number(position.entry_price), decimals)}
      </span>

      {/* Current */}
      <span
        style={{
          fontSize: 11,
          fontFamily: 'var(--font-mono)',
          color: '#e8e8ef',
        }}
      >
        {formatPrice(Number(currentPrice), decimals)}
      </span>

      {/* Pips */}
      <span
        style={{
          fontSize: 11,
          fontFamily: 'var(--font-mono)',
          color: pnlPositive ? '#00d68f' : '#ff3b5c',
        }}
      >
        {pips >= 0 ? '+' : ''}${Math.abs(pips).toLocaleString()}
      </span>

      {/* P&L */}
      <span
        style={{
          fontSize: 12,
          fontWeight: 700,
          fontFamily: 'var(--font-mono)',
          color: pnlPositive ? '#00d68f' : '#ff3b5c',
        }}
      >
        {formatPnL(unrealizedPnl)}
      </span>

      {/* Close button */}
      <button
        style={{
          padding: '3px 10px',
          border: '1px solid #252540',
          borderRadius: 5,
          background: 'transparent',
          color: '#8888a0',
          fontSize: 11,
          cursor: 'pointer',
          transition: 'all 100ms ease',
        }}
        onMouseEnter={(e) => {
          ;(e.currentTarget as HTMLButtonElement).style.borderColor = '#ff3b5c44'
          ;(e.currentTarget as HTMLButtonElement).style.color = '#ff3b5c'
        }}
        onMouseLeave={(e) => {
          ;(e.currentTarget as HTMLButtonElement).style.borderColor = '#252540'
          ;(e.currentTarget as HTMLButtonElement).style.color = '#8888a0'
        }}
      >
        Close
      </button>
    </div>
  )
}

// ─── Main PositionsPanel ───────────────────────────────────────────────────────

export function PositionsPanel() {
  const positions = usePositionsStore((s) => s.positions)
  const totalPnl = positions.reduce(
    (sum, p) => sum + (Number(p.unrealized_pnl) || 0),
    0
  )

  if (positions.length === 0) {
    return (
      <div
        style={{
          padding: '12px 16px',
          borderTop: '1px solid #1e2035',
          background: '#0d0d14',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: '0.1em',
            color: '#55556a',
            marginBottom: 6,
            textTransform: 'uppercase',
          }}
        >
          Open Positions
        </div>
        <p style={{ fontSize: 12, color: '#55556a' }}>
          No open positions. Connect a broker to start trading.
        </p>
      </div>
    )
  }

  return (
    <div
      style={{
        borderTop: '1px solid #1e2035',
        background: '#0d0d14',
        flexShrink: 0,
      }}
    >
      {/* Panel header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '9px 16px 6px',
          borderBottom: '1px solid #1e2035',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span
            style={{
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: '0.1em',
              color: '#55556a',
              textTransform: 'uppercase',
            }}
          >
            Open Positions
          </span>
          <span
            style={{
              fontSize: 10,
              fontWeight: 700,
              padding: '1px 7px',
              borderRadius: 10,
              background: '#1a1a26',
              color: '#8888a0',
            }}
          >
            {positions.length} active
          </span>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 11, color: '#55556a' }}>Total PnL:</span>
          <span
            style={{
              fontSize: 13,
              fontWeight: 700,
              fontFamily: 'var(--font-mono)',
              color: totalPnl >= 0 ? '#00d68f' : '#ff3b5c',
            }}
          >
            {formatPnL(totalPnl)}
          </span>
        </div>
      </div>

      {/* Column headers */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '90px 58px 54px 90px 90px 68px 80px 56px',
          padding: '4px 16px',
          gap: 6,
        }}
      >
        {['Pair', '', 'Size', 'Entry', 'Current', 'Move', 'P&L', ''].map((h, i) => (
          <span
            key={i}
            style={{
              fontSize: 9,
              fontWeight: 700,
              letterSpacing: '0.08em',
              color: '#55556a',
              textTransform: 'uppercase',
            }}
          >
            {h}
          </span>
        ))}
      </div>

      {/* Position rows */}
      <div style={{ overflowX: 'auto' }}>
        {positions.map((p) => (
          <PositionRow key={p.id} position={p} />
        ))}
      </div>
    </div>
  )
}
