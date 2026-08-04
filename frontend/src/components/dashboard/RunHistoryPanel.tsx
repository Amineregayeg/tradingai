import { useEffect, useState } from 'react'
import { api } from '@/services/api'

/**
 * Past and present engine runs (task 2.5, closes KNOWN_ISSUES B6).
 *
 * WHY THIS EXISTS
 * Resetting the engine starts a new run and deletes nothing — but until this
 * panel there was no screen for the old ones, so pressing Reset sent every
 * number to zero with no visible route back to what had been there. The reset
 * was safe and did not LOOK safe, which is the impression the whole
 * scoped-runs design went to trouble to avoid.
 *
 * TWO HONESTY RULES, both inherited from what this project has already been
 * burned by:
 *
 * 1. Win rate is shown WITH its sample size, and marked when the sample is too
 *    small to mean anything. "50%" from four trades is noise, and presenting it
 *    with the same weight as a real figure is how a number nobody checked ends
 *    up driving a decision.
 * 2. Each run shows the SETTINGS it ran under. A result read against the wrong
 *    configuration is worse than no result — and comparing runs is the entire
 *    point of keeping them.
 */

const GREEN = '#00d68f'
const RED = '#ff3b5c'
const AMBER = '#e3b341'
const MUTED = '#55556a'

/** Tier 1 requires >= 200 closed trades before an edge is even measurable. */
const MEANINGFUL_SAMPLE = 200

interface Run {
  id: string
  started_at: string | null
  ended_at: string | null
  active: boolean
  label: string | null
  note: string | null
  config: Record<string, unknown> | null
  closed_trades: number
  realized_pnl: number
  wins: number
  decisions: number
  abstentions: number
}

function duration(run: Run): string {
  if (!run.started_at) return '—'
  const start = new Date(run.started_at).getTime()
  const end = run.ended_at ? new Date(run.ended_at).getTime() : Date.now()
  const hours = (end - start) / 3_600_000
  if (hours < 1) return `${Math.round(hours * 60)}m`
  if (hours < 48) return `${hours.toFixed(1)}h`
  return `${(hours / 24).toFixed(1)}d`
}

function settingsLine(cfg: Record<string, unknown> | null): string {
  if (!cfg) return 'settings not recorded'
  const risk = typeof cfg.risk_pct === 'number' ? `${(cfg.risk_pct * 100).toFixed(0)}% risk` : ''
  const syms = Array.isArray(cfg.symbols) ? (cfg.symbols as string[]).join(' · ') : ''
  return [syms, cfg.entry_tf, risk, cfg.mode, `prices: ${cfg.price_source ?? 'binance'}`]
    .filter(Boolean)
    .join('  ·  ')
}

function RunRow({ run }: { run: Run }) {
  const [open, setOpen] = useState(false)
  const pnlColour = run.realized_pnl > 0 ? GREEN : run.realized_pnl < 0 ? RED : MUTED
  const winRate = run.closed_trades ? (100 * run.wins) / run.closed_trades : null
  const tooFew = run.closed_trades < MEANINGFUL_SAMPLE

  return (
    <div style={{ borderTop: '1px solid #1a1a26', padding: '9px 0' }}>
      <div
        onClick={() => setOpen(!open)}
        style={{ display: 'flex', alignItems: 'baseline', gap: 8, cursor: 'pointer' }}
      >
        <span style={{ fontSize: 12, color: '#e8e8ef', fontWeight: 600 }}>
          {run.label || `run ${run.id.slice(0, 8)}`}
        </span>
        {run.active && (
          <span style={{ fontSize: 9, color: GREEN, border: `1px solid ${GREEN}`, borderRadius: 3, padding: '0 4px' }}>
            ACTIVE
          </span>
        )}
        <span style={{ fontSize: 11, color: MUTED }}>{duration(run)}</span>
        <span style={{ marginLeft: 'auto', fontSize: 12, color: pnlColour, fontFamily: 'var(--font-mono)' }}>
          {run.realized_pnl >= 0 ? '+' : ''}
          {run.realized_pnl.toFixed(2)}
        </span>
        <span style={{ fontSize: 10, color: MUTED }}>{open ? '▾' : '▸'}</span>
      </div>

      <div style={{ fontSize: 11, color: MUTED, marginTop: 2 }}>
        {run.closed_trades} trade{run.closed_trades === 1 ? '' : 's'}
        {winRate !== null && (
          <>
            {' · '}
            <span style={{ color: tooFew ? MUTED : '#e8e8ef' }}>{winRate.toFixed(0)}% won</span>
            {/* Sample size beside the rate, always. A win rate without it is the
                kind of number that gets quoted later without its caveat. */}
            {tooFew && (
              <span style={{ color: AMBER }}>
                {' '}(only {run.closed_trades} of {MEANINGFUL_SAMPLE} needed to mean anything)
              </span>
            )}
          </>
        )}
        {run.decisions > 0 && (
          <>
            {' · '}
            {run.decisions} decision{run.decisions === 1 ? '' : 's'}, {run.abstentions} declined
          </>
        )}
      </div>

      {open && (
        <div style={{ marginTop: 6, paddingLeft: 10, borderLeft: '2px solid #1e2035' }}>
          <div style={{ fontSize: 10, color: MUTED, letterSpacing: '0.06em', marginBottom: 3 }}>
            SETTINGS
          </div>
          <div style={{ fontSize: 11, color: '#8888a0', fontFamily: 'var(--font-mono)', lineHeight: 1.6 }}>
            {settingsLine(run.config)}
          </div>
          {run.note && (
            <div style={{ fontSize: 11, color: MUTED, marginTop: 5, lineHeight: 1.5 }}>{run.note}</div>
          )}
          <div style={{ fontSize: 10, color: MUTED, marginTop: 5 }}>
            {run.started_at ? new Date(run.started_at).toLocaleString() : '—'}
            {run.ended_at ? ` → ${new Date(run.ended_at).toLocaleString()}` : ' → now'}
          </div>
        </div>
      )}
    </div>
  )
}

export function RunHistoryPanel() {
  const [runs, setRuns] = useState<Run[] | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let alive = true
    const load = () =>
      api.engine
        .runs()
        .then((r) => { if (alive) { setRuns(r as unknown as Run[]); setFailed(false) } })
        .catch(() => { if (alive) setFailed(true) })
    load()
    const id = setInterval(load, 60_000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  if (failed) {
    return <div style={{ fontSize: 11, color: AMBER }}>Run history unavailable — the API did not respond.</div>
  }
  if (!runs) return null
  if (runs.length === 0) {
    return <div style={{ fontSize: 12, color: MUTED }}>No runs recorded yet.</div>
  }

  return (
    <div>
      <div style={{ fontSize: 11, color: MUTED, lineHeight: 1.5, marginBottom: 4 }}>
        Resetting the engine starts a new run. Nothing is deleted — every run below
        keeps its own trades and decisions.
      </div>
      {runs.map((r) => <RunRow key={r.id} run={r} />)}
    </div>
  )
}
