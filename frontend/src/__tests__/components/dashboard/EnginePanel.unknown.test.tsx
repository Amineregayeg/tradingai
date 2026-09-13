/**
 * B431 — a count the engine could not COMPUTE must not render as a count of zero.
 *
 * The backend now sends `null` for `closed_trades`, `wins`, `losses` and `win_rate` when the
 * realized-trade ledger is unavailable — a broker without one (any real venue adapter) with the
 * database also unreachable. Before this the panel would have rendered:
 *
 * ```
 * Wins / Losses   nullW · nullL     in GREEN
 * ```
 *
 * because a template literal stringifies `null`, and **`null >= null` is `true` in JavaScript**,
 * so the colour test for "winning" passes on two absent numbers. Two independent ways for an
 * unknown to present itself as a healthy result, in one three-line component.
 *
 * No assertion reads the component's source.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const getStatus = vi.fn()
const fetchMock = vi.fn()

// Mirrors EnginePanel.halt.test.tsx exactly: a NAMED export, `vi.stubGlobal` for fetch, and the
// ws surface this component actually uses (`subscribe`/`on`/`off`). My first version guessed
// `connect`/`disconnect` and a default export, and the panel rendered as `undefined` — a mock
// shaped for a component that does not exist tests nothing.
vi.stubGlobal('fetch', fetchMock)
vi.mock('@/services/api', () => ({ authHeaders: () => ({}) }))
vi.mock('@/services/ws', () => ({
  wsService: { subscribe: () => () => {}, on: () => () => {}, off: () => {} },
}))

import { EnginePanel } from '@/components/dashboard/EnginePanel'

const MEASURED = {
  running: true, paused: false, mode: 'PAPER', symbols: ['BTC/USD'],
  equity: 10_500, balance: 10_400, total_pnl: 400, total_pnl_pct: 4,
  win_rate: 60, closed_trades: 5, wins: 3, losses: 2,
  open_positions: 0, risk_pct: 0.01, entry_tf: '1H',
  counts_unavailable: [] as string[],
}

/** The ledger could not be read: every derived figure is absent, not zero. */
const UNKNOWN = {
  ...MEASURED,
  win_rate: null, closed_trades: null, wins: null, losses: null,
  counts_unavailable: ['_closed'],
}

beforeEach(() => {
  getStatus.mockReset()
  fetchMock.mockReset()
  fetchMock.mockImplementation(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(getStatus()) }),
  )
})

async function mount() {
  render(<EnginePanel />)
  await waitFor(() => expect(screen.getByText('LIVE ENGINE')).toBeTruthy())
}

/** The VALUE rendered under a given Stat label.
 *
 * **Scoped deliberately.** Asserting the em dash against the whole panel passed on the pre-fix
 * render, because the Win rate stat beside it ALREADY renders an em dash for a null — a
 * neighbouring defence satisfying the arm for the mechanism under test. Measured twice: the
 * whole-panel form survived the defect, this form does not.
 */
function statValue(label: string): string {
  const k = screen.getByText(label)
  return k.nextElementSibling?.textContent ?? ''
}

describe('B431 — unknown counts do not render as zeros', () => {
  it('CONTROL: measured counts still render as numbers', async () => {
    getStatus.mockReturnValue(MEASURED)
    await mount()

    // POSITIVE FIRST: an arm whose only assertion is an absence passes over a panel that
    // rendered nothing at all.
    await waitFor(() => expect(screen.getByText('3W · 2L')).toBeTruthy())
    expect(screen.getByText('60%')).toBeTruthy()
  })

  it('an unavailable ledger renders an em dash, NOT nullW · nullL', async () => {
    getStatus.mockReturnValue(UNKNOWN)
    await mount()

    await waitFor(() => expect(screen.getByText('LIVE ENGINE')).toBeTruthy())
    expect(document.body.textContent).not.toMatch(/null/i)
    expect(document.body.textContent).not.toMatch(/0W · 0L/)
  })

  it('the unknown state renders the em dash POSITIVELY, not merely something different', async () => {
    getStatus.mockReturnValue(MEASURED)
    const { unmount } = render(<EnginePanel />)
    await waitFor(() => expect(screen.getByText('3W · 2L')).toBeTruthy())
    const measuredWL = statValue('Wins / Losses')
    unmount()

    getStatus.mockReturnValue(UNKNOWN)
    await mount()
    const unknownWL = statValue('Wins / Losses')

    // **`A != B` PASSES ON INCIDENTAL DIFFERENCE, and this arm did.** Measured against the
    // pre-fix render: `nullW · nullL` differs from `3W · 2L` perfectly well, so asserting only
    // that the two states differ SURVIVED the defect. Two of three arms here fired; this one did
    // not, and it was the one named for the discrimination.
    //
    // So it asserts the RIGHT ANSWER'S SHAPE instead: the unknown state must render the same
    // muted placeholder every other unknown on this panel renders.
    expect(unknownWL).toBe('—')
    expect(measuredWL).toBe('3W · 2L')
    expect(measuredWL).not.toEqual(unknownWL)
  })
})

describe('B431 — the reason is RENDERED, not merely typed', () => {
  it('names why the counts are unavailable, so a dash is not just a dash', async () => {
    getStatus.mockReturnValue(UNKNOWN)
    await mount()

    // **A TYPE DECLARATION IS NOT A CONSUMER.** `counts_unavailable` existed on the payload and in
    // the TS interface of both consumers, and was rendered by neither — so the operator saw an em
    // dash and could not tell a database outage from a broker that keeps no ledger. Third
    // iteration of one class: 500s, then 0 explained by an unreachable key, then a dash explained
    // by an unrendered one.
    const text = document.body.textContent ?? ''
    expect(text).toMatch(/counts unavailable/i)
    expect(text).toContain('_closed')
    expect(text).toMatch(/unknown, not zero/i)
  })

  it('CONTROL: says nothing of the sort when the counts were measured', async () => {
    getStatus.mockReturnValue(MEASURED)
    await mount()

    expect(document.body.textContent).toContain('3W · 2L')
    expect(document.body.textContent).not.toMatch(/counts unavailable/i)
  })
})
