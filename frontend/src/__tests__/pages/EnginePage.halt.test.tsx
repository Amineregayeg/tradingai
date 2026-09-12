/**
 * T-0141 — the Engine page must say the run is HALTED, and why.
 *
 * **The second of `M-6`'s two consumers, and the one an operator opens on purpose.** `EnginePanel`
 * carries the dot; this page carries the controls. A `B413` halt leaves `running: true` and
 * `paused: false`, so before this the page rendered **Pause and Stop, enabled, with nothing
 * saying the engine had already stopped taking entries** — an operator would press Pause on an
 * engine that was not running and read the absence of trades as a quiet market.
 *
 * The banner also has to say the thing that is NOT true of a pause: this state does not clear on
 * Stop or on a new run, because what it reports is at the venue rather than in the engine.
 *
 * No assertion reads the component's source.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const status = vi.fn()

vi.mock('@/services/api', () => ({
  authHeaders: () => ({}),
  api: {
    engine: {
      status: () => status(),
      sim: () => Promise.resolve(null),
      decisions: () => Promise.resolve([]),
      feedback: () => Promise.resolve(null),
      runs: () => Promise.resolve([]),
      start: () => Promise.resolve({}),
      stop: () => Promise.resolve({}),
      pause: () => Promise.resolve({}),
      resume: () => Promise.resolve({}),
    },
  },
}))

import EnginePage from '@/pages/EnginePage'

const RUNNING = {
  running: true,
  paused: false,
  mode: 'PAPER',
  symbols: ['BTC/USD'],
  activity: [],
  config: { symbols: ['BTC/USD'] },
}

const HALT = 'a partial fill left a position we could not size'

describe('T-0141 — the Engine page surfaces a halt and its reason', () => {
  beforeEach(() => {
    status.mockReset()
  })

  it('CONTROL: a running engine shows NO halt banner, so the arms below are not vacuous', async () => {
    status.mockResolvedValue(RUNNING)
    render(<EnginePage />)

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Engine' })).toBeTruthy())
    // POSITIVE FIRST. An arm whose only assertion is an absence passes over a page that rendered
    // nothing at all — so this pins that the running controls ARE on screen, and only then that
    // no halt banner is.
    expect(screen.getByRole('button', { name: 'Pause' })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('names the halt AND its reason when the engine has halted itself', async () => {
    status.mockResolvedValue({ ...RUNNING, halt_reason: HALT })
    render(<EnginePage />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('HALTED')
    expect(alert.textContent).toContain(HALT)
  })

  it('says it is NOT a pause — a halt that reads like one invites the wrong remedy', async () => {
    status.mockResolvedValue({ ...RUNNING, halt_reason: HALT })
    render(<EnginePage />)

    const alert = await screen.findByRole('alert')
    // The operator's next action depends on this: Pause/Resume does not clear it, and neither
    // does Stop, because the condition is at the venue.
    expect(alert.textContent).toMatch(/not a pause/i)
  })

  it('an operator PAUSE shows no halt banner — the two states stay distinct on screen', async () => {
    status.mockResolvedValue({ ...RUNNING, paused: true })
    render(<EnginePage />)

    await waitFor(() => expect(screen.getByRole('heading', { name: 'Engine' })).toBeTruthy())
    // The POSITIVE half: a paused engine offers Resume. Without it this arm is satisfied by a
    // page that failed to render, which is the same reading as "no halt banner".
    expect(screen.getByRole('button', { name: 'Resume' })).toBeTruthy()
    expect(screen.queryByRole('alert')).toBeNull()
  })

  it('T-0143: says when the halt\'s DURABLE RECORD could not be written', async () => {
    // M-6's consumer. A log line rotates; this page is where the operator already is, BECAUSE of
    // the halt. So the second fact — the record is missing — arrives where the first one sent them.
    status.mockResolvedValue({
      ...RUNNING,
      halt_reason: HALT,
      halt_record_failed:
        'the halt is IN FORCE but its durable record could not be written (alert: OperationalError)'
        + ' — reconcile the position at the venue by hand',
    })
    render(<EnginePage />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain('RECORD IS MISSING')
    expect(alert.textContent).toMatch(/reconcile/i)
    // and the halt itself is still reported — the record failing does not replace the halt
    expect(alert.textContent).toContain(HALT)
  })

  it('says NOTHING about a missing record when the writes succeeded', async () => {
    // The control: a line that is always present reports nothing. Without this the arm above is
    // satisfied by hard-coded text.
    status.mockResolvedValue({ ...RUNNING, halt_reason: HALT, halt_record_failed: null })
    render(<EnginePage />)

    const alert = await screen.findByRole('alert')
    expect(alert.textContent).toContain(HALT)
    expect(alert.textContent).not.toContain('RECORD IS MISSING')
  })
})
