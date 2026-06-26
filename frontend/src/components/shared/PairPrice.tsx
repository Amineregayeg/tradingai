import { useEffect, useRef, useState } from 'react'
import { clsx } from 'clsx'
import { usePrices } from '@/hooks/usePrices'
import { formatPrice } from '@/utils/format'

export interface PairPriceProps {
  pair: string
  decimals?: number
  showSpread?: boolean
  className?: string
}

type FlashDirection = 'up' | 'down' | null

/**
 * Displays live bid/ask prices for a currency pair.
 * Briefly flashes green (up) or red (down) when price changes.
 */
export function PairPrice({ pair, decimals = 5, showSpread = false, className }: PairPriceProps) {
  const { bid, ask, spread } = usePrices(pair)
  const prevBidRef = useRef<number | null>(null)
  const [flashDir, setFlashDir] = useState<FlashDirection>(null)
  const flashTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    if (bid === null) return

    const prev = prevBidRef.current
    if (prev !== null && bid !== prev) {
      const dir: FlashDirection = bid > prev ? 'up' : 'down'
      setFlashDir(dir)

      if (flashTimer.current) clearTimeout(flashTimer.current)
      flashTimer.current = setTimeout(() => setFlashDir(null), 650)
    }
    prevBidRef.current = bid

    return () => {
      if (flashTimer.current) clearTimeout(flashTimer.current)
    }
  }, [bid])

  if (bid === null || ask === null) {
    return (
      <div className={clsx('flex items-center gap-3', className)}>
        <span className="text-[var(--text-sm)] font-medium text-[var(--text-primary)]">{pair}</span>
        <span className="text-[var(--text-muted)] text-[var(--text-sm)]">—</span>
      </div>
    )
  }

  return (
    <div
      className={clsx(
        'flex items-center gap-3 rounded-[var(--radius-sm)] px-1 -mx-1',
        'transition-colors duration-[var(--duration-fast)]',
        flashDir === 'up' && 'flash-green',
        flashDir === 'down' && 'flash-red',
        className
      )}
    >
      {/* Pair name */}
      <span className="text-[var(--text-sm)] font-medium text-[var(--text-secondary)] min-w-[60px]">
        {pair}
      </span>

      {/* Bid */}
      <div className="flex flex-col items-end">
        <span className="text-[10px] text-[var(--text-muted)] leading-none">BID</span>
        <span
          className={clsx(
            'font-mono text-[var(--text-sm)] font-medium leading-tight',
            flashDir === 'down' ? 'text-[var(--accent-red)]' : 'text-[var(--text-primary)]'
          )}
        >
          {formatPrice(bid, decimals)}
        </span>
      </div>

      {/* Divider */}
      <span className="text-[var(--border-light)]">|</span>

      {/* Ask */}
      <div className="flex flex-col items-start">
        <span className="text-[10px] text-[var(--text-muted)] leading-none">ASK</span>
        <span
          className={clsx(
            'font-mono text-[var(--text-sm)] font-medium leading-tight',
            flashDir === 'up' ? 'text-[var(--accent-green)]' : 'text-[var(--text-primary)]'
          )}
        >
          {formatPrice(ask, decimals)}
        </span>
      </div>

      {/* Spread */}
      {showSpread && spread !== null && (
        <span className="text-[var(--text-xs)] text-[var(--text-muted)]">
          {(spread * 10000).toFixed(1)} pts
        </span>
      )}
    </div>
  )
}
