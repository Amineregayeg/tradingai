import { useEffect, useState } from 'react'
import { api } from '@/services/api'
import type { ComponentHealth, DataHealth } from '@/types/api'

/**
 * The systems that fail silently — the dominance collector and backups.
 *
 * WHY THIS PANEL EXISTS
 * Both can die without anyone noticing, and the collector's data is
 * UNRECOVERABLE: no source sells intraday dominance history, so it exists only
 * because something was recording at the time. Its container went unhealthy
 * within ten minutes of any stoppage, but nothing read that healthcheck — so a
 * quiet death would cost days that no later fix retrieves.
 *
 * THE DISPLAY RULE
 * When everything is healthy this renders a single quiet line. It only grows
 * when something is wrong. A panel that shouts constantly gets ignored, and
 * then it is not a monitor — it is decoration.
 *
 * "unavailable" is styled as a PROBLEM, not as an absence of news: it means the
 * backend could not read that component at all, i.e. nothing is watching it.
 */

const GREEN = '#00d68f'
const RED = '#ff3b5c'
const AMBER = '#e3b341'
const MUTED = '#55556a'

/**
 * Every status the backend actually emits, and what it means for a reader.
 *
 * `B234`: the catch-all used to be commented `// down, failing` — NEITHER of which the
 * backend emits — while silently absorbing four that do: `withdrawn`, `idle`, `thin` and
 * `not_applicable`. A comment naming the cases it does not handle, over a branch swallowing
 * the ones it does.
 *
 * `B229`/`B234`: **`idle` and `withdrawn` must not be the same colour.** They are precisely
 * the two states the `ok` question is about — an engine deliberately stopped, versus an
 * engine running and unable to trade — and folding them together makes the flag unreadable
 * whichever way that question is answered.
 */
const STATUS_COLOUR: Record<string, string> = {
  healthy: GREEN,
  idle: MUTED,            // nothing is DUE. Not a problem, and not health either.
  not_applicable: MUTED,  // this check does not apply here
  stale: AMBER,
  thin: AMBER,
  unavailable: AMBER,     // we cannot SEE it — never styled as an absence of news
  withdrawn: RED,         // running, and unable to trade
  down: RED,
  failing: RED,
}

function colourFor(status: string): string {
  // An unknown status is AMBER, never green: a status this panel has not been taught is a
  // thing it cannot vouch for, and defaulting to green is how a screen reassures about
  // something it stopped understanding.
  return STATUS_COLOUR[status] ?? AMBER
}

function Component({ name, health }: { name: string; health: ComponentHealth }) {
  const colour = colourFor(health.status)

  return (
    <div style={{ padding: '5px 0', borderTop: '1px solid #1a1a26' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
        <div style={{ width: 7, height: 7, borderRadius: '50%', background: colour, flex: '0 0 auto' }} />
        <span style={{ fontSize: 11, color: '#e8e8ef' }}>{name}</span>
        <span style={{ fontSize: 10, color: colour, marginLeft: 'auto', textTransform: 'uppercase' }}>
          {health.status}
        </span>
      </div>
      {/* THE COMPONENT'S OWN SENTENCE. This used to be built here, by branching on the
          component's NAME — `name === 'Collector' ? age_minutes... : age_hours...` — which
          is why a third component could not be rendered at all. */}
      {health.summary && (
        <div style={{ fontSize: 10, color: MUTED, marginLeft: 14, marginTop: 1 }}>
          {health.summary}
        </div>
      )}
      {/* The warning says WHY it is urgent, not just that it happened — for the
          collector, that the loss is permanent. */}
      {health.warning && (
        <div style={{ fontSize: 10, color: colour, marginLeft: 14, marginTop: 3, lineHeight: 1.45 }}>
          {health.warning}
        </div>
      )}
    </div>
  )
}

/** `dominance_collector` -> `Dominance collector`. The key is the name; nothing is hardcoded. */
function labelFor(key: string): string {
  const spaced = key.replace(/_/g, ' ')
  return spaced.charAt(0).toUpperCase() + spaced.slice(1)
}

export function DataHealthPanel() {
  const [health, setHealth] = useState<DataHealth | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    const load = () =>
      api.system
        .dataHealth()
        .then((r) => { if (alive) { setHealth(r); setFailed(false) } })
        .catch(() => { if (alive) setFailed(true) })
    load()
    // 60s: the collector samples once a minute, so checking faster tells you
    // nothing new.
    const id = setInterval(load, 60_000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  if (failed) {
    return (
      <div style={{ fontSize: 11, color: AMBER, marginBottom: 12 }}>
        Data health unavailable — the API did not respond.
      </div>
    )
  }
  if (!health) return null

  const components = Object.entries(health.components ?? {})

  // Healthy: one quiet line. Anything louder trains people to ignore it.
  //
  // COUNTED, NOT NAMED. This said "Collector and backups healthy" while five components had
  // been checked — a claim narrower than the check that produced it, which reads as a
  // reassurance about the two it names and silently covers three it does not.
  if (health.ok) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 12 }}>
        <div style={{ width: 7, height: 7, borderRadius: '50%', background: GREEN }} />
        <span style={{ fontSize: 11, color: MUTED }}>
          {components.length} component{components.length === 1 ? '' : 's'} healthy
        </span>
      </div>
    )
  }

  return (
    <div style={{
      background: '#12121a', border: `1px solid ${RED}44`, borderRadius: 9,
      padding: '10px 12px', marginBottom: 12,
    }}>
      <div style={{
        fontSize: 10, color: RED, fontWeight: 700, letterSpacing: '0.07em',
        textTransform: 'uppercase', marginBottom: 4,
      }}>
        Data health — {health.problems.length} problem{health.problems.length === 1 ? '' : 's'}
      </div>
      {/* EVERY component, derived from the payload. A sixth appears here with ZERO change
          to this file — which is the whole of B231's fix. */}
      {components.map(([key, component]) => (
        <Component key={key} name={labelFor(key)} health={component} />
      ))}
    </div>
  )
}
