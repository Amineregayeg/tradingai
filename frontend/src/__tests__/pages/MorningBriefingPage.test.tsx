/**
 * T-0035 — an event the provider did not classify must be VISIBLE, not merely non-"low".
 *
 * THE FINDING THIS FILE EXISTS FOR, and it runs the opposite way to the usual one.
 * The backend fix stops coercing an unrecognised impact to "low". On its own that would have
 * made the event render in NO section: the bucket loop was `['high','medium','low'].map(...)`,
 * and the empty-state message is guarded by `events.length === 0`, which is false — so the
 * page would have drawn an empty bordered box and said nothing.
 *
 * Before T-0035 the event was VISIBLE AND MISLABELLED. A backend-only fix would have made it
 * INVISIBLE, which is strictly worse: "visible and wrong" at least gets looked at.
 *
 * So this asserts the RENDERED OUTPUT, not the source text. A guard that greps the JSX proves
 * the author read the file; only a render proves the user sees the row.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import MorningBriefingPage from '@/pages/MorningBriefingPage'

vi.mock('@/services/api', () => ({
  authHeaders: () => ({}),
  api: { settings: { get: () => Promise.resolve({}) } },
}))

const UNKNOWN_EVENT = {
  time: '2026-05-29T12:30:00+00:00',
  currency: 'USD',
  impact: 'unknown',
  event: 'Unclassified Release',
  forecast: null,
  previous: null,
  impact_raw: 'tier-1',
}

const HIGH_EVENT = {
  time: '2026-05-29T13:30:00+00:00',
  currency: 'EUR',
  impact: 'high',
  event: 'ECB Rate Decision',
  forecast: null,
  previous: null,
  impact_raw: 'high',
}

function serve(events: unknown[]) {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => Promise.resolve({ ok: true, json: () => Promise.resolve(events) })),
  )
}

beforeEach(() => {
  vi.clearAllMocks()
})
afterEach(() => {
  vi.unstubAllGlobals()
})

describe('MorningBriefingPage — the unknown-impact bucket', () => {
  it('MUST-FIRE ARM: an unknown-impact event appears in the rendered output', async () => {
    serve([UNKNOWN_EVENT])
    render(<MorningBriefingPage />)

    // The event itself, not just its section header — a header with no rows under it would
    // satisfy a laxer assertion while the user still sees nothing.
    expect(await screen.findByText('Unclassified Release')).toBeInTheDocument()
  })

  it('labels the section as NOT CLASSIFIED rather than as a severity', async () => {
    serve([UNKNOWN_EVENT])
    render(<MorningBriefingPage />)

    // "unknown" is the ABSENCE of a severity. A header reading "UNKNOWN IMPACT" alone would
    // read as a fourth tier below "low", which is a different and equally wrong claim. The
    // header also NAMES the value, so the reader learns what the provider actually sent.
    expect(await screen.findByText(/NOT CLASSIFIED BY THE PROVIDER — "unknown"/)).toBeInTheDocument()
  })

  it("shows the provider's own string so the reader can act on it", async () => {
    serve([UNKNOWN_EVENT])
    render(<MorningBriefingPage />)

    // One repeated value means our map is missing a tier; many distinct values mean the
    // provider's schema moved. Opposite fixes, and the count alone distinguishes neither.
    expect(await screen.findByText(/tier-1/)).toBeInTheDocument()
  })

  it('MUST-MISS ARM: it is not silently relabelled as low', async () => {
    serve([UNKNOWN_EVENT])
    render(<MorningBriefingPage />)
    await screen.findByText('Unclassified Release')

    expect(screen.queryByText(/^LOW IMPACT$/)).not.toBeInTheDocument()
  })

  it('CONTROL: the known tiers still render, so the change is additive', async () => {
    serve([UNKNOWN_EVENT, HIGH_EVENT])
    render(<MorningBriefingPage />)

    expect(await screen.findByText('ECB Rate Decision')).toBeInTheDocument()
    expect(await screen.findByText(/^HIGH IMPACT$/)).toBeInTheDocument()
    expect(await screen.findByText('Unclassified Release')).toBeInTheDocument()
  })

  it('A VALUE THIS FILE HAS NEVER HEARD OF STILL RENDERS — the buckets are derived', async () => {
    // THE ARM THAT SEPARATES A DERIVED GROUPING FROM AN ENUMERATED ONE.
    // `['high','medium','low','unknown']` would pass every other test here and fail this.
    // An enumeration is a claim about its complement, and this one has already been wrong
    // once — so the guard has to be a value no list in this repo mentions.
    serve([{ ...UNKNOWN_EVENT, impact: 'sev-9', impact_raw: 'sev-9', event: 'Novel Severity' }])
    render(<MorningBriefingPage />)

    expect(await screen.findByText('Novel Severity')).toBeInTheDocument()
    expect(await screen.findByText(/NOT CLASSIFIED BY THE PROVIDER — "sev-9"/)).toBeInTheDocument()
    // AND the raw badge, which was gated on `impact === 'unknown'` in the first draft — an
    // enumeration one member over, where the header named the value and the provider's own
    // string stayed hidden for every value except today's.
    expect(await screen.findByText(/sent: sev-9/)).toBeInTheDocument()
  })

  it('THE TOTAL PILL COUNTS WHAT WAS RENDERED, so it cannot disagree with the list', async () => {
    // The old pill read `events.length`. With a dropped bucket it counted rows that were not
    // on screen and named no member — a visible discrepancy with no attribution. Derived from
    // the groups, the two are the same number by construction.
    serve([UNKNOWN_EVENT, HIGH_EVENT, { ...HIGH_EVENT, impact: 'sev-9', event: 'Third' }])
    render(<MorningBriefingPage />)

    await screen.findByText('Unclassified Release')
    expect(screen.getByText('3 Total Events')).toBeInTheDocument()
    for (const name of ['Unclassified Release', 'ECB Rate Decision', 'Third']) {
      expect(screen.getByText(name)).toBeInTheDocument()
    }
  })

  it('MUST-MISS ARM: a known impact never lands in the residual bucket', async () => {
    serve([HIGH_EVENT])
    render(<MorningBriefingPage />)

    await screen.findByText('ECB Rate Decision')
    expect(screen.getByText(/^HIGH IMPACT$/)).toBeInTheDocument()
    expect(screen.queryByText(/NOT CLASSIFIED BY THE PROVIDER/)).not.toBeInTheDocument()
  })

  it('CONTROL: with no events at all the page SAYS so — the state a half fix imitated', async () => {
    serve([])
    render(<MorningBriefingPage />)

    // This is the message the empty-state guard shows. A backend-only fix produced a page
    // that looked empty WITHOUT this text, which is why "the page looked fine" would not
    // have caught it.
    await waitFor(() =>
      expect(screen.getByText(/No economic events today/i)).toBeInTheDocument(),
    )
  })
})
