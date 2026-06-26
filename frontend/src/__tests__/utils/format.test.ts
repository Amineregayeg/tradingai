import { describe, it, expect } from 'vitest'
import {
  formatPnL,
  formatPrice,
  formatPercent,
  formatDuration,
  formatRMultiple,
  formatPips,
  formatNumber,
  formatDateTime,
  formatDate,
} from '@/utils/format'

// ─── formatPnL ────────────────────────────────────────────────────────────────

describe('formatPnL', () => {
  it('formats positive PnL with + prefix and $ sign', () => {
    expect(formatPnL(1234.56)).toMatch(/^\+\$1,234\.56$/)
  })

  it('formats negative PnL with - prefix and $ sign', () => {
    expect(formatPnL(-234.56)).toMatch(/^-\$234\.56$/)
  })

  it('formats zero as +$0.00', () => {
    // Zero is treated as non-negative (sign is +)
    expect(formatPnL(0)).toBe('+$0.00')
  })

  it('formats small positive value', () => {
    expect(formatPnL(0.50)).toBe('+$0.50')
  })

  it('formats large negative value with commas', () => {
    expect(formatPnL(-10000)).toBe('-$10,000.00')
  })
})

// ─── formatPrice ──────────────────────────────────────────────────────────────

describe('formatPrice', () => {
  it('formats to 5 decimal places by default', () => {
    expect(formatPrice(1.08356)).toBe('1.08356')
  })

  it('respects custom decimals of 2', () => {
    expect(formatPrice(1.08356, 2)).toBe('1.08')
  })

  it('respects custom decimals of 0', () => {
    expect(formatPrice(1234.5, 0)).toBe('1235')
  })

  it('pads trailing zeros to meet decimal count', () => {
    expect(formatPrice(1.1, 5)).toBe('1.10000')
  })

  it('rounds to specified decimals', () => {
    expect(formatPrice(1.123456789, 4)).toBe('1.1235')
  })
})

// ─── formatPercent ────────────────────────────────────────────────────────────

describe('formatPercent', () => {
  it('adds % suffix', () => {
    expect(formatPercent(1.23)).toContain('%')
  })

  it('defaults to 2 decimal places', () => {
    expect(formatPercent(1.23456)).toBe('1.23%')
  })

  it('respects custom decimals', () => {
    expect(formatPercent(1.23456, 0)).toBe('1%')
    expect(formatPercent(1.23456, 3)).toBe('1.235%')
  })

  it('formats zero correctly', () => {
    expect(formatPercent(0)).toBe('0.00%')
  })

  it('formats negative percent', () => {
    expect(formatPercent(-5.5)).toBe('-5.50%')
  })
})

// ─── formatDuration ───────────────────────────────────────────────────────────

describe('formatDuration', () => {
  it('formats hours when >= 3600 seconds', () => {
    expect(formatDuration(3600)).toContain('h')
  })

  it('formats 3600 seconds as 1h (no minutes)', () => {
    expect(formatDuration(3600)).toBe('1h')
  })

  it('formats hours with minutes when both present', () => {
    expect(formatDuration(9240)).toBe('2h 34m')
  })

  it('formats minutes when < 3600 seconds', () => {
    expect(formatDuration(90)).toContain('m')
  })

  it('formats 3 minutes exactly', () => {
    expect(formatDuration(180)).toBe('3m')
  })

  it('formats seconds when < 60 seconds', () => {
    expect(formatDuration(45)).toBe('45s')
  })

  it('formats minutes with seconds when < 5 minutes and has remainder', () => {
    // 2m 30s → less than 5 minutes, has seconds
    expect(formatDuration(150)).toBe('2m 30s')
  })

  it('formats exactly 5 minutes as 5m (no seconds shown)', () => {
    // 5m 0s → m >= 5, so no seconds
    expect(formatDuration(300)).toBe('5m')
  })
})

// ─── formatRMultiple ──────────────────────────────────────────────────────────

describe('formatRMultiple', () => {
  it('prefixes positive R with + sign', () => {
    expect(formatRMultiple(2.5)).toBe('+2.50R')
  })

  it('formats zero as +0.00R', () => {
    expect(formatRMultiple(0)).toBe('+0.00R')
  })

  it('formats negative R without extra - prefix (sign is from toFixed)', () => {
    expect(formatRMultiple(-1)).toBe('-1.00R')
  })

  it('formats two decimal places', () => {
    expect(formatRMultiple(1.5)).toBe('+1.50R')
  })
})

// ─── formatPips ───────────────────────────────────────────────────────────────

describe('formatPips', () => {
  it('formats positive pips with + prefix', () => {
    expect(formatPips(12.3)).toBe('+12.3 pips')
  })

  it('formats negative pips without extra + prefix', () => {
    expect(formatPips(-5.1)).toBe('-5.1 pips')
  })

  it('formats zero pips with + prefix', () => {
    expect(formatPips(0)).toBe('+0.0 pips')
  })
})

// ─── formatNumber ─────────────────────────────────────────────────────────────

describe('formatNumber', () => {
  it('formats with commas and 2 decimal places by default', () => {
    expect(formatNumber(1234567.89)).toBe('1,234,567.89')
  })

  it('respects custom decimal argument', () => {
    expect(formatNumber(1000, 0)).toBe('1,000')
  })
})

// ─── formatDateTime ───────────────────────────────────────────────────────────

describe('formatDateTime', () => {
  it('formats ISO string to "MMM d HH:mm" format', () => {
    // 2024-05-16T14:23:00Z — exact format depends on locale/date-fns
    const result = formatDateTime('2024-05-16T14:23:00.000Z')
    expect(result).toMatch(/May \d{1,2} \d{2}:\d{2}/)
  })

  it('returns original string for invalid ISO input', () => {
    expect(formatDateTime('not-a-date')).toBe('not-a-date')
  })
})

// ─── formatDate ───────────────────────────────────────────────────────────────

describe('formatDate', () => {
  it('formats ISO string to "MMM d" format', () => {
    const result = formatDate('2024-05-16T00:00:00.000Z')
    expect(result).toMatch(/May \d{1,2}/)
  })

  it('returns original string for invalid ISO input', () => {
    expect(formatDate('bad-input')).toBe('bad-input')
  })
})
