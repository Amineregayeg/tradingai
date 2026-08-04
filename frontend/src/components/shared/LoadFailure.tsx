import { Banner } from '@/components/ui'

/**
 * Says outright that data is missing because a request failed (E3).
 *
 * Pairs with `useLoadState`. The wording is deliberate on two points:
 *
 *   * it names WHAT failed, because "trades could not be loaded" tells you
 *     which numbers on the page to distrust and "something went wrong" does not;
 *   * it says the figures are INCOMPLETE rather than absent. The page below is
 *     still rendering — with fallbacks — and the risk being defended against is
 *     someone reading those fallbacks as a real result.
 */
export function LoadFailure({ what }: { what: string[] }) {
  if (what.length === 0) return null

  const list =
    what.length === 1
      ? what[0]
      : `${what.slice(0, -1).join(', ')} and ${what[what.length - 1]}`

  return (
    <div style={{ marginBottom: 14 }}>
      <Banner variant="error" title={`Could not load ${list}.`}>
        What is shown below is incomplete — this is a loading failure, not an
        empty result. It will clear on its own once the data loads.
      </Banner>
    </div>
  )
}
