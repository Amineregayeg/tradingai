/**
 * T-0141 — a HALTED engine must not read as a LIVE one, and the reason must be on the screen.
 *
 * **THIS IS `M-6`'s CONSUMER, and it is the one that matters.** The kill set says a reason stored
 * where nothing reads it is `B394`, and that the arm must assert a consumer changes behaviour
 * rather than that a field exists. `status()` carrying `halt_reason` is necessary and is not that
 * consumer — **the operator's green dot is.**
 *
 * `EnginePanel` computed `live = running && !paused`. A `B413` halt leaves `running: true` and
 * `paused: false`, so the dot went on **pulsing green over an engine that would never take
 * another entry.** That is `B179`'s shape — *the flag is off* rendering as *it works and there was
 * nothing to do* — and it is worse here, because the thing it hides is a position at the venue
 * that we could not size.
 *
 * No assertion reads the component's source. The panel is rendered and the screen is read.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const fetchMock = vi.fn()

vi.stubGlobal('fetch', fetchMock)
vi.mock('@/services/api', () => ({ authHeaders: () => ({}) }))
vi.mock('@/services/ws', () => ({
  wsService: { subscribe: () => () => {}, on: () => () => {}, off: () => {} },
}))

import { EnginePanel } from '@/components/dashboard/EnginePanel'

const BASE = {
  running: true,
  paused: false,
  mode: 'PAPER',
  symbols: ['BTC/USD', 'ETH/USD'],
  equity: 10_000,
  balance: 10_000,
  total_pnl: 0,
  total_pnl_pct: 0,
  win_rate: 0,
  closed_trades: 0,
  wins: 0,
  losses: 0,
  open_positions: 0,
  risk_pct: 0.01,
  entry_tf: '1h',
}

const HALT = 'a partial fill left a position we could not size'

function serve(status: Record<string, unknown>) {
  fetchMock.mockImplementation(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(status) }),
  )
}

/** The pulsing dot, found by the class the component uses for "live" rather than by colour. */
function pulsingDots(container: HTMLElement) {
  return container.querySelectorAll('.pulse-dot')
}

describe('T-0141 — a halted engine does not render as live', () => {
  beforeEach(() => {
    fetchMock.mockReset()
  })

  it('CONTROL: a genuinely running engine DOES pulse, so the arms below are not vacuous', async () => {
    serve(BASE)
    const { container } = render(<EnginePanel />)

    await waitFor(() => expect(screen.getByText('LIVE ENGINE')).toBeTruthy())
    expect(pulsingDots(container).length).toBe(1)
  })

  it('stops pulsing when the engine is HALTED, even though running is true and paused is false', async () => {
    serve({ ...BASE, halt_reason: HALT })
    const { container } = render(<EnginePanel />)

    await waitFor(() => expect(screen.getByText('LIVE ENGINE')).toBeTruthy())
    expect(pulsingDots(container).length).toBe(0)
  })

  it('puts the REASON on the screen, not merely the state', async () => {
    serve({ ...BASE, halt_reason: HALT })
    render(<EnginePanel />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain(HALT)
  })

  it('shows NO alert when nothing has halted — a banner that is always there reports nothing', async () => {
    serve(BASE)
    render(<EnginePanel />)

    await waitFor(() => expect(screen.getByText('LIVE ENGINE')).toBeTruthy())
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('distinguishes a HALT from an operator PAUSE on the screen', async () => {
    // Both stop trading. Only one of them is something the operator did, and only one of them
    // means a position may exist that we could not size — `M-7`, at the surface.
    serve({ ...BASE, paused: true })
    const { unmount } = render(<EnginePanel />)
    await waitFor(() => expect(screen.getByText('LIVE ENGINE')).toBeTruthy())
    const pausedAlert = screen.queryByRole('alert')
    unmount()

    serve({ ...BASE, halt_reason: HALT })
    render(<EnginePanel />)
    const haltedAlert = await screen.findByRole('alert')

    expect(pausedAlert).toBeNull()
    expect(haltedAlert.textContent).toContain(HALT)
  })

  it('a status with NO halt_reason key at all is treated as not halted', async () => {
    // The backend field is optional in the type, and an older backend will not send it. Absence
    // must read as "not halted" here — unlike on the backend, where absence of a FILLED quantity
    // is the alarming state. The difference is that this surface cannot cause a trade.
    const { halt_reason: _omit, ...withoutKey } = { ...BASE, halt_reason: undefined }
    serve(withoutKey)
    const { container } = render(<EnginePanel />)

    await waitFor(() => expect(screen.getByText('LIVE ENGINE')).toBeTruthy())
    expect(pulsingDots(container).length).toBe(1)
    expect(screen.queryByRole('alert')).toBeNull()
  })
})
