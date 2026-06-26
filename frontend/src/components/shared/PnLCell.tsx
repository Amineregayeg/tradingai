import { formatPnL } from '@/utils/format'

export interface PnLCellProps {
  value: number | null
  suffix?: string
  showSign?: boolean
}

export function PnLCell({ value, suffix, showSign = true }: PnLCellProps) {
  if (value === null || value === undefined) {
    return (
      <span style={{ color: 'var(--text-muted)', fontSize: 'var(--text-sm)' }}>—</span>
    )
  }

  const isPositive = value >= 0
  const isNegative = value < 0

  let display: string
  if (suffix === '$' || !suffix) {
    display = formatPnL(value)
  } else if (suffix === 'R') {
    const sign = showSign ? (isPositive ? '+' : '') : ''
    display = `${sign}${value.toFixed(2)}R`
  } else if (suffix === 'pips') {
    const sign = showSign ? (isPositive ? '+' : '') : ''
    display = `${sign}${value.toFixed(1)} pips`
  } else {
    const sign = showSign ? (isPositive ? '+' : '') : ''
    display = `${sign}${value.toFixed(2)} ${suffix}`
  }

  return (
    <span
      style={{
        color: isPositive
          ? 'var(--accent-green)'
          : isNegative
          ? 'var(--accent-red)'
          : 'var(--text-muted)',
        fontWeight: 'var(--weight-medium)',
        fontSize: 'var(--text-sm)',
      }}
    >
      {display}
    </span>
  )
}
