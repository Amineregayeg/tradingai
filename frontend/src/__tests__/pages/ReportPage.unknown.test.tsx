/**
 * B431 — the REPORT is the surface read as evidence, so a count nobody could compute must not
 * appear there as a count.
 *
 * `EnginePanel` was fixed first and this page was missed. It reads the same
 * `/api/engine/status` payload and had every one of the same defects, plus one the panel does not:
 *
 * ```
 * :157  {s.closed_trades} closed trades          -> "null closed trades"
 * :158  s.closed_trades < 200                    -> null < 200 is TRUE in JS, so the
 *                                                   small-sample verdict fired on an UNKNOWN count
 * :181  `${s.win_rate}%`  /  `${s.wins}W · ...`  -> "null%" / "nullW · nullL"
 * :182  String(s.closed_trades)                  -> "null"
 * :210  `${s.wins} / ${s.losses}`                -> "null / null"
 * ```
 *
 * **The banner is the worst of them.** It is the disclaimer that tells the reader how to weigh
 * everything below it, and it asserted *far below the 200 trades needed to tell an edge from
 * noise* about a sample size nobody had measured.
 *
 * **AND THE PAGE ALREADY CONTAINED THE LESSON.** `loadFailed` carries the comment *"An outage must
 * not render as 'no trades'"*, written for the `/api/trades` fetch **three lines above** the status
 * fetch that is read naively. Same file, same class, two sources, one defended — found by the
 * review seat after the execute seat fixed only the consumer it happened to be looking at.
 *
 * No assertion reads the component's source.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

vi.mock('@/services/api', () => ({ authHeaders: () => ({}) }))

import ReportPage from '@/pages/ReportPage'

const MEASURED = {
  running: true, mode: 'PAPER', equity: 51_000, balance: 51_000,
  starting_balance: 50_000, total_pnl: 1_000, total_pnl_pct: 2,
  win_rate: 60, closed_trades: 5, wins: 3, losses: 2,
  counts_unavailable: [] as string[],
  // Required by the page's header line — `s.symbols.join(' · ')` throws without it. A fixture
  // thin enough to crash the component tests nothing, and the crash reads as four failing arms.
  symbols: ['BTC/USD'], entry_tf: '1H', risk_pct: 0.01, started_at: null,
}

/** The ledger could not be read: every derived figure is absent, not zero. */
const UNKNOWN = {
  ...MEASURED,
  win_rate: null, closed_trades: null, wins: null, losses: null,
  counts_unavailable: ['_closed'],
}

let status: Record<string, unknown> = MEASURED

beforeEach(() => {
  status = MEASURED
  vi.stubGlobal('fetch', vi.fn((url: string) => {
    const body = String(url).includes('/api/trades') ? [] : status
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) })
  }))
})

async function mount() {
  render(<ReportPage />)
  await waitFor(() => expect(screen.getByText(/Live paper trading only/i)).toBeTruthy())
}

/** The whole banner, not just its bold lead.
 *
 * `getByText(/Live paper trading only/i)` matches the `<b>` element — the sample-size verdict and
 * the missing-source name are SIBLINGS of it, so reading that node's textContent silently drops
 * the half of the banner these arms are about. Scoped one level up, deliberately: scoping too
 * tightly is the same error as not scoping at all, in the other direction.
 */
function banner(): string {
  return screen.getByText(/Live paper trading only/i).closest('div')?.textContent ?? ''
}

describe('B431 — the report does not present unknown counts as counts', () => {
  it('CONTROL: measured counts render as numbers and the sample verdict applies', async () => {
    status = MEASURED
    await mount()

    // POSITIVE FIRST — an absence-only arm passes over a page that rendered nothing.
    expect(document.body.textContent).toContain('5 closed trades')
    expect(document.body.textContent).toMatch(/far below the 200 trades/i)
    expect(document.body.textContent).toContain('3W · 2L')
  })

  it('THE BANNER does not claim a sample size nobody measured', async () => {
    status = UNKNOWN
    await mount()

    const text = document.body.textContent ?? ''
    expect(text).toMatch(/UNAVAILABLE/i)
    expect(text).not.toMatch(/far below the 200 trades/i)
    expect(text).not.toMatch(/Sample size is adequate/i)
  })

  it('no metric renders the literal string "null"', async () => {
    status = UNKNOWN
    await mount()

    // The defect's own signature. `${null}` stringifies, so this is the exact text that shipped.
    expect(document.body.textContent).not.toMatch(/null/i)
  })

  it('and the two states DISCRIMINATE on the banner itself, not merely somewhere on the page',
    async () => {
      status = MEASURED
      const { unmount } = render(<ReportPage />)
      await waitFor(() => expect(screen.getByText(/Live paper trading only/i)).toBeTruthy())
      // **SCOPED.** An em-dash or "unavailable" assertion against the whole page is satisfied by
      // any of a dozen already-guarded metrics — a neighbouring defence answering for the
      // mechanism under test, which is how the EnginePanel version of this arm survived twice.
      const measured = screen.getByText(/Live paper trading only/i).textContent ?? ''
      unmount()

      status = UNKNOWN
      await mount()
      const unknown = screen.getByText(/Live paper trading only/i).textContent ?? ''

      expect(measured).toContain('5 closed')
      expect(unknown).toMatch(/UNAVAILABLE/i)
      expect(measured).not.toEqual(unknown)
    })
})

describe('B431 — the banner has THREE states and all three are asserted', () => {
  it('the ADEQUATE-sample branch still renders, and it costs one literal', async () => {
    // **MY REASON FOR SKIPPING THIS WAS WRONG IN MY OWN FAVOUR.** I said it would need 200+
    // trades; the banner reads a NUMBER from the payload, and this fixture supplies the payload
    // as a literal. Three-state logic with two states asserted is where the third silently
    // becomes unreachable — found by review reading the component rather than my excuse.
    status = { ...MEASURED, closed_trades: 250, wins: 150, losses: 100 }
    await mount()

    const text = banner()
    expect(text).toContain('250 closed trades')
    expect(text).toMatch(/Sample size is adequate/i)
    expect(text).not.toMatch(/far below/i)
    expect(text).not.toMatch(/UNAVAILABLE/i)
  })

  it('names the missing source rather than asserting a generic outage', async () => {
    status = UNKNOWN
    await mount()

    expect(banner()).toContain('_closed')
  })
})
