import { useState, useEffect } from 'react'
import { api } from '@/services/api'

interface EconomicEvent {
  time: string
  currency: string
  impact: 'high' | 'medium' | 'low'
  event: string
  forecast?: string | null
  previous?: string | null
}

const IMPACT_COLORS = {
  high: '#ff3b5c',
  medium: '#f59e0b',
  low: '#4f8fff',
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
    fetch('/api/calendar/today')
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
                { label: `${events.length} Total Events`, color: '#4f8fff', bg: 'rgba(79,143,255,0.1)' },
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
                {['high', 'medium', 'low'].map((impact) => {
                  const filtered = events.filter((e) => e.impact === impact)
                  if (filtered.length === 0) return null
                  return (
                    <div key={impact}>
                      <div style={{
                        padding: '8px 18px', background: '#0d0d14', borderBottom: '1px solid #1e2035',
                        fontSize: 9, fontWeight: 700, letterSpacing: '0.1em',
                        color: IMPACT_COLORS[impact as keyof typeof IMPACT_COLORS],
                      }}>
                        {impact.toUpperCase()} IMPACT
                      </div>
                      {filtered.map((ev, i) => (
                        <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 14, padding: '12px 18px', borderBottom: '1px solid #13131e' }}>
                          <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: '#55556a', minWidth: 70 }}>{fmt(ev.time)}</span>
                          <span style={{ fontSize: 14 }}>{FLAGS[ev.currency] ?? ''}</span>
                          <span style={{ fontSize: 11, fontWeight: 700, color: '#8888a0', minWidth: 28 }}>{ev.currency}</span>
                          <span style={{ flex: 1, fontSize: 12, color: '#e8e8ef' }}>{ev.event}</span>
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
