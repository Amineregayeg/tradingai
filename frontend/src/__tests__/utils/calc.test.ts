import { describe, it, expect } from 'vitest'
import {
  calcRR,
  calcRMultiple,
  calcSession,
  calcLotSize,
  calcPips,
  calcPipValue,
} from '@/utils/calc'

// ─── calcRR ───────────────────────────────────────────────────────────────────

describe('calcRR', () => {
  it('calculates R:R for LONG trade (risk 50 pips, reward 100 pips → 2R)', () => {
    const rr = calcRR(1.0850, 1.0800, 1.0950, 'LONG')
    expect(rr).toBeCloseTo(2.0, 1)
  })

  it('calculates R:R for SHORT trade (risk 50 pips, reward 100 pips → 2R)', () => {
    const rr = calcRR(1.0850, 1.0900, 1.0750, 'SHORT')
    expect(rr).toBeCloseTo(2.0, 1)
  })

  it('returns 0 when SL equals entry (no risk)', () => {
    const rr = calcRR(1.0850, 1.0850, 1.0950, 'LONG')
    expect(rr).toBe(0)
  })

  it('returns 0 when SL is beyond entry for LONG (invalid setup)', () => {
    // SL above entry for LONG → risk <= 0
    const rr = calcRR(1.0850, 1.0900, 1.0950, 'LONG')
    expect(rr).toBe(0)
  })

  it('returns 0 when SL is beyond entry for SHORT (invalid setup)', () => {
    // SL below entry for SHORT → risk <= 0
    const rr = calcRR(1.0850, 1.0800, 1.0750, 'SHORT')
    expect(rr).toBe(0)
  })

  it('calculates 1:1 R:R for LONG', () => {
    const rr = calcRR(1.0850, 1.0800, 1.0900, 'LONG')
    expect(rr).toBeCloseTo(1.0, 1)
  })

  it('calculates 3:1 R:R for SHORT', () => {
    const rr = calcRR(1.0850, 1.0900, 1.0700, 'SHORT')
    expect(rr).toBeCloseTo(3.0, 1)
  })
})

// ─── calcRMultiple ────────────────────────────────────────────────────────────

describe('calcRMultiple', () => {
  it('calculates 1R at TP for LONG trade', () => {
    // Entry 1.0850, SL 1.0800 (50 pip risk), Exit 1.0900 (50 pips profit = 1R)
    const r = calcRMultiple(1.0850, 1.0900, 1.0800, 'LONG')
    expect(r).toBeCloseTo(1.0, 1)
  })

  it('calculates 2R for LONG trade', () => {
    // Entry 1.0850, SL 1.0800 (50 pip risk), Exit 1.0950 (100 pips profit = 2R)
    const r = calcRMultiple(1.0850, 1.0950, 1.0800, 'LONG')
    expect(r).toBeCloseTo(2.0, 1)
  })

  it('calculates negative R for losing LONG trade', () => {
    // Entry 1.0850, SL 1.0800, Exit at SL 1.0800 → -1R
    const r = calcRMultiple(1.0850, 1.0800, 1.0800, 'LONG')
    expect(r).toBeLessThanOrEqual(0)
  })

  it('calculates 1R at TP for SHORT trade', () => {
    // Entry 1.0850, SL 1.0900 (50 pip risk), Exit 1.0800 (50 pips profit = 1R)
    const r = calcRMultiple(1.0850, 1.0800, 1.0900, 'SHORT')
    expect(r).toBeCloseTo(1.0, 1)
  })

  it('calculates 2R for SHORT trade', () => {
    // Entry 1.0850, SL 1.0900 (50 pip risk), Exit 1.0750 (100 pips profit = 2R)
    const r = calcRMultiple(1.0850, 1.0750, 1.0900, 'SHORT')
    expect(r).toBeCloseTo(2.0, 1)
  })

  it('returns 0 when SL equals entry (no risk)', () => {
    const r = calcRMultiple(1.0850, 1.0900, 1.0850, 'LONG')
    expect(r).toBe(0)
  })

  it('calculates -1R exactly when exit is at stop loss for LONG', () => {
    // Exit = SL = 1.0800, risk = 50 pips, profit = -50 pips → -1R
    const r = calcRMultiple(1.0850, 1.0800, 1.0800, 'LONG')
    expect(r).toBeCloseTo(-1.0, 1)
  })
})

// ─── calcSession ──────────────────────────────────────────────────────────────

describe('calcSession', () => {
  it('returns asian for hour 0 (midnight UTC)', () => {
    expect(calcSession(0)).toBe('asian')
  })

  it('returns asian for hour 2 (early Asian session)', () => {
    expect(calcSession(2)).toBe('asian')
  })

  it('returns asian for hour 7 (last Asian hour)', () => {
    expect(calcSession(7)).toBe('asian')
  })

  it('returns london for hour 8 (London open)', () => {
    expect(calcSession(8)).toBe('london')
  })

  it('returns london for hour 9 (London session)', () => {
    expect(calcSession(9)).toBe('london')
  })

  it('returns london for hour 12 (last London-only hour)', () => {
    expect(calcSession(12)).toBe('london')
  })

  it('returns overlap for hour 13 (London/NY overlap opens)', () => {
    expect(calcSession(13)).toBe('overlap')
  })

  it('returns overlap for hour 14 (NY session overlap)', () => {
    expect(calcSession(14)).toBe('overlap')
  })

  it('returns overlap for hour 16 (last overlap hour)', () => {
    expect(calcSession(16)).toBe('overlap')
  })

  it('returns ny for hour 17 (NY after London close)', () => {
    expect(calcSession(17)).toBe('ny')
  })

  it('returns ny for hour 20 (NY session)', () => {
    expect(calcSession(20)).toBe('ny')
  })

  it('returns ny for hour 21 (last NY hour)', () => {
    expect(calcSession(21)).toBe('ny')
  })

  it('returns off for hour 22', () => {
    expect(calcSession(22)).toBe('off')
  })

  it('returns off for hour 23', () => {
    expect(calcSession(23)).toBe('off')
  })

  it('normalizes hours >= 24 correctly', () => {
    // 24 normalizes to 0 → asian
    expect(calcSession(24)).toBe('asian')
  })
})

// ─── calcLotSize ──────────────────────────────────────────────────────────────

describe('calcLotSize', () => {
  it('calculates lot size correctly for EURUSD', () => {
    // $10,000 balance, 1% risk = $100, 20 pips SL, pip value $10 → 0.50 lots
    const lots = calcLotSize(10000, 1, 20, 'EURUSD')
    expect(lots).toBeCloseTo(0.5, 2)
  })

  it('returns 0 when slPips is 0', () => {
    expect(calcLotSize(10000, 1, 0, 'EURUSD')).toBe(0)
  })

  it('returns 0 when balance is 0', () => {
    expect(calcLotSize(0, 1, 20, 'EURUSD')).toBe(0)
  })

  it('returns 0 when riskPct is 0', () => {
    expect(calcLotSize(10000, 0, 20, 'EURUSD')).toBe(0)
  })

  it('uses a default pip value for unknown pairs', () => {
    // Fallback pip value is 10, same as EURUSD
    const known = calcLotSize(10000, 1, 20, 'EURUSD')
    const unknown = calcLotSize(10000, 1, 20, 'UNKNOWN')
    expect(known).toBe(unknown)
  })
})

// ─── calcPips ─────────────────────────────────────────────────────────────────

describe('calcPips', () => {
  it('calculates pips for a 4-decimal pair', () => {
    // 1.0900 - 1.0800 = 0.0100 / 0.0001 = 100 pips
    expect(calcPips(1.0900, 1.0800, 'EURUSD')).toBe(100)
  })

  it('calculates pips for a JPY pair (0.01 pip size)', () => {
    // 150.00 - 149.50 = 0.50 / 0.01 = 50 pips
    expect(calcPips(150.00, 149.50, 'USDJPY')).toBe(50)
  })

  it('is commutative (absolute difference)', () => {
    expect(calcPips(1.0800, 1.0900, 'EURUSD')).toBe(calcPips(1.0900, 1.0800, 'EURUSD'))
  })
})

// ─── calcPipValue ─────────────────────────────────────────────────────────────

describe('calcPipValue', () => {
  it('calculates pip value for 1 lot EURUSD ($10 per lot per pip)', () => {
    expect(calcPipValue(1, 'EURUSD')).toBe(10)
  })

  it('calculates pip value for 0.5 lots', () => {
    expect(calcPipValue(0.5, 'EURUSD')).toBe(5)
  })

  it('calculates pip value for USDJPY', () => {
    // 9.1 per standard lot
    expect(calcPipValue(1, 'USDJPY')).toBe(9.1)
  })
})
