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

function colourFor(status: string): string {
  if (status === 'healthy') return GREEN
  if (status === 'stale' || status === 'unavailable') return AMBER
  return RED // down, failing
}

function Component({ name, health }: { name: string; health: ComponentHealth }) {
  const colour = colourFor(health.status)
  const detail =
    health.status === 'unavailable'
      ? 'not being watched'
      : name === 'Collector'
        ? `${health.age_minutes?.toFixed(0)}m ago · ${health.recent_density_pct?.toFixed(0)}% of last hour`
        : `${health.age_hours?.toFixed(0)}h ago · ${health.backup_count ?? '—'} kept`

  return (
    <div style={{ padding: '5px 0', borderTop: '1px solid #1a1a26' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
        <div style={{ width: 7, height: 7, borderRadius: '50%', background: colour, flex: '0 0 auto' }} />
        <span style={{ fontSize: 11, color: '#e8e8ef' }}>{name}</span>
        <span style={{ fontSize: 10, color: colour, marginLeft: 'auto', textTransform: 'uppercase' }}>
          {health.status}
        </span>
      </div>
      <div style={{ fontSize: 10, color: MUTED, marginLeft: 14, marginTop: 1 }}>{detail}</div>
      {/* The warning says WHY it is urgent, not just that it happened — for the
          collector, that the loss is permanent. */}
      {health.warning && (
        <div style={{ fontSize: 10, color: colour, marginLeft: 14, marginTop: 3, lineHeight: 1.45 }}>
          {health.warning}
        </div>
      )}
      {health.reason && !health.warning && (
        <div style={{ fontSize: 10, color: MUTED, marginLeft: 14, marginTop: 3, lineHeight: 1.45 }}>
          {health.reason}
        </div>
      )}
    </div>
  )
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

  // Healthy: one quiet line. Anything louder trains people to ignore it.
  if (health.ok) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', gap: 7, marginBottom: 12 }}>
        <div style={{ width: 7, height: 7, borderRadius: '50%', background: GREEN }} />
        <span style={{ fontSize: 11, color: MUTED }}>
          Collector and backups healthy
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
      <Component name="Collector" health={health.dominance_collector} />
      <Component name="Backups" health={health.backups} />
    </div>
  )
}
