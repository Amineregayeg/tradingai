import { useEffect, useState } from 'react'
import { api } from '@/services/api'

/**
 * Configure a run before starting it (task 2.2).
 *
 * Applying a configuration ALWAYS starts a new run. Changing the timeframe or
 * symbol set halfway through would make the result uninterpretable, so settings
 * belong to a run and are snapshotted with it.
 *
 * THE OPTIONS COME FROM THE BACKEND, deliberately. The broker connection form
 * hard-coded its choices and offered three brokers and one environment that the
 * backend could only ever refuse — every attempt failed with an opaque error.
 * Serving the options means this form cannot present something that will be
 * rejected.
 *
 * RISK IS SHOWN AS FIXED RATHER THAN OMITTED. An absent field looks like an
 * oversight; a stated one with its reason looks deliberate — and it is:
 * ROI ≈ risk_pct × n × avg_R is an identity, so changing risk only rescales the
 * curve and the drawdown together. It cannot make a strategy better, only
 * louder.
 */

const MUTED = '#55556a'
const AMBER = '#e3b341'

interface Options {
  symbols: string[]
  entry_tf: string[]
  bias_tf: string[]
  broker_mode: { value: string; label: string }[]
  price_source: { value: string; label: string }[]
  starting_balance: { min: number; max: number }
  max_concurrent: { min: number; max: number }
  fixed: Record<string, { value: number; reason: string }>
}

const label = { fontSize: 11, color: MUTED, display: 'block', marginBottom: 4 } as const
const field = { width: '100%', marginBottom: 12 } as const

export function RunConfigForm({ onApplied }: { onApplied?: () => void }) {
  const [opts, setOpts] = useState<Options | null>(null)
  const [form, setForm] = useState<Record<string, unknown>>({})
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.engine
      .configOptions()
      .then((o) => setOpts(o as unknown as Options))
      .catch(() => setError('Could not load configuration options.'))
  }, [])

  if (error && !opts) return <div style={{ fontSize: 11, color: AMBER }}>{error}</div>
  if (!opts) return null

  const set = (k: string, v: unknown) => setForm((f) => ({ ...f, [k]: v }))

  const apply = () => {
    if (!window.confirm(
      'Apply these settings and start a new run?\n\n' +
      'Metrics restart at zero. Nothing is deleted — the current run is kept ' +
      'and stays viewable under Runs.'
    )) return
    setBusy(true); setError('')
    api.engine
      .reset(form)
      .then(() => { setBusy(false); onApplied?.() })
      // Show the backend's reason verbatim. It explains WHY a value was
      // refused, and replacing it with a generic message would hide the only
      // useful part.
      .catch((e) => { setBusy(false); setError(String(e?.detail || 'Could not apply settings.')) })
  }

  return (
    <div>
      <div style={{ fontSize: 11, color: MUTED, lineHeight: 1.5, marginBottom: 10 }}>
        Settings belong to a run. Applying them starts a new one so results are
        never a mix of two configurations.
      </div>

      <label style={label}>Symbols</label>
      <div style={{ display: 'flex', gap: 12, marginBottom: 12, flexWrap: 'wrap' }}>
        {opts.symbols.map((s) => {
          const chosen = (form.symbols as string[] | undefined) ?? null
          const on = chosen === null ? true : chosen.includes(s)
          return (
            <label key={s} style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12, color: '#e8e8ef' }}>
              <input
                type="checkbox"
                checked={on}
                onChange={(e) => {
                  const base = chosen ?? opts.symbols
                  set('symbols', e.target.checked ? [...base, s] : base.filter((x) => x !== s))
                }}
              />
              {s}
            </label>
          )
        })}
      </div>

      <div style={{ display: 'flex', gap: 12 }}>
        <div style={{ flex: 1 }}>
          <label style={label}>Entry timeframe</label>
          <select style={field} value={String(form.entry_tf ?? '1H')}
                  onChange={(e) => set('entry_tf', e.target.value)}>
            {opts.entry_tf.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div style={{ flex: 1 }}>
          <label style={label}>Bias timeframe</label>
          <select style={field} value={String(form.bias_tf ?? 'D')}
                  onChange={(e) => set('bias_tf', e.target.value)}>
            {opts.bias_tf.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
      </div>

      <label style={label}>Starting balance</label>
      <input type="number" style={field}
             min={opts.starting_balance.min} max={opts.starting_balance.max}
             value={String(form.starting_balance ?? 50000)}
             onChange={(e) => set('starting_balance', Number(e.target.value))} />

      <label style={label}>Broker mode</label>
      <select style={field} value={String(form.broker_mode ?? 'paper')}
              onChange={(e) => set('broker_mode', e.target.value)}>
        {opts.broker_mode.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
      </select>

      <label style={label}>Price source</label>
      <select style={field} value={String(form.price_source ?? 'binance')}
              onChange={(e) => set('price_source', e.target.value)}>
        {opts.price_source.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
      </select>

      <label style={label}>Run label (optional)</label>
      <input type="text" style={field} placeholder="e.g. 15m on CFT prices"
             value={String(form.label ?? '')}
             onChange={(e) => set('label', e.target.value)} />

      {/* Stated, not hidden. */}
      {opts.fixed?.risk_pct && (
        <div style={{
          fontSize: 11, color: MUTED, lineHeight: 1.5, padding: '8px 10px',
          background: '#12121a', border: '1px solid #1e2035', borderRadius: 7, marginBottom: 12,
        }}>
          <b style={{ color: '#e8e8ef' }}>
            Risk per trade is fixed at {(opts.fixed.risk_pct.value * 100).toFixed(0)}%
          </b>
          <div style={{ marginTop: 3 }}>{opts.fixed.risk_pct.reason}</div>
        </div>
      )}

      {error && (
        <div style={{ fontSize: 11, color: '#ff3b5c', marginBottom: 10, lineHeight: 1.5 }}>{error}</div>
      )}

      <button onClick={apply} disabled={busy}
              style={{
                padding: '9px 16px', border: 'none', borderRadius: 7,
                background: busy ? '#6b5fa0' : '#a78bfa', color: '#fff',
                fontSize: 13, fontWeight: 600, cursor: busy ? 'default' : 'pointer',
              }}>
        {busy ? 'Starting…' : 'Apply and start a new run'}
      </button>
    </div>
  )
}
