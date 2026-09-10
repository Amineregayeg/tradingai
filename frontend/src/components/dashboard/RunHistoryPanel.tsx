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
  /** Refusals split by the direction the strategy asked for. A `GROUP BY`, not a counter. */
  rejected_by_direction?: Record<string, number> | null
  rejections?: number
}

/**
 * T-0137. WHY A LONG-ONLY RUN NEEDS ITS OWN MARK ON THIS PANEL.
 *
 * Malek ruled 2026-09-10 that the venue is Alpaca and the platform is LONG ONLY, because
 * Alpaca crypto is non-marginable and not shortable. Measured on real executed trades: 147
 * shorts against 146 longs — so roughly HALF of every decision this engine has ever made
 * cannot be placed.
 *
 * That makes a long-only run a DIFFERENT STRATEGY rather than a smaller sample of the same
 * one, and its P&L and win rate are not comparable with anything recorded before the ruling.
 * Two lines above, this file already says why that matters: *"A result read against the wrong
 * configuration is worse than no result — and comparing runs is the entire point of keeping
 * them."* This is that rule applied to the setting that changes the most.
 */
function longOnly(cfg: Record<string, unknown> | null): boolean {
  return cfg?.long_only === true
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
  // The account SIZE belongs on this line even though it never changes any more.
  // The history spans the settings freeze: runs before it started from $50,000
  // of plain paper, runs after from a $5,000 prop-firm challenge. Their dollar
  // P&L is not comparable, and without the size on the line the two are
  // indistinguishable — same symbols, same timeframe, same risk percentage.
  const bal = typeof cfg.starting_balance === 'number'
    ? `$${cfg.starting_balance.toLocaleString('en-US', { maximumFractionDigits: 0 })}`
    : ''
  // The VENUE and its direction constraint, on the settings line with everything else that
  // makes two runs incomparable. Absent from older runs' config, which is why this reads the
  // value rather than assuming one: a run recorded before the ruling must not be labelled
  // long-only retroactively.
  const venue = typeof cfg.venue === 'string' ? cfg.venue : ''
  const directions = longOnly(cfg) ? 'LONG ONLY' : ''
  return [syms, cfg.entry_tf, risk, bal, cfg.mode, `prices: ${cfg.price_source ?? 'binance'}`,
          venue, directions]
    .filter(Boolean)
    .join('  ·  ')
}

/** Refusals worth showing beside the P&L, ordered so the constrained direction reads first. */
function refusals(run: Run): [string, number][] {
  const split = run.rejected_by_direction
  if (!split) return []
  return Object.entries(split).filter(([, n]) => n > 0).sort((a, b) => b[1] - a[1])
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
        {/* BESIDE THE P&L, NOT INSIDE THE COLLAPSED DETAIL. This number is the one that gets
            read as "the strategy underperformed", and a mark a reader has to expand a row to
            find does not qualify it. */}
        {longOnly(run.config) && (
          <span
            data-testid="long-only-badge"
            title="Alpaca crypto is non-marginable and not shortable — every SHORT this run produced was refused by the venue."
            style={{ fontSize: 9, color: AMBER, border: `1px solid ${AMBER}`, borderRadius: 3, padding: '0 4px' }}
          >
            LONG ONLY
          </span>
        )}
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
        {/* THE SPLIT, NOT THE TOTAL. A run that produced no shorts and a run that produced 147
            and had every one refused have the same trades, the same P&L and the same win rate.
            The direction of the rejections is the only thing on this panel that tells them
            apart — a bare count does not.

            "REJECTED", NOT "REFUSED BY THE VENUE", AND THE DISTINCTION IS NOT PEDANTRY.
            `execute()` checks entry drift, the stop and the size BEFORE it ever reaches
            `place_order`, so a SHORT can be rejected for reasons that have nothing to do with
            Alpaca and never reach the venue check at all. Beside a LONG ONLY badge the word
            "refused" would attribute every one of them to the ruling — a count that reads as
            a cause. Which rejection was which is on the DecisionRecord's `rejection_reason`;
            this line reports only what is actually being counted. */}
        {refusals(run).length > 0 && (
          <span
            data-testid="refusal-split"
            title="Every signal the strategy produced and execution declined, split by the direction asked for. Includes venue refusals AND bar-specific rejections (entry drift, size, stop); the reason for each is on its decision record."
          >
            {' · '}
            {refusals(run).map(([dir, n]) => `${n} ${dir} rejected`).join(', ')}
          </span>
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
