import { format, parseISO } from 'date-fns'

/**
 * Format a price to the specified number of decimal places.
 * e.g. formatPrice(1.23456) → "1.23456"
 */
export function formatPrice(price: number, decimals = 5): string {
  return price.toFixed(decimals)
}

/**
 * Format a PnL value with sign and dollar symbol.
 * e.g. formatPnL(1234.56) → "+$1,234.56"
 * e.g. formatPnL(-234.56) → "-$234.56"
 */
export function formatPnL(pnl: number): string {
  const abs = Math.abs(pnl)
  const formatted = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(abs)
  const sign = pnl >= 0 ? '+' : '-'
  return `${sign}$${formatted}`
}

/**
 * Format pips value.
 * e.g. formatPips(12.3) → "+12.3 pips"
 * e.g. formatPips(-5.1) → "-5.1 pips"
 */
export function formatPips(pips: number): string {
  const sign = pips >= 0 ? '+' : ''
  return `${sign}${pips.toFixed(1)} pips`
}

/**
 * Format a duration in seconds to a human-readable string.
 * e.g. formatDuration(9240) → "2h 34m"
 * e.g. formatDuration(45)   → "45s"
 * e.g. formatDuration(180)  → "3m"
 */
export function formatDuration(seconds: number): string {
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = seconds % 60

  if (h > 0) {
    return m > 0 ? `${h}h ${m}m` : `${h}h`
  }
  if (m > 0) {
    return s > 0 && m < 5 ? `${m}m ${s}s` : `${m}m`
  }
  return `${s}s`
}

/**
 * Format an ISO datetime string to "May 16 14:23".
 */
export function formatDateTime(iso: string): string {
  try {
    return format(parseISO(iso), 'MMM d HH:mm')
  } catch {
    return iso
  }
}

/**
 * Format an ISO datetime string to "May 16".
 */
export function formatDate(iso: string): string {
  try {
    return format(parseISO(iso), 'MMM d')
  } catch {
    return iso
  }
}

/**
 * Format a number as a percentage string.
 * e.g. formatPercent(1.234) → "1.23%"
 */
export function formatPercent(n: number, decimals = 2): string {
  return `${n.toFixed(decimals)}%`
}

/**
 * Format a number with commas.
 * e.g. formatNumber(1234567.89) → "1,234,567.89"
 */
export function formatNumber(n: number, decimals = 2): string {
  return new Intl.NumberFormat('en-US', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(n)
}

/**
 * Format an R-multiple value.
 * e.g. formatRMultiple(2.5) → "+2.5R"
 */
export function formatRMultiple(r: number): string {
  const sign = r >= 0 ? '+' : ''
  return `${sign}${r.toFixed(2)}R`
}
