import { usePricesStore } from '@/stores/pricesStore'

interface UsePricesReturn {
  bid: number | null
  ask: number | null
  spread: number | null
  timestamp: string | null
}

/**
 * Returns the latest price data for a given currency pair.
 * Updates reactively whenever a new tick arrives via WebSocket.
 */
export function usePrices(pair: string): UsePricesReturn {
  const tick = usePricesStore((s) => s.ticks[pair])

  if (!tick) {
    return { bid: null, ask: null, spread: null, timestamp: null }
  }

  return {
    bid: tick.bid,
    ask: tick.ask,
    spread: tick.spread,
    timestamp: tick.timestamp,
  }
}
