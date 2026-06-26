import type { Trade } from '@/types/api'
import { formatPnL, formatRMultiple } from '@/utils/format'

export interface JournalStatsBarProps {
  trades: Trade[]
}

interface StatCardProps {
  title: string
  value: string
  subtitle?: string
  valueColor?: string
}

function StatCard({ title, value, subtitle, valueColor }: StatCardProps) {
  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-lg)',
        padding: 'var(--space-4)',
        flex: 1,
        minWidth: 0,
      }}
    >
      <p
        style={{
          fontSize: 'var(--text-sm)',
          color: 'var(--text-secondary)',
          marginBottom: 'var(--space-1)',
          fontWeight: 'var(--weight-medium)',
        }}
      >
        {title}
      </p>
      <p
        style={{
          fontSize: 'var(--text-2xl)',
          fontWeight: 'var(--weight-bold)',
          color: valueColor ?? 'var(--text-primary)',
          lineHeight: 1.2,
        }}
      >
        {value}
      </p>
      {subtitle && (
        <p style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)', marginTop: 'var(--space-1)' }}>
          {subtitle}
        </p>
      )}
    </div>
  )
}

export function JournalStatsBar({ trades }: JournalStatsBarProps) {
  const total = trades.length
  const wins = trades.filter((t) => t.outcome === 'WIN').length
  const winRate = total > 0 ? (wins / total) * 100 : 0

  const closedWithR = trades.filter(
    (t) => t.outcome !== 'OPEN' && t.r_multiple !== null
  )
  const avgR =
    closedWithR.length > 0
      ? closedWithR.reduce((sum, t) => sum + (t.r_multiple ?? 0), 0) / closedWithR.length
      : null

  const netPnl = trades.reduce((sum, t) => sum + (t.pnl_dollars ?? 0), 0)

  let winRateColor = 'var(--accent-red)'
  if (winRate >= 55) winRateColor = 'var(--accent-green)'
  else if (winRate >= 45) winRateColor = 'var(--accent-amber)'

  const pnlColor = netPnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'

  return (
    <div
      style={{
        display: 'flex',
        gap: 'var(--space-3)',
        padding: 'var(--space-4)',
        paddingTop: 0,
      }}
    >
      <StatCard
        title="Total Trades"
        value={String(total)}
        subtitle={`${wins}W / ${trades.filter((t) => t.outcome === 'LOSS').length}L`}
      />
      <StatCard
        title="Win Rate"
        value={total > 0 ? `${winRate.toFixed(1)}%` : '—'}
        subtitle={`${wins} wins`}
        valueColor={total > 0 ? winRateColor : undefined}
      />
      <StatCard
        title="Avg R"
        value={avgR !== null ? formatRMultiple(avgR) : '—'}
        subtitle={`${closedWithR.length} closed trades`}
        valueColor={
          avgR !== null
            ? avgR >= 0
              ? 'var(--accent-green)'
              : 'var(--accent-red)'
            : undefined
        }
      />
      <StatCard
        title="Net PnL"
        value={total > 0 ? formatPnL(netPnl) : '—'}
        subtitle="realized"
        valueColor={total > 0 ? pnlColor : undefined}
      />
    </div>
  )
}
