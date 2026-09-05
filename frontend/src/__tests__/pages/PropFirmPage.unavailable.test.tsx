/**
 * B380 — an UNEVALUATED account must not render as a healthy one.
 *
 * **WHY THIS FILE EXISTS AND WHY MY FIRST WITNESS DID NOT COUNT.** B378's arm asserted
 * `rows[0].state is ComplianceState.UNAVAILABLE` **against the database** and called that the
 * surface. The row was written correctly and the consumer turned it back into a number:
 *
 *     StatusBadge       map[state] ?? {label: state}   -> "UNAVAILABLE"    honest
 *     Equity / Balance  value > 0 ? … : '—'            -> "—"              HONEST BY LUCK
 *     Drawdown bars     Number(null) === 0             -> "0.00%"          FABRICATED
 *
 * `Number(null)` is `0`, so an account the monitor could not evaluate rendered as one using **none
 * of its drawdown allowance** — the most reassuring reading available on a breach monitor, and now
 * carrying a current timestamp. **Stale healthy replaced by fresh healthy is worse.**
 *
 * **A fix whose whole subject is *absence must be visible* needs its witness driven from the layer
 * where the absence is READ** — the same standard I set on B369 when I drove the form instead of
 * reading the component, and then failed here.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const UNEVALUATED = {
  profile_id: 'p1',
  firm_name: 'Crypto Fund Trader',
  state: 'UNAVAILABLE',
  equity: null,
  balance: null,
  daily_loss: null,
  total_loss: null,
  daily_loss_limit_pct: 5,
  total_loss_limit_pct: 10,
  timestamp: '2026-09-05T14:00:00Z',
}

const HEALTHY = {
  ...UNEVALUATED,
  state: 'ACTIVE',
  equity: 5012, balance: 5000, daily_loss: 0, total_loss: 12,
}

let statuses: unknown[] = []

vi.mock('@/services/api', () => ({
  authHeaders: () => ({}),
  api: {
    propFirm: {
      status: () => Promise.resolve(statuses),
      profiles: () => Promise.resolve([]),
      list: () => Promise.resolve([]),
    },
    settings: { get: () => Promise.resolve({}) },
  },
}))

import PropFirmPage from '@/pages/PropFirmPage'

describe('B380 — the compliance surface must show absence as absence', () => {
  beforeEach(() => { statuses = [] })

  it('does NOT render a drawdown percentage for an unevaluated account', async () => {
    statuses = [UNEVALUATED]
    render(<PropFirmPage />)

    await waitFor(() => expect(screen.getByText(/Crypto Fund Trader/)).toBeTruthy())

    // THE DEFECT, STATED AS AN ASSERTION: a null loss became 0 and the bar read "0.00%".
    expect(screen.queryByText(/0\.00%/)).toBeNull()
    const bars = screen.getAllByText(/NOT EVALUATED/)
    expect(bars.length).toBeGreaterThanOrEqual(2)
  })

  it('shows the state itself rather than a healthy-looking one', async () => {
    statuses = [UNEVALUATED]
    render(<PropFirmPage />)
    await waitFor(() => expect(screen.getByText('UNAVAILABLE')).toBeTruthy())
  })

  it('shows a dash for figures it does not have, by DECISION and not by truthiness', async () => {
    statuses = [UNEVALUATED]
    render(<PropFirmPage />)
    await waitFor(() => expect(screen.getByTestId('figure-Equity')).toBeTruthy())
    expect(screen.getByTestId('figure-Equity').textContent).toBe('—')
    expect(screen.getByTestId('figure-Balance').textContent).toBe('—')
  })

  it('MUST-MISS: a real evaluation still renders its numbers and its bars', async () => {
    // Without this, "render nothing" satisfies every arm above and destroys the monitor.
    statuses = [HEALTHY]
    render(<PropFirmPage />)
    await waitFor(() => expect(screen.getByTestId('figure-Equity')).toBeTruthy())
    expect(screen.getByTestId('figure-Equity').textContent).toContain('5,012')
    expect(screen.queryByText(/NOT EVALUATED/)).toBeNull()
  })
})
