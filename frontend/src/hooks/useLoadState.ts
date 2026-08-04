import { useCallback, useState } from 'react'

/**
 * Track which loads failed, so an outage cannot render as "no data" (E3).
 *
 * THE BUG THIS EXISTS TO KILL
 * Seven of nine pages caught fetch errors and substituted an empty value:
 *
 *     api.trades.list(...).catch(() => setTrades([]))
 *
 * The page then renders its empty state. A dead API and a genuinely quiet week
 * become pixel-identical, and the quiet week is the reading people reach for —
 * so "no trades this week" gets believed when the truth is "the backend is
 * down". On a platform whose entire job is telling you what happened, a
 * confident wrong answer is worse than an error.
 *
 * WHY A FALLBACK IS STILL RETURNED
 * The fallback is not the problem; rendering it *silently* is. A page that
 * throws on one failed request loses the sections that did load, which is a
 * worse outage than a partial one. So `track` keeps the fallback and records
 * the failure, letting the page show what it has and say plainly what it does
 * not.
 *
 * Names are used rather than booleans because pages load several things at
 * once, and "trades could not be loaded" is actionable where "something failed"
 * is not.
 *
 * Recovery is automatic: a later successful load of the same name clears it, so
 * polling pages heal without a reload.
 */
export function useLoadState() {
  const [failed, setFailed] = useState<string[]>([])

  const track = useCallback(
    <T,>(what: string, p: Promise<T>, fallback: T): Promise<T> =>
      p.then(
        (value) => {
          setFailed((f) => (f.includes(what) ? f.filter((x) => x !== what) : f))
          return value
        },
        () => {
          setFailed((f) => (f.includes(what) ? f : [...f, what]))
          return fallback
        }
      ),
    []
  )

  return { failed, track }
}
