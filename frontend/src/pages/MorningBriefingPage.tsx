import { useState, useEffect } from 'react'
import { api, authHeaders } from '@/services/api'

interface EconomicEvent {
  time: string
  currency: string
  // DELIBERATELY `string`, not a union. This is parsed JSON from a live API with no runtime
  // validation, so a union here is a compile-time claim about data the compiler never sees —
  // it constrains nothing at runtime while pushing every repair toward widening the union by
  // one more literal. The grouping below derives its buckets from the values actually
  // present, so an impact this file has never heard of still renders.
  impact: string
  event: string
  forecast?: string | null
  previous?: string | null
  // The provider's own string when it did not resolve. null means nothing was sent to keep.
  impact_raw?: string | null
}

// The severities this UI has a designed appearance for, in display order.
const KNOWN_IMPACTS = ['high', 'medium', 'low'] as const
type KnownImpact = (typeof KNOWN_IMPACTS)[number]

const IMPACT_COLORS: Record<KnownImpact, string> = {
  high: '#ff3b5c',
  medium: '#f59e0b',
  low: '#4f8fff',
}

// Everything the known set does not cover. `unknown` is what the backend emits today; the
// point of the residual bucket is that it is NOT a fourth literal.
const UNRECOGNISED_COLOR = '#a855f7'

// An explicit fallback rather than `IMPACT_COLORS[k as keyof typeof IMPACT_COLORS]`.
// THAT CAST DEFEATS THE COMPILER EXACTLY WHERE IT WOULD OTHERWISE CATCH A MISSING KEY:
// with a widened union and an un-widened colour map it type-checks and returns `undefined`
// at runtime, so the events render with no colour. That is the same fail-open as the one
// this task is closing, one layer down, and it compiles clean.
function impactColor(key: string): string {
  return (IMPACT_COLORS as Record<string, string>)[key] ?? UNRECOGNISED_COLOR
}

// GROUP FROM THE DATA, NOT FROM A LIST. An enumeration is a claim about its complement, and
// this one has already been wrong once: `['high','medium','low']` silently dropped every
// event whose impact was outside it, while the "No economic events today" message stayed
// hidden behind `events.length === 0`. Deriving the residual bucket makes rendering-nowhere
// unrepresentable rather than merely fixed for today's fourth value.
function groupByImpact(events: EconomicEvent[]) {
  const known = new Set<string>(KNOWN_IMPACTS)
  const residual = Array.from(new Set(events.map((e) => e.impact).filter((i) => !known.has(i)))).sort()
  // Residual first: an event the provider did not classify is the one a human must look at.
  return [...residual, ...KNOWN_IMPACTS]
    .map((key) => ({ key, isKnown: known.has(key), rows: events.filter((e) => e.impact === key) }))
    .filter((g) => g.rows.length > 0)
}

// Currency → flag emoji map
const FLAGS: Record<string, string> = {
  USD: '🇺🇸', EUR: '🇪🇺', GBP: '🇬🇧', JPY: '🇯🇵',
  AUD: '🇦🇺', CAD: '🇨🇦', NZD: '🇳🇿', CHF: '🇨🇭',
}

function fmt(iso: string) {
  try {
    return new Date(iso).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'UTC' }) + ' GMT'
  } catch { return iso }
}

export default function MorningBriefingPage() {
  const [events, setEvents] = useState<EconomicEvent[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // Try to fetch calendar from backend
    setIsLoading(true)
    fetch('/api/calendar/today', { headers: authHeaders() })
      .then((r) => {
        if (!r.ok) throw new Error(`${r.status}`)
        return r.json()
      })
      .then((data: EconomicEvent[]) => {
        setEvents(Array.isArray(data) ? data : [])
        setIsLoading(false)
      })
      .catch((e) => {
        setError(e.message === '404' ? 'no_endpoint' : 'no_key')
        setIsLoading(false)
      })

    // Also load user settings to get session info
    api.settings.get().catch(() => {})
  }, [])

  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })
  const highImpact = events.filter((e) => e.impact === 'high')
  const medImpact = events.filter((e) => e.impact === 'medium')
  const groups = groupByImpact(events)

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: '#0a0a0f' }}>
      {/* Header */}
      <div style={{ padding: '16px 24px 12px', borderBottom: '1px solid #1e2035', background: '#0d0d14', flexShrink: 0 }}>
        <h1 style={{ fontSize: 18, fontWeight: 700, color: '#e8e8ef', marginBottom: 2 }}>Morning Briefing</h1>
        <span style={{ fontSize: 12, color: '#55556a' }}>{today}</span>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
        {isLoading ? (
          <div style={{ textAlign: 'center', color: '#55556a', padding: 40 }}>Loading economic calendar…</div>
        ) : error ? (
          <div style={{ maxWidth: 520, margin: '40px auto' }}>
            {/* No Finnhub key — explain what to add */}
            <div style={{ background: '#12121a', border: '1px solid #1e2035', borderRadius: 12, padding: '32px 28px' }}>
              <div style={{ fontSize: 28, marginBottom: 16, textAlign: 'center' }}>📅</div>
              <h2 style={{ fontSize: 16, fontWeight: 700, color: '#e8e8ef', marginBottom: 8, textAlign: 'center' }}>Economic Calendar</h2>
              <p style={{ fontSize: 13, color: '#55556a', lineHeight: 1.7, marginBottom: 20, textAlign: 'center' }}>
                The economic calendar requires a <strong style={{ color: '#e8e8ef' }}>Finnhub API key</strong>.<br />
                Add it to your <code style={{ background: '#1a1a26', padding: '2px 6px', borderRadius: 4 }}>.env</code> file to enable high-impact news tracking.
              </p>
              <div style={{ background: '#0d0d14', borderRadius: 8, padding: '14px 16px', fontFamily: 'var(--font-mono)', fontSize: 12, color: '#8888a0', marginBottom: 20 }}>
                FINNHUB_API_KEY=your_key_here
              </div>
              <p style={{ fontSize: 11, color: '#3a3a50', textAlign: 'center' }}>
                Free tier at finnhub.io — 60 calls/min, no credit card required.
              </p>
            </div>

            {/* Static session plan as fallback */}
            <div style={{ marginTop: 24, background: '#12121a', border: '1px solid #1e2035', borderRadius: 12, padding: '20px 24px' }}>
              <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', color: '#55556a', marginBottom: 14 }}>TODAY'S SESSION PLAN</div>
              {[
                { time: '07:00 GMT', session: 'London Open', color: '#f59e0b', pairs: 'GBP/USD · EUR/USD · XAU/USD' },
                { time: '08:30 GMT', session: 'London Kill Zone', color: '#ff3b5c', pairs: 'GBP/USD · EUR/GBP' },
                { time: '12:00 GMT', session: 'London–NY Overlap', color: '#a78bfa', pairs: 'EUR/USD · GBP/USD · XAU/USD' },
                { time: '13:30 GMT', session: 'New York Kill Zone', color: '#ff3b5c', pairs: 'EUR/USD · USD/JPY · XAU/USD' },
                { time: '16:00 GMT', session: 'NY Afternoon Session', color: '#4f8fff', pairs: 'USD pairs · Gold' },
              ].map((s) => (
                <div key={s.time} style={{ display: 'flex', gap: 14, marginBottom: 12, alignItems: 'flex-start' }}>
                  <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: '#55556a', minWidth: 70, paddingTop: 2 }}>{s.time}</span>
                  <div>
                    <div style={{ fontSize: 12, fontWeight: 600, color: s.color, marginBottom: 2 }}>{s.session}</div>
                    <div style={{ fontSize: 11, color: '#55556a' }}>{s.pairs}</div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : (
          <>
            {/* Summary pills */}
            <div style={{ display: 'flex', gap: 10, marginBottom: 24, flexWrap: 'wrap' }}>
              {[
                { label: `${highImpact.length} High Impact`, color: '#ff3b5c', bg: 'rgba(255,59,92,0.1)' },
                { label: `${medImpact.length} Medium Impact`, color: '#f59e0b', bg: 'rgba(245,158,11,0.1)' },
                // DERIVED FROM WHAT IS RENDERED, not from events.length. If a bucket ever
                // dropped rows again, the old pill would have disagreed with the list below
                // it and named no member. Now the two cannot disagree.
                { label: `${groups.reduce((n, g) => n + g.rows.length, 0)} Total Events`, color: '#4f8fff', bg: 'rgba(79,143,255,0.1)' },
              ].map((p) => (
                <div key={p.label} style={{ padding: '6px 14px', borderRadius: 20, background: p.bg, color: p.color, fontSize: 12, fontWeight: 600 }}>
                  {p.label}
                </div>
              ))}
            </div>

            {/* Events list */}
            {events.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 40, color: '#55556a', fontSize: 13 }}>No economic events today</div>
            ) : (
              <div style={{ background: '#12121a', border: '1px solid #1e2035', borderRadius: 12, overflow: 'hidden' }}>
                {groups.map(({ key: impact, isKnown, rows: filtered }) => {
                  return (
                    <div key={impact}>
                      <div style={{
                        padding: '8px 18px', background: '#0d0d14', borderBottom: '1px solid #1e2035',
                        fontSize: 9, fontWeight: 700, letterSpacing: '0.1em',
                        color: impactColor(impact),
                      }}>
                        {isKnown
                          ? `${impact.toUpperCase()} IMPACT`
                          : `NOT CLASSIFIED BY THE PROVIDER — "${impact}"`}
                      </div>
                      {filtered.map((ev, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 18px', borderBottom: '1px solid #13131e' }}>
                          <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: '#55556a', minWidth: 70 }}>{fmt(ev.time)}</span>
                          <span style={{ fontSize: 14 }}>{FLAGS[ev.currency] ?? ''}</span>
                          <span style={{ fontSize: 11, fontWeight: 700, color: '#8888a0', minWidth: 28 }}>{ev.currency}</span>
                          <span style={{ flex: 1, fontSize: 12, color: '#e8e8ef' }}>
                            {ev.event}
                            {/* Gated on !isKnown, NOT on `impact === 'unknown'`. A literal here
                                would be the same enumeration one member over: the header would
                                name `sev-9` while the provider's own string stayed hidden. */}
                            {!isKnown && ev.impact_raw && (
                              <span style={{ marginLeft: 8, fontSize: 10, fontFamily: 'var(--font-mono)', color: '#a855f7' }}>
                                sent: {ev.impact_raw}
                              </span>
                            )}
                          </span>
                          {ev.forecast && <span style={{ fontSize: 11, color: '#4f8fff', minWidth: 60, textAlign: 'right' }}>F: {ev.forecast}</span>}
                          {ev.previous && <span style={{ fontSize: 11, color: '#55556a', minWidth: 60, textAlign: 'right' }}>P: {ev.previous}</span>}
                        </div>
                      ))}
                    </div>
                  )
                })}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
