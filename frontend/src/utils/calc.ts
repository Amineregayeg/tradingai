import type { Direction } from '@/types/api'

// ─── Pip values per pair (approximate) ───────────────────────────────────────

const PIP_VALUES: Record<string, number> = {
  // Major pairs (USD quote) — 1 pip = $10 per standard lot (100k units)
  EURUSD: 10,
  GBPUSD: 10,
  AUDUSD: 10,
  NZDUSD: 10,
  USDCAD: 7.5, // approximate, varies with USDCAD rate
  USDCHF: 10,
  USDJPY: 9.1, // approximate
  // Cross pairs — approximate
  EURGBP: 12.5,
  EURJPY: 9.1,
  GBPJPY: 9.1,
  AUDJPY: 9.1,
  XAUUSD: 10, // gold
  XAGUSD: 10, // silver
}

function getPipValue(pair: string): number {
  const clean = pair.replace('/', '').toUpperCase()
  return PIP_VALUES[clean] ?? 10
}

// ─── Public calculations ──────────────────────────────────────────────────────

/**
 * Calculate the Risk:Reward ratio.
 * Returns how many R units the trade targets (e.g. 2.5 means 2.5R).
 */
export function calcRR(
  entry: number,
  sl: number,
  tp: number,
  direction: Direction
): number {
  const risk = direction === 'LONG' ? entry - sl : sl - entry
  const reward = direction === 'LONG' ? tp - entry : entry - tp

  if (risk <= 0) return 0
  return parseFloat((reward / risk).toFixed(2))
}

/**
 * Calculate the appropriate lot size given account balance,
 * risk percentage, SL in pips, and currency pair.
 *
 * lotSize = (balance × riskPct/100) / (slPips × pipValuePerLot)
 */
export function calcLotSize(
  balance: number,
  riskPct: number,
  slPips: number,
  pair: string
): number {
  if (slPips <= 0 || balance <= 0 || riskPct <= 0) return 0
  const riskAmount = balance * (riskPct / 100)
  const pipValue = getPipValue(pair)
  const lots = riskAmount / (slPips * pipValue)
  // Round to 2 decimal places (0.01 lot increments)
  return parseFloat(lots.toFixed(2))
}

/**
 * Determine the trading session based on UTC hour.
 * - Asian:   00:00–07:59 UTC
 * - London:  08:00–09:59 UTC (pre-NY overlap)
 * - Overlap: 13:00–16:59 UTC (London/NY)
 * - NY:      10:00–12:59 and 17:00–21:59 UTC
 * - Off:     22:00–23:59 UTC
 */
export function calcSession(
  utcHour: number
): 'asian' | 'london' | 'ny' | 'overlap' | 'off' {
  const h = ((utcHour % 24) + 24) % 24 // normalize
  if (h >= 0 && h < 8) return 'asian'
  if (h >= 8 && h < 13) return 'london'
  if (h >= 13 && h < 17) return 'overlap'
  if (h >= 17 && h < 22) return 'ny'
  return 'off'
}

/**
 * Calculate the R-multiple of a completed trade.
 * Positive = winner, negative = loser.
 */
export function calcRMultiple(
  entry: number,
  exit: number,
  sl: number,
  direction: Direction
): number {
  const risk = direction === 'LONG' ? entry - sl : sl - entry
  if (risk <= 0) return 0

  const profit = direction === 'LONG' ? exit - entry : entry - exit
  return parseFloat((profit / risk).toFixed(2))
}

/**
 * Calculate the number of pips between two prices for a given pair.
 * Assumes 4-decimal pairs use 0.0001 pip size, JPY pairs use 0.01.
 */
export function calcPips(price1: number, price2: number, pair: string): number {
  const isJpy = pair.toUpperCase().includes('JPY')
  const pipSize = isJpy ? 0.01 : 0.0001
  return parseFloat((Math.abs(price1 - price2) / pipSize).toFixed(1))
}

/**
 * Calculate the dollar value of pips for a given lot size and pair.
 */
export function calcPipValue(lots: number, pair: string): number {
  const pipValue = getPipValue(pair)
  return parseFloat((lots * pipValue).toFixed(2))
}
