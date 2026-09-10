/**
 * T-0137 — the panel where "the strategy underperformed" gets concluded must say when half
 * the strategy was never allowed to run.
 *
 * **THIS IS THE LOAD-BEARING SURFACE, AND THE RUN SUMMARY IS NOT.** `B380`'s lesson is not
 * *write the value to a surface* — it is *drive the witness from the layer where the wrong
 * conclusion would be drawn*. Nobody forms a belief about the strategy by reading a refusal
 * count. They form it by reading a P&L and a win rate, which is what this component renders.
 *
 * A run that produced no shorts and a run that produced 147 and had every one refused have the
 * same trades, the same P&L, the same win rate and the same R-multiples. Every number on this
 * panel agrees across the two. So the arms below are DIFFERENTIAL where the property is
 * differential: they render both runs and assert the output differs.
 *
 * No assertion reads the component's source. The panel is rendered and the screen is read.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const runs = vi.fn()

vi.mock('@/services/api', () => ({
  authHeaders: () => ({}),
  api: { engine: { runs: () => runs() } },
}))

import { RunHistoryPanel } from '@/components/dashboard/RunHistoryPanel'

const BASE = {
  id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
  started_at: '2026-09-10T08:00:00Z',
  ended_at: null,
  active: false,
  label: 'run one',
  note: null,
  closed_trades: 12,
  realized_pnl: -240.5,
  wins: 4,
  decisions: 300,
  abstentions: 285,
}

const LONG_ONLY = {
  ...BASE,
  config: { symbols: ['BTC/USD'], entry_tf: '5m', risk_pct: 0.01, mode: 'PAPER',
            long_only: true, venue: 'alpaca' },
  rejected_by_direction: { SHORT: 147 },
  rejections: 147,
}

const BOTH_DIRECTIONS = {
  ...BASE,
  config: { symbols: ['BTC/USD'], entry_tf: '5m', risk_pct: 0.01, mode: 'PAPER' },
  rejected_by_direction: {},
  rejections: 0,
}

beforeEach(() => { runs.mockReset() })

describe('a long-only run must not read like an ordinary one', () => {
  it('marks the run LONG ONLY beside the P&L, not buried in the collapsed detail', async () => {
    runs.mockResolvedValue([LONG_ONLY])
    render(<RunHistoryPanel />)

    const badge = await screen.findByTestId('long-only-badge')
    expect(badge.textContent).toMatch(/LONG ONLY/)
    // The reason travels with the mark. A badge a reader cannot interpret is decoration.
    expect(badge.getAttribute('title')).toMatch(/not shortable/i)
  })

  it('shows the rejections SPLIT BY DIRECTION rather than as a total', async () => {
    runs.mockResolvedValue([LONG_ONLY])
    render(<RunHistoryPanel />)

    const split = await screen.findByTestId('refusal-split')
    expect(split.textContent).toMatch(/147 SHORT rejected/)
  })

  it('does not attribute every SHORT rejection to the venue', async () => {
    // `execute()` checks entry drift, the stop and the size BEFORE `place_order`, so a SHORT
    // can be rejected without the venue ever seeing it. Beside a LONG ONLY badge, the word
    // "refused" would turn a count into a causal claim about the ruling.
    runs.mockResolvedValue([LONG_ONLY])
    render(<RunHistoryPanel />)

    const split = await screen.findByTestId('refusal-split')
    expect(split.textContent).not.toMatch(/refused/)
    expect(split.getAttribute('title')).toMatch(/entry drift/)
  })

  /**
   * WHAT THE DIFFERENTIAL IS TAKEN OVER, AND CHOOSING IT IS THE WHOLE ARM.
   *
   * Comparing whole rendered text is the WRONG SHAPE. Two runs always differ somewhere — an
   * id, a label, a start time, a duration that ticks — so `A !== B` over the container's
   * textContent collects that for free and passes while the property is broken. This projects
   * onto the two marks the property is about and nothing else.
   */
  async function marks(run: unknown): Promise<{ badge: boolean; refusals: string | null }> {
    runs.mockResolvedValue([run])
    const view = render(<RunHistoryPanel />)
    await waitFor(() => expect(view.container.textContent).toMatch(/trade/))
    const out = {
      badge: view.queryByTestId('long-only-badge') !== null,
      refusals: view.queryByTestId('refusal-split')?.textContent ?? null,
    }
    view.unmount()
    return out
  }

  it('projects onto the property and NOT onto incidental difference (negative control)',
     async () => {
    // Two both-directions runs that differ in everything a reader can see EXCEPT the property:
    // different id, label, P&L, trade count, start time. If the projection collected any of
    // that, the differential below would pass no matter what the panel rendered.
    const a = { ...BOTH_DIRECTIONS, id: 'run-a', label: 'run A', realized_pnl: -240.5 }
    const b = {
      ...BOTH_DIRECTIONS, id: 'run-b', label: 'run B', realized_pnl: 918.25,
      closed_trades: 41, wins: 22, started_at: '2026-07-02T11:30:00Z',
    }

    expect(JSON.stringify(a)).not.toBe(JSON.stringify(b))
    expect(await marks(a)).toEqual(await marks(b))
  })

  it('renders a long-only run DIFFERENTLY from a both-directions run with identical results',
     async () => {
    // THE PROPERTY ITSELF. Same trades, same P&L, same win rate, same decision counts —
    // everything a reader judges the strategy on is byte-identical between these two.
    expect(LONG_ONLY.realized_pnl).toBe(BOTH_DIRECTIONS.realized_pnl)
    expect(LONG_ONLY.closed_trades).toBe(BOTH_DIRECTIONS.closed_trades)
    expect(LONG_ONLY.wins).toBe(BOTH_DIRECTIONS.wins)

    const constrained = await marks(LONG_ONLY)
    const unconstrained = await marks(BOTH_DIRECTIONS)

    expect(constrained).not.toEqual(unconstrained)
    expect(constrained.badge).toBe(true)
    expect(unconstrained.badge).toBe(false)
    expect(unconstrained.refusals).toBeNull()
  })

  it('does not label an older run long-only just because it has no venue recorded', async () => {
    // Runs recorded before the ruling have no `long_only` key at all. Reading a missing value
    // as `true` would relabel history; reading it as `false` is the honest default and is what
    // the panel's own doctrine requires — settings are SHOWN, never inferred.
    runs.mockResolvedValue([{ ...BASE, config: { symbols: ['BTC/USD'], mode: 'PAPER' },
                              rejected_by_direction: null }])
    render(<RunHistoryPanel />)

    await waitFor(() => expect(screen.getByText(/run one/)).toBeTruthy())
    expect(screen.queryByTestId('long-only-badge')).toBeNull()
    expect(screen.queryByTestId('refusal-split')).toBeNull()
  })

  it('survives an endpoint that has not been redeployed yet', async () => {
    // The field is absent, not empty. A panel that throws here would take the whole run
    // history down over a value it only decorates with.
    runs.mockResolvedValue([{ ...BASE, config: { mode: 'PAPER' } }])
    render(<RunHistoryPanel />)
    await waitFor(() => expect(screen.getByText(/run one/)).toBeTruthy())
  })
})
