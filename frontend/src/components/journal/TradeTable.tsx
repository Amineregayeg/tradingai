import { Badge } from '@/components/ui'
import { EmptyState } from '@/components/ui'
import { PnLCell } from '@/components/shared'
import type { Trade } from '@/types/api'
import { formatPrice, formatRMultiple, formatDateTime } from '@/utils/format'

export interface TradeTableProps {
  trades: Trade[]
  isLoading: boolean
  onSelectTrade: (trade: Trade) => void
  selectedTradeId?: string
}

const sessionVariant: Record<string, 'info' | 'success' | 'warning' | 'neutral'> = {
  London: 'info',
  NY: 'success',
  Asian: 'warning',
}

const outcomeVariant: Record<string, 'success' | 'danger' | 'neutral' | 'warning'> = {
  WIN: 'success',
  LOSS: 'danger',
  BE: 'neutral',
  OPEN: 'warning',
}

function DirectionIcon({ direction }: { direction: 'LONG' | 'SHORT' }) {
  if (direction === 'LONG') {
    return (
      <span style={{ color: 'var(--accent-green)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M6 10V2M6 2L2 6M6 2l4 4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
        LONG
      </span>
    )
  }
  return (
    <span style={{ color: 'var(--accent-red)', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
        <path d="M6 2v8M6 10L2 6m4 4 4-4" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      SHORT
    </span>
  )
}

function SkeletonRows() {
  return (
    <>
      {[0, 1, 2].map((i) => (
        <tr key={i}>
          {Array.from({ length: 11 }).map((_, j) => (
            <td key={j} style={{ padding: 'var(--space-3) var(--space-4)' }}>
              <div
                style={{
                  height: 14,
                  borderRadius: 'var(--radius-sm)',
                  background: 'var(--bg-accent)',
                  width: j === 2 ? 60 : j === 10 ? 40 : 80,
                  animation: 'pulse 1.5s ease-in-out infinite',
                }}
              />
            </td>
          ))}
        </tr>
      ))}
    </>
  )
}

const thStyle: React.CSSProperties = {
  padding: 'var(--space-2) var(--space-4)',
  textAlign: 'left',
  fontSize: 'var(--text-xs)',
  fontWeight: 'var(--weight-semibold)',
  color: 'var(--text-muted)',
  textTransform: 'uppercase',
  letterSpacing: '0.05em',
  whiteSpace: 'nowrap',
  borderBottom: '1px solid var(--border)',
  background: 'var(--bg-card)',
  position: 'sticky' as const,
  top: 0,
  zIndex: 1,
}

const tdStyle: React.CSSProperties = {
  padding: 'var(--space-3) var(--space-4)',
  fontSize: 'var(--text-sm)',
  color: 'var(--text-primary)',
  whiteSpace: 'nowrap',
  borderBottom: '1px solid var(--border)',
}

export function TradeTable({
  trades,
  isLoading,
  onSelectTrade,
  selectedTradeId,
}: TradeTableProps) {
  // Sort by entry_time desc
  const sorted = [...trades].sort(
    (a, b) => new Date(b.entry_time).getTime() - new Date(a.entry_time).getTime()
  )

  return (
    <div style={{ flex: 1, overflowY: 'auto', overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr>
            <th style={thStyle}>#</th>
            <th style={thStyle}>Date</th>
            <th style={thStyle}>Pair</th>
            <th style={thStyle}>Direction</th>
            <th style={thStyle}>Entry</th>
            <th style={thStyle}>Exit</th>
            <th style={thStyle}>R</th>
            <th style={thStyle}>PnL</th>
            <th style={thStyle}>Session</th>
            <th style={thStyle}>Setup Tag</th>
            <th style={thStyle}>Outcome</th>
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <SkeletonRows />
          ) : sorted.length === 0 ? (
            <tr>
              <td colSpan={11}>
                <EmptyState
                  title="No trades found"
                  description="Adjust your filters or connect a broker to start logging trades."
                  icon={
                    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                      <rect x="3" y="6" width="18" height="14" rx="2" stroke="currentColor" strokeWidth="1.5" />
                      <path d="M3 10h18" stroke="currentColor" strokeWidth="1.5" />
                      <path d="M8 14h4M8 17h2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                    </svg>
                  }
                />
              </td>
            </tr>
          ) : (
            sorted.map((trade, idx) => {
              const isSelected = trade.id === selectedTradeId
              return (
                <tr
                  key={trade.id}
                  onClick={() => onSelectTrade(trade)}
                  style={{
                    cursor: 'pointer',
                    background: isSelected ? 'var(--bg-accent)' : 'transparent',
                    transition: 'background 0.1s',
                  }}
                  onMouseEnter={(e) => {
                    if (!isSelected) {
                      (e.currentTarget as HTMLTableRowElement).style.background =
                        'var(--bg-card-hover)'
                    }
                  }}
                  onMouseLeave={(e) => {
                    if (!isSelected) {
                      (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'
                    }
                  }}
                >
                  <td style={{ ...tdStyle, color: 'var(--text-muted)' }}>{idx + 1}</td>
                  <td style={tdStyle}>{formatDateTime(trade.entry_time)}</td>
                  <td style={{ ...tdStyle, fontWeight: 'var(--weight-semibold)' }}>{trade.pair}</td>
                  <td style={tdStyle}>
                    <DirectionIcon direction={trade.direction} />
                  </td>
                  <td style={tdStyle}>{formatPrice(trade.entry_price)}</td>
                  <td style={{ ...tdStyle, color: 'var(--text-secondary)' }}>
                    {trade.exit_price !== null ? formatPrice(trade.exit_price) : '—'}
                  </td>
                  <td style={tdStyle}>
                    {trade.r_multiple !== null ? (
                      <span
                        style={{
                          color:
                            trade.r_multiple >= 0
                              ? 'var(--accent-green)'
                              : 'var(--accent-red)',
                          fontWeight: 'var(--weight-medium)',
                        }}
                      >
                        {formatRMultiple(trade.r_multiple)}
                      </span>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>—</span>
                    )}
                  </td>
                  <td style={tdStyle}>
                    <PnLCell value={trade.pnl_dollars} suffix="$" />
                  </td>
                  <td style={tdStyle}>
                    {trade.session ? (
                      <Badge
                        variant={
                          sessionVariant[trade.session] ?? 'neutral'
                        }
                        size="sm"
                      >
                        {trade.session}
                      </Badge>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>—</span>
                    )}
                  </td>
                  <td style={tdStyle}>
                    {trade.setup_tag ? (
                      <span
                        style={{
                          display: 'inline-block',
                          padding: '2px 8px',
                          borderRadius: 'var(--radius-sm)',
                          background: 'var(--bg-accent)',
                          border: '1px solid var(--border)',
                          fontSize: 'var(--text-xs)',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        {trade.setup_tag}
                      </span>
                    ) : (
                      <span style={{ color: 'var(--text-muted)' }}>—</span>
                    )}
                  </td>
                  <td style={tdStyle}>
                    <Badge variant={outcomeVariant[trade.outcome] ?? 'neutral'} size="sm">
                      {trade.outcome}
                    </Badge>
                  </td>
                </tr>
              )
            })
          )}
        </tbody>
      </table>
    </div>
  )
}
