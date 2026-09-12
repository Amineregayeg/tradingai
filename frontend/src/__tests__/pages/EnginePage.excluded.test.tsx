/**
 * B425 — the records the analysis REFUSED must be visible on every branch of the feedback panel,
 * not only on the one where the engine has already stopped itself.
 *
 * **The backend half of `B425` was landing `excluded` counts on both of `analyze()`'s return
 * paths. This is the half that was one step short.** `abstain_reason` carries those counts and
 * renders on ONE of the panel's three branches, so:
 *
 * ```
 * abstained            -> abstain_reason renders, counts visible
 * no corrections       -> "the engine is tracking its expectations"   <- 60 rows dropped, unchanged
 * corrections proposed -> the corrections list                        <- 60 rows dropped, unchanged
 * ```
 *
 * The refusal was visible exactly when the engine had stopped acting and hidden on both branches
 * where it acts — **a surface that reads as health regardless of what went missing**, which is the
 * defect `B425` is about, one layer out from the classifier. Found by the review seat against the
 * execute seat's claim that the counts reached the screen with no frontend change: true of the
 * line, false of the branch it sits on.
 *
 * **ABSENT AND EMPTY ARE DIFFERENT ANSWERS.** `{}` is the backend saying it counted and found
 * none. A missing key is a build that cannot tell you. They must not render the same, or the
 * panel re-enacts the default-reads-as-health bug it exists to report.
 *
 * No assertion reads the component's source.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'

const feedback = vi.fn()

vi.mock('@/services/api', () => ({
  authHeaders: () => ({}),
  api: {
    engine: {
      status: () => Promise.resolve({
        running: true, paused: false, mode: 'PAPER',
        symbols: ['BTC/USD'], activity: [], config: { symbols: ['BTC/USD'] },
      }),
      sim: () => Promise.resolve(null),
      decisions: () => Promise.resolve([]),
      feedback: () => feedback(),
      runs: () => Promise.resolve([]),
      start: () => Promise.resolve({}),
      stop: () => Promise.resolve({}),
      pause: () => Promise.resolve({}),
      resume: () => Promise.resolve({}),
    },
  },
}))

import EnginePage from '@/pages/EnginePage'

/** The branch that prints an affirmatively reassuring sentence. */
const TRACKING = 'No corrections proposed — the engine is tracking its expectations.'

const base = {
  n: 40,
  expected_vs_actual: { mean_realized_r: 0.4, mean_winner_realized_r: 2.1 },
  gaps: {},
  corrections: [],
  abstained: false,
  abstain_reason: null,
}

async function mounted() {
  render(<EnginePage />)
  await waitFor(() => expect(screen.getByRole('heading', { name: 'Engine' })).toBeTruthy())
}

describe('B425 — refused records are visible on every branch', () => {
  beforeEach(() => {
    feedback.mockReset()
  })

  it('CONTROL: with nothing excluded the panel says so by saying NOTHING, and still renders the branch', async () => {
    feedback.mockResolvedValue({ ...base, excluded: {} })
    await mounted()

    // POSITIVE FIRST. An arm whose only assertion is an absence passes over a page that failed
    // to render the panel at all.
    await waitFor(() => expect(screen.getByText(TRACKING)).toBeTruthy())
    expect(screen.queryByText(/excluded from the evidence/i)).toBeNull()
    expect(screen.queryByText(/cannot report/i)).toBeNull()
  })

  it('THE BRANCH THAT WAS BLIND: exclusions show even while the engine says it is tracking', async () => {
    feedback.mockResolvedValue({ ...base, excluded: { unrecognised: 60 } })
    await mounted()

    await waitFor(() => expect(screen.getByText(TRACKING)).toBeTruthy())
    const line = screen.getByText(/excluded from the evidence/i)
    expect(line.textContent).toContain('60')
    expect(line.textContent).toContain('unrecognised=60')
  })

  it('THE OTHER BLIND BRANCH: exclusions show alongside proposed corrections', async () => {
    feedback.mockResolvedValue({
      ...base,
      corrections: [{ target_param: 'rr_partial', current: 2, proposed: 1.8, evidence_n: 40, confidence: 0.7, rationale: 'winners short of target' }],
      excluded: { rejected: 4, unsized_fill: 3 },
    })
    await mounted()

    await waitFor(() => expect(screen.getByText(/rr_partial/)).toBeTruthy())
    const line = screen.getByText(/excluded from the evidence/i)
    expect(line.textContent).toContain('rejected=4')
    expect(line.textContent).toContain('unsized_fill=3')
    expect(line.textContent).toContain('7 record(s)')
  })

  it('and on the abstained branch, where it was already visible, it is not lost', async () => {
    feedback.mockResolvedValue({
      ...base,
      n: 4,
      abstained: true,
      abstain_reason: 'insufficient evidence: 4 closed record(s) < min_evidence=30; no confident correction on thin data. Excluded 60 record(s): unrecognised=60.',
      excluded: { unrecognised: 60 },
    })
    await mounted()

    await waitFor(() => expect(screen.getByText(/insufficient evidence/i)).toBeTruthy())
    expect(screen.getByText(/excluded from the evidence/i).textContent).toContain('unrecognised=60')
  })

  it('ABSENT is not EMPTY: a backend that cannot report exclusions must not look like one reporting none', async () => {
    feedback.mockResolvedValue({ ...base })   // no `excluded` key at all
    await mounted()

    await waitFor(() => expect(screen.getByText(/cannot report/i)).toBeTruthy())
    expect(screen.queryByText(/excluded from the evidence/i)).toBeNull()
  })

  it('THE DISCRIMINATION, driven: {} and a missing key render DIFFERENT text', async () => {
    feedback.mockResolvedValue({ ...base, excluded: {} })
    const { unmount } = render(<EnginePage />)
    await waitFor(() => expect(screen.getByText(TRACKING)).toBeTruthy())
    const withEmpty = document.body.textContent ?? ''
    unmount()

    feedback.mockResolvedValue({ ...base })
    await mounted()
    await waitFor(() => expect(screen.getByText(/cannot report/i)).toBeTruthy())
    const withAbsent = document.body.textContent ?? ''

    expect(withEmpty).not.toEqual(withAbsent)
    expect(withEmpty).not.toMatch(/cannot report/i)
  })
})
