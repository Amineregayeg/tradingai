import { useCallback, useEffect, useState } from 'react'
import { api } from '@/services/api'

const GREEN = '#00d68f'
const RED = '#ff3b5c'
const AMBER = '#f59e0b'
const MUTE = '#8888a0'

type Dict = Record<string, unknown>
const n = (x: unknown): number | null => {
  const v = Number(x)
  return Number.isFinite(v) ? v : null
}
const pct = (x: unknown, d = 1) => {
  const v = n(x)
  return v === null ? '—' : `${v.toFixed(d)}%`
}
const money = (x: unknown) => {
  const v = n(x)
  return v === null ? '—' : (v < 0 ? '-$' : '$') + Math.abs(Math.round(v)).toLocaleString()
}
const r = (x: unknown) => {
  const v = n(x)
  return v === null ? '—' : `${v >= 0 ? '+' : ''}${v.toFixed(2)}R`
}

function Panel({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div style={{ background: '#12121a', border: '1px solid #1e2035', borderRadius: 12, padding: '16px 18px', marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 12 }}>
        <div style={{ fontSize: 11, color: '#55556a', fontWeight: 700, letterSpacing: '0.07em', textTransform: 'uppercase' }}>{title}</div>
        {right}
      </div>
      {children}
    </div>
  )
}

function Stat({ label, value, color }: { label: string; value: string; color?: string }) {
  return (
    <div style={{ flex: 1, minWidth: 120 }}>
      <div style={{ fontSize: 10, color: '#55556a', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 6 }}>{label}</div>
      <div style={{ fontSize: 19, fontWeight: 700, color: color ?? '#e8e8ef', fontFamily: 'var(--font-mono)' }}>{value}</div>
    </div>
  )
}

export default function EnginePage() {
  const [status, setStatus] = useState<Dict | null>(null)
  const [sim, setSim] = useState<Dict | null>(null)
  const [decisions, setDecisions] = useState<Dict[]>([])
  // which decision's reasoning is expanded (null = none)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [feedback, setFeedback] = useState<Dict | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(() => {
    api.engine.status().then(setStatus).catch((e) => setErr(String(e?.detail || e?.title || 'engine offline')))
    api.engine.sim().then(setSim).catch(() => setSim(null))
    api.engine.decisions(50).then((d) => setDecisions(Array.isArray(d) ? d : [])).catch(() => setDecisions([]))
    api.engine.feedback(30).then(setFeedback).catch(() => setFeedback(null))
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 5000)
    return () => clearInterval(t)
  }, [load])

  const paused = !!status?.paused
  const mode = String(status?.mode ?? '—')
  const simOn = !!sim?.enabled

  const gaps = (feedback?.gaps ?? {}) as Dict
  const eva = (feedback?.expected_vs_actual ?? {}) as Dict
  const corrections = (feedback?.corrections ?? []) as Dict[]
  const activity = (status?.activity ?? []) as Dict[]

  return (
    <div style={{ flex: 1, overflow: 'auto', background: '#0a0a0f' }}>
      <div style={{ padding: '20px 28px 16px', borderBottom: '1px solid #1e2035', background: '#0d0d14', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#e8e8ef', margin: 0 }}>Engine</h1>
          <div style={{ fontSize: 12, color: MUTE, marginTop: 5 }}>
            Live decisions, prop-firm challenge state, and the feedback loop —{' '}
            <span style={{ color: simOn ? AMBER : GREEN, fontWeight: 600 }}>{mode}</span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => {
              // A reset is NOT destructive — nothing is deleted and the previous
              // run stays queryable — but it does zero the visible numbers, and
              // an unexpected reset would look exactly like data loss.
              if (!window.confirm(
                'Start a new run?\n\n' +
                'Metrics restart at zero and the balance returns to its starting value.\n' +
                'Nothing is deleted \u2014 the current run is kept and stays viewable.'
              )) return
              api.engine.reset().then(setStatus).catch(() => {})
            }}
            style={{ padding: '8px 14px', border: '1px solid #5c3d00', borderRadius: 8, background: 'transparent', color: '#e3b341', fontSize: 12, cursor: 'pointer' }}>Reset run</button>
          <button onClick={() => api.engine.pause().then(setStatus).catch(() => {})} disabled={paused}
            style={{ padding: '8px 14px', border: '1px solid #252540', borderRadius: 8, background: paused ? '#1a1a24' : 'transparent', color: paused ? '#55556a' : '#e8e8ef', fontSize: 12, cursor: paused ? 'default' : 'pointer' }}>Pause</button>
          <button onClick={() => api.engine.resume().then(setStatus).catch(() => {})} disabled={!paused}
            style={{ padding: '8px 14px', border: '1px solid #252540', borderRadius: 8, background: !paused ? '#1a1a24' : 'transparent', color: !paused ? '#55556a' : '#e8e8ef', fontSize: 12, cursor: !paused ? 'default' : 'pointer' }}>Resume</button>
        </div>
      </div>

      <div style={{ padding: '18px 28px', maxWidth: 1180 }}>
        {err && !status && (
          <div style={{ background: 'rgba(255,59,92,0.08)', border: '1px solid #5c1f2a', borderRadius: 10, padding: '11px 14px', marginBottom: 14, color: '#ff8fa3', fontSize: 13 }}>
            Engine not reachable: {err}
          </div>
        )}

        {/* Engine status */}
        <Panel title="Status">
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <Stat label="State" value={paused ? 'Paused' : 'Running'} color={paused ? AMBER : GREEN} />
            <Stat label="Balance" value={money(status?.balance)} />
            <Stat label="Equity" value={money(status?.equity)} />
            <Stat label="Win rate" value={pct(status?.win_rate)} color={AMBER} />
            <Stat label="Closed trades" value={String(status?.closed_trades ?? '—')} />
            <Stat label="Open" value={String(status?.open_positions ?? '—')} />
          </div>
        </Panel>

        {/* Prop-firm challenge (sim mode only) */}
        {simOn && (
          <Panel title="Prop-Firm Challenge"
            right={<span style={{ fontSize: 12, fontWeight: 700, color: sim?.status === 'failed' ? RED : sim?.status === 'passed' ? GREEN : AMBER, textTransform: 'uppercase' }}>{String(sim?.status ?? '')}{sim?.breach_reason ? ` · ${String(sim.breach_reason)}` : ''}</span>}>
            <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
              <Stat label="Balance" value={money(sim?.balance)} />
              <Stat label="Day P&L" value={pct(sim?.day_pnl_pct)} color={(n(sim?.day_pnl_pct) ?? 0) < 0 ? RED : GREEN} />
              <Stat label="Drawdown" value={pct(sim?.drawdown_pct)} color={AMBER} />
              <Stat label={`Daily limit (${pct(sim?.daily_loss_limit_pct, 0)})`} value={money(sim?.balance)} />
              <Stat label="Profit target" value={pct(sim?.profit_target_pct, 0)} color={GREEN} />
              <Stat label="Trading days" value={`${sim?.trading_days ?? 0}/${sim?.min_trading_days ?? 0}`} />
            </div>
          </Panel>
        )}

        {/* Feedback loop */}
        <Panel title="Feedback Loop — Expected vs Actual"
          right={feedback?.abstained ? <span style={{ fontSize: 11, color: MUTE }}>abstained · thin evidence</span> : <span style={{ fontSize: 11, color: MUTE }}>{String(feedback?.n ?? 0)} closed</span>}>
          <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap', marginBottom: corrections.length ? 14 : 0 }}>
            <Stat label="Mean realized R" value={r(eva.mean_realized_r)} color={(n(eva.mean_realized_r) ?? 0) >= 0 ? GREEN : RED} />
            <Stat label="Winners realized R" value={r(eva.mean_winner_realized_r)} color={GREEN} />
            <Stat label="Winners vs target" value={r(gaps.winner_realized_minus_target_r)} color={(n(gaps.winner_realized_minus_target_r) ?? 0) >= 0 ? GREEN : RED} />
            <Stat label="Slippage" value={r(gaps.mean_slippage_r)} color={AMBER} />
            <Stat label="Win-rate gap" value={eva.actual_win_rate != null ? `${(((n(gaps.win_rate_gap) ?? 0)) * 100).toFixed(1)}pp` : '—'} />
          </div>
          {feedback?.abstained ? (
            <div style={{ fontSize: 12, color: MUTE, lineHeight: 1.5 }}>{String(feedback?.abstain_reason ?? '')}</div>
          ) : corrections.length === 0 ? (
            <div style={{ fontSize: 12, color: MUTE }}>No corrections proposed — the engine is tracking its expectations.</div>
          ) : (
            <div>
              <div style={{ fontSize: 10, color: '#55556a', fontWeight: 700, letterSpacing: '0.06em', textTransform: 'uppercase', marginBottom: 8 }}>Proposed corrections (risk_pct is never tuned)</div>
              {corrections.map((c, i) => (
                <div key={i} style={{ padding: '10px 12px', background: '#0d0d14', border: '1px solid #1e2035', borderRadius: 8, marginBottom: 8 }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: '#e8e8ef' }}>
                      {String(c.target_param)}: <span style={{ color: MUTE }}>{String(c.current)}</span> → <span style={{ color: AMBER }}>{String(c.proposed)}</span>
                    </span>
                    <span style={{ fontSize: 11, color: MUTE }}>n={String(c.evidence_n)} · conf {n(c.confidence) != null ? (n(c.confidence)! * 100).toFixed(0) + '%' : '—'}</span>
                  </div>
                  <div style={{ fontSize: 12, color: '#b8b8c8', marginTop: 5, lineHeight: 1.5 }}>{String(c.rationale)}</div>
                </div>
              ))}
            </div>
          )}
        </Panel>

        {/* Decision log */}
        <Panel title="Decision Log" right={<span style={{ fontSize: 11, color: MUTE }}>{decisions.length} recent</span>}>
          {decisions.length === 0 ? (
            <div style={{ fontSize: 12, color: MUTE }}>No decisions recorded yet. Every evaluated bar appears here — taken trades with their expected and realized R, and refusals with the reason they were refused.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr style={{ color: '#55556a', textAlign: 'left' }}>
                    {['Time', 'Symbol', 'Dir', 'Entry', 'Exp R', 'Real R', 'Gap R', 'Outcome'].map((h) => (
                      <th key={h} style={{ padding: '6px 10px', fontWeight: 600, borderBottom: '1px solid #1e2035', whiteSpace: 'nowrap' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {decisions.map((d, i) => {
                    const out = String(d.outcome ?? '')
                    const oc = out === 'WIN' ? GREEN : out === 'LOSS' ? RED : MUTE
                    // The engine's own reasoning. Abstentions are the majority
                    // of what it does and used to leave no record at all, so
                    // they are shown in the same log rather than hidden behind
                    // a filter — the refusals ARE the strategy.
                    const abstained = Boolean(d.abstained)
                    const reasons = Array.isArray(d.reasons) ? (d.reasons as string[]) : []
                    const open = expanded === i
                    return (
                      <>
                      <tr key={i}
                          onClick={() => reasons.length && setExpanded(open ? null : i)}
                          style={{ borderBottom: reasons.length && open ? 'none' : '1px solid #15151f',
                                   cursor: reasons.length ? 'pointer' : 'default',
                                   opacity: abstained ? 0.75 : 1 }}>
                        <td style={{ padding: '6px 10px', color: MUTE, whiteSpace: 'nowrap' }}>{d.created_at ? new Date(String(d.created_at)).toLocaleString() : '—'}</td>
                        <td style={{ padding: '6px 10px', color: '#e8e8ef' }}>{String(d.symbol ?? '')}</td>
                        <td style={{ padding: '6px 10px', color: String(d.signal_dir) === 'LONG' ? GREEN : RED }}>{String(d.signal_dir ?? '')}</td>
                        <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)' }}>{n(d.signal_entry)?.toLocaleString() ?? '—'}</td>
                        <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)' }}>{r(d.expected_r)}</td>
                        <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', color: oc }}>{d.realized_r != null ? r(d.realized_r) : '—'}</td>
                        <td style={{ padding: '6px 10px', fontFamily: 'var(--font-mono)', color: (n(d.gap_r) ?? 0) >= 0 ? GREEN : RED }}>{d.gap_r != null ? r(d.gap_r) : '—'}</td>
                        <td style={{ padding: '6px 10px', color: oc, fontWeight: 600 }}>
                          {out || 'OPEN'}
                          {reasons.length > 0 && (
                            <span style={{ color: MUTE, marginLeft: 6, fontWeight: 400 }}>
                              {open ? '▾' : '▸'}
                            </span>
                          )}
                        </td>
                      </tr>
                      {open && reasons.length > 0 && (
                        <tr key={`${i}-why`} style={{ borderBottom: '1px solid #15151f' }}>
                          <td colSpan={8} style={{ padding: '2px 10px 10px 10px', background: '#0f0f17' }}>
                            <div style={{ fontSize: 10, color: MUTE, marginBottom: 4, letterSpacing: '0.06em' }}>
                              WHY
                            </div>
                            {reasons.map((rs, k) => (
                              <div key={k} style={{
                                fontSize: 11, lineHeight: 1.6, fontFamily: 'var(--font-mono)',
                                color: rs.startsWith('FAIL') ? '#ff8fa3'
                                     : rs.startsWith('PASS') ? '#7fe3c0' : MUTE,
                                paddingLeft: rs.startsWith('  ') ? 14 : 0,
                              }}>{rs.trim()}</div>
                            ))}
                          </td>
                        </tr>
                      )}
                      </>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Panel>

        {/* Activity feed — the engine's live reasoning */}
        <Panel title="Activity — what the engine is doing">
          {activity.length === 0 ? (
            <div style={{ fontSize: 12, color: MUTE }}>No activity yet.</div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 320, overflowY: 'auto' }}>
              {activity.map((a, i) => (
                <div key={i} style={{ display: 'flex', gap: 10, fontSize: 12, padding: '3px 0' }}>
                  <span style={{ color: '#55556a', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>{a.time ? new Date(String(a.time)).toLocaleTimeString() : ''}</span>
                  <span style={{ color: '#55556a', textTransform: 'uppercase', fontSize: 10, fontWeight: 700, minWidth: 52 }}>{String(a.kind ?? '')}</span>
                  <span style={{ color: '#b8b8c8' }}>{String(a.msg ?? '')}</span>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>
    </div>
  )
}
