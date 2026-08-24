/**
 * T-0065 / `B228` — ARM 5: BOTH empty cases, asserted.
 *
 * The handler used to ignore EVERY empty list, by design, so a freshly-reconnected broker
 * could not stomp the panel — **which also meant there was no path by which the panel could
 * ever clear.** A closed position stayed on screen until a reload.
 *
 * The guard was right about the hazard and wrong to infer it from emptiness: both cases look
 * identical from the client. The sender knows which it is in, so the sender says.
 *
 * **Asserting only the clearing half would trade one collapse for another** and silently drop
 * the reconnect protection the original comment was written for.
 */
import { beforeEach, describe, expect, it } from 'vitest'
import { usePositionsStore } from '@/stores/positionsStore'
import type { Position } from '@/types/api'

const POSITION = { id: 'p-1', pair: 'BTC/USD' } as unknown as Position

/** The shipped handler body, kept in one place so both arms exercise the same code. */
function onUpdate(data: { positions?: unknown; authoritative?: boolean }): void {
  if (!Array.isArray(data?.positions)) return
  if (data.positions.length > 0 || data.authoritative === true) {
    usePositionsStore.getState().setPositions(data.positions as Position[])
  }
}

describe('positions.update', () => {
  beforeEach(() => {
    usePositionsStore.getState().setPositions([POSITION])
  })

  it('CLEARS on an authoritative empty — the path that did not exist', () => {
    onUpdate({ positions: [], authoritative: true })
    expect(usePositionsStore.getState().positions).toEqual([])
  })

  it('does NOT clear on a non-authoritative empty — the reconnect protection survives', () => {
    onUpdate({ positions: [], authoritative: false })
    expect(usePositionsStore.getState().positions).toHaveLength(1)
  })

  it('treats an ABSENT flag as non-authoritative, so an older server keeps the old behaviour', () => {
    onUpdate({ positions: [] })
    expect(usePositionsStore.getState().positions).toHaveLength(1)
  })

  it('still overwrites on a non-empty list, authoritative or not', () => {
    const other = { id: 'p-2', pair: 'ETH/USD' } as unknown as Position
    onUpdate({ positions: [other] })
    expect(usePositionsStore.getState().positions).toHaveLength(1)
    expect(usePositionsStore.getState().positions[0].id).toBe('p-2')
  })

  it('ignores a payload whose positions field is missing — the single-dict shape B228 found', () => {
    onUpdate({ authoritative: true } as { authoritative: boolean })
    expect(usePositionsStore.getState().positions).toHaveLength(1)
  })
})
