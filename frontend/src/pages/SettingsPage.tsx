import { useState, useEffect } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'
import { api } from '@/services/api'
import { useLoadState } from '@/hooks/useLoadState'
import { LoadFailure, ActionError } from '@/components/shared'
import { useAction } from '@/hooks/useAction'
import type { Settings, BrokerConnection, BrokerConnectRequest } from '@/types/api'

/**
 * What the BACKEND can actually construct — see broker/manager.py::_make_adapter.
 *
 * This form used to offer four brokers and two environments. Three of those
 * brokers (OANDA, Alpaca, MetaAPI) do not exist in _make_adapter and raise
 * "Unsupported broker"; the OANDA adapter was deliberately removed as the only
 * unguarded real-money path. And CryptoFundTrader has exactly one environment —
 * CFT_BASE_URLS is {"live": ...} — so "Practice" raised "no 'practice'
 * environment" every time.
 *
 * Worse, the form DEFAULTED to oanda + practice, so the out-of-the-box state was
 * a guaranteed failure, and each failure surfaced as an opaque 500. Offering a
 * choice that cannot work is not a neutral extra option: it sends the user
 * hunting for a mistake they did not make.
 *
 * Keep this in step with _make_adapter. Adding an adapter there means adding it
 * here; the reverse is not true and must never be — a broker listed here that
 * the backend cannot build is exactly the bug this replaced.
 *
 * `B369` — AND THE ONE-DIRECTIONAL INVARIANT ABOVE IS WHY MT5 WAS MISSING FOR A DAY.
 * "Frontend ⊆ backend" guarantees you cannot OFFER what the backend refuses, and says
 * nothing about offering what the backend now ACCEPTS. So an adapter added on the
 * backend violates nothing here and the UI lags it silently, invisibly from both
 * sides: nothing is broken and the feature does not exist. MT5 was constructible
 * from the API before it was reachable from this form.
 *
 * NOTE ON "live": it selects CFT's only HOST, not real-money trading. A
 * challenge account is fake money on that same host. Order placement is gated
 * separately by observe_only and the server-side ALLOW_LIVE_TRADING flag.
 */
const BROKER_CAPABILITIES = {
  cryptofundtrader: {
    label: 'Crypto Fund Trader',
    environments: [{ value: 'live', label: 'Live' }],
    envNote: 'CFT runs a single host. A challenge account is simulated funds on it.',
  },
  mt5: {
    label: 'MetaTrader 5 (MetaApi)',
    // BOTH, unlike CFT. A MetaApi account is provisioned against a demo or a live broker
    // server and the platform reads either — so offering only one would repeat the CFT
    // mistake in the opposite direction, sending a demo user hunting for a mistake they
    // did not make.
    environments: [
      { value: 'practice', label: 'Demo' },
      { value: 'live', label: 'Live' },
    ],
    envNote: 'Matches the MetaApi account you provisioned. Reads only — MT5 order placement '
      + 'refuses at the adapter until the sizing conversion is settled.',
  },
} as const

type SupportedBroker = keyof typeof BROKER_CAPABILITIES

const SUPPORTED_BROKERS = Object.keys(BROKER_CAPABILITIES) as SupportedBroker[]

// Section wrapper
function Section({ title, description, children }: { title: string; description?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 32 }}>
      <div style={{ marginBottom: 16 }}>
        <h2 style={{ fontSize: 15, fontWeight: 700, color: '#e8e8ef', marginBottom: 4 }}>{title}</h2>
        {description && <p style={{ fontSize: 12, color: '#55556a' }}>{description}</p>}
      </div>
      <div style={{
        background: '#12121a', border: '1px solid #1e2035', borderRadius: 10, overflow: 'hidden',
      }}>
        {children}
      </div>
    </div>
  )
}

// Setting row
function SettingRow({ label, description, children, last }: { label: string; description?: string; children: React.ReactNode; last?: boolean }) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', justifyContent: 'space-between',
      padding: '14px 20px',
      borderBottom: last ? 'none' : '1px solid #1a1a26',
    }}>
      <div style={{ flex: 1, marginRight: 24 }}>
        <div style={{ fontSize: 13, fontWeight: 500, color: '#e8e8ef' }}>{label}</div>
        {description && <div style={{ fontSize: 11, color: '#55556a', marginTop: 2 }}>{description}</div>}
      </div>
      {children}
    </div>
  )
}

// Toggle switch
function Toggle({ checked, onChange }: { checked: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!checked)}
      style={{
        width: 44, height: 24, borderRadius: 12, border: 'none', cursor: 'pointer', flexShrink: 0,
        background: checked ? '#a78bfa' : '#252540',
        position: 'relative', transition: 'background 200ms',
      }}
    >
      <div style={{
        position: 'absolute', top: 3, left: checked ? 23 : 3,
        width: 18, height: 18, borderRadius: '50%', background: '#fff',
        transition: 'left 200ms', boxShadow: '0 1px 3px rgba(0,0,0,0.3)',
      }} />
    </button>
  )
}

type SectionId = 'broker' | 'ai' | 'risk' | 'notifications' | 'appearance'

const NAV_SECTIONS: { id: SectionId; label: string; icon: string }[] = [
  { id: 'broker', label: 'Broker Connections', icon: '🔗' },
  { id: 'ai', label: 'AI Behavior', icon: '✦' },
  { id: 'risk', label: 'Risk Defaults', icon: '⚠' },
  { id: 'notifications', label: 'Notifications', icon: '🔔' },
  { id: 'appearance', label: 'Appearance', icon: '🎨' },
]

export default function SettingsPage() {
  const [activeSection, setActiveSection] = useState<SectionId>('broker')
  const settings = useSettingsStore((s) => s.settings)
  const setSettings = useSettingsStore((s) => s.setSettings)
  const [brokers, setBrokers] = useState<BrokerConnection[]>([])
  const { failed, track } = useLoadState()
  const { error: actionErr, run, dismiss } = useAction()
  const [showAddBroker, setShowAddBroker] = useState(false)
  const [brokerForm, setBrokerForm] = useState<BrokerConnectRequest>({
    // Defaults must be a combination that CAN succeed — see BROKER_CAPABILITIES.
    // These were previously 'oanda' + 'practice', neither of which the backend
    // supports, so an untouched form failed on submit.
    broker: 'cryptofundtrader',
    api_key: '',
    account_id: '',
    environment: 'live',
    observe_only: true,
  })
  const [connectLoading, setConnectLoading] = useState(false)
  const [connectError, setConnectError] = useState('')

  useEffect(() => {
    // A swallowed failure here rendered as "No broker connections", which on
    // this platform reads as "you are not connected to your funded account" —
    // a statement about money, made without knowing (E3).
    track('broker connections', api.brokers.list(), [] as BrokerConnection[])
      .then((b) => setBrokers(Array.isArray(b) ? b : []))
    if (!settings) api.settings.get().then(setSettings).catch(() => {})
  }, [settings, setSettings])

  const updateSetting = (key: keyof Settings, value: unknown) => {
    if (!settings) return
    // The update is OPTIMISTIC — the control moves before the server agrees.
    // Swallowing the failure left the UI showing a setting that was never
    // saved, which survives until a reload and is then silently wrong (E5).
    // Revert on failure and say why.
    const previous = settings
    const updated = { ...settings, [key]: value }
    setSettings(updated)
    void run(`Saving ${String(key)}`, () => api.settings.update({ [key]: value }))
      .then((r) => { if (!r.ok) setSettings(previous) })
  }

  const handleConnect = async () => {
    setConnectLoading(true)
    setConnectError('')
    try {
      const conn = await api.brokers.connect(brokerForm)
      setBrokers((b) => [...b, conn])
      setShowAddBroker(false)
      // `B369`. THIS RESET SAID `oanda` + `practice` — the exact pair the comment four lines
      // above line 120 says the backend cannot build, recreated after every SUCCESSFUL connect.
      // The initial state was fixed and the reset was missed, so the form was correct until it
      // was used once. It now returns to the same default the component starts from.
      setBrokerForm({ broker: SUPPORTED_BROKERS[0], api_key: '', account_id: '', environment: 'live', observe_only: true })
    } catch (e: unknown) {
      const err = e as { detail?: string }
      setConnectError(err?.detail ?? 'Connection failed')
    } finally {
      setConnectLoading(false)
    }
  }

  return (
    <div style={{ display: 'flex', flex: 1, overflow: 'hidden', background: '#0a0a0f' }}>
      {/* Settings sidebar nav */}
      <div style={{
        width: 220, flexShrink: 0, background: '#0d0d14', borderRight: '1px solid #1e2035',
        padding: '20px 12px', overflowY: 'auto',
      }}>
        <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', color: '#55556a', marginBottom: 12, padding: '0 8px' }}>
          SETTINGS
        </div>
        {NAV_SECTIONS.map((s) => (
          <button
            key={s.id}
            onClick={() => setActiveSection(s.id)}
            style={{
              display: 'flex', alignItems: 'center', gap: 10, width: '100%',
              padding: '9px 12px', border: 'none', borderRadius: 7, cursor: 'pointer',
              background: activeSection === s.id ? '#1a1a26' : 'transparent',
              color: activeSection === s.id ? '#e8e8ef' : '#8888a0',
              fontSize: 13, fontWeight: activeSection === s.id ? 600 : 400,
              marginBottom: 2, textAlign: 'left',
            }}
          >
            <span style={{ fontSize: 14 }}>{s.icon}</span>
            {s.label}
          </button>
        ))}
      </div>

      {/* Settings content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '28px 36px', maxWidth: 720 }}>

        {activeSection === 'broker' && (
          <Section title="Broker Connections" description="Connect your trading accounts to sync positions and trades.">
            <LoadFailure what={failed} />
            <ActionError message={actionErr} onDismiss={dismiss} />
            {brokers.length === 0 && failed.length === 0 ? (
              <div style={{ padding: '32px 20px', textAlign: 'center' }}>
                <div style={{ fontSize: 13, color: '#55556a', marginBottom: 16 }}>
                  No broker connections. Click "Add Broker" to connect your first account.
                </div>
                <button onClick={() => setShowAddBroker(true)} style={{
                  padding: '8px 18px', border: 'none', borderRadius: 7,
                  background: '#a78bfa', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer',
                }}>+ Add Broker</button>
              </div>
            ) : (
              <>
                {brokers.map((b, idx) => (
                  <SettingRow
                    key={b.id}
                    label={b.label || b.broker}
                    description={`${b.account_id ?? '—'} · ${b.environment ?? '—'}`}
                    last={idx === brokers.length - 1}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                      <div style={{
                        width: 8, height: 8, borderRadius: '50%',
                        background: b.connected ? '#00d68f' : '#ff3b5c',
                      }} />
                      <span style={{ fontSize: 11, color: b.connected ? '#00d68f' : '#ff3b5c' }}>
                        {b.connected ? 'Connected' : 'Disconnected'}
                      </span>
                      <button
                        onClick={() => {
                          void run('Disconnect broker', () => api.brokers.disconnect(b.id))
                            .then((r) => { if (r.ok) setBrokers((brs) => brs.filter((x) => x.id !== b.id)) })
                        }}
                        style={{
                          padding: '4px 10px', border: '1px solid #252540', borderRadius: 5,
                          background: 'transparent', color: '#8888a0', fontSize: 11, cursor: 'pointer',
                        }}
                      >Disconnect</button>
                    </div>
                  </SettingRow>
                ))}
                <div style={{ padding: '12px 20px', borderTop: '1px solid #1a1a26' }}>
                  <button onClick={() => setShowAddBroker(true)} style={{
                    padding: '7px 16px', border: '1px solid #252540', borderRadius: 7,
                    background: 'transparent', color: '#8888a0', fontSize: 12, cursor: 'pointer',
                  }}>+ Add Broker</button>
                </div>
              </>
            )}

            {/* Add Broker Modal */}
            {showAddBroker && (
              <div
                style={{
                  position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
                }}
                onClick={() => setShowAddBroker(false)}
              >
                <div
                  style={{
                    background: '#16161f', border: '1px solid #252540', borderRadius: 12,
                    padding: 28, width: 420, maxWidth: '90vw',
                  }}
                  onClick={(e) => e.stopPropagation()}
                >
                  <h3 style={{ fontSize: 16, fontWeight: 700, color: '#e8e8ef', marginBottom: 20 }}>Connect Broker</h3>

                  <div style={{ marginBottom: 14 }}>
                    <label style={{ fontSize: 12, color: '#8888a0', display: 'block', marginBottom: 5 }}>Broker</label>
                    <select
                      value={brokerForm.broker}
                      onChange={(e) => setBrokerForm((f) => ({ ...f, broker: e.target.value as BrokerConnectRequest['broker'] }))}
                      style={{ width: '100%' }}
                    >
                      {SUPPORTED_BROKERS.map((b) => (
                        <option key={b} value={b}>{BROKER_CAPABILITIES[b].label}</option>
                      ))}
                    </select>
                  </div>

                  <div style={{ marginBottom: 14 }}>
                    <label style={{ fontSize: 12, color: '#8888a0', display: 'block', marginBottom: 5 }}>Label (optional)</label>
                    <input
                      type="text"
                      placeholder="e.g. CFT 5K Challenge"
                      value={brokerForm.label ?? ''}
                      onChange={(e) => setBrokerForm((f) => ({ ...f, label: e.target.value }))}
                      style={{ width: '100%' }}
                    />
                  </div>

                  {brokerForm.broker === 'mt5' ? (
                    <>
                      <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 12, color: '#8888a0', display: 'block', marginBottom: 5 }}>MetaApi Token</label>
                        <input
                          type="password"
                          placeholder="MetaApi API token"
                          value={brokerForm.token ?? ''}
                          onChange={(e) => setBrokerForm((f) => ({ ...f, token: e.target.value }))}
                          style={{ width: '100%' }}
                        />
                        <div style={{ fontSize: 11, color: '#55556a', marginTop: 4 }}>
                          From app.metaapi.cloud — not your broker password.
                        </div>
                      </div>
                      <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 12, color: '#8888a0', display: 'block', marginBottom: 5 }}>MetaApi Account ID</label>
                        <input
                          type="text"
                          placeholder="provisioned account id"
                          value={brokerForm.mt5_account_id ?? ''}
                          onChange={(e) => setBrokerForm((f) => ({ ...f, mt5_account_id: e.target.value }))}
                          style={{ width: '100%' }}
                        />
                        <div style={{ fontSize: 11, color: '#55556a', marginTop: 4 }}>
                          The id MetaApi assigned when you added the account — not your MT5 login number.
                        </div>
                      </div>
                    </>
                  ) : brokerForm.broker === 'cryptofundtrader' ? (
                    <>
                      <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 12, color: '#8888a0', display: 'block', marginBottom: 5 }}>Email</label>
                        <input
                          type="email"
                          placeholder="account email"
                          value={brokerForm.email ?? ''}
                          onChange={(e) => setBrokerForm((f) => ({ ...f, email: e.target.value }))}
                          style={{ width: '100%' }}
                        />
                      </div>
                      <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 12, color: '#8888a0', display: 'block', marginBottom: 5 }}>Password</label>
                        <input
                          type="password"
                          placeholder="account password"
                          value={brokerForm.password ?? ''}
                          onChange={(e) => setBrokerForm((f) => ({ ...f, password: e.target.value }))}
                          style={{ width: '100%' }}
                        />
                      </div>
                      {/* The old placeholder was "https://<host>/mtr-api/<system-uuid>",
                          wrong twice over: the adapter appends /mtr-api/{uuid}
                          itself (following it produced
                          .../mtr-api/x/mtr-api/x/balance — a 404 on every
                          request), and the uuid is DISCOVERED from the login
                          response, never typed. Host only; blank = default. */}
                      <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 12, color: '#8888a0', display: 'block', marginBottom: 5 }}>API Base URL</label>
                        <input
                          type="text"
                          placeholder="https://trading.cryptofundtrader.com (leave blank for default)"
                          value={brokerForm.server ?? ''}
                          onChange={(e) => setBrokerForm((f) => ({ ...f, server: e.target.value }))}
                          style={{ width: '100%' }}
                        />
                        <div style={{ fontSize: 11, color: '#55556a', marginTop: 4 }}>
                          Host only — the rest of the path is added automatically.
                        </div>
                      </div>
                      <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 12, color: '#8888a0', display: 'block', marginBottom: 5 }}>Account ID (optional)</label>
                        <input
                          type="text"
                          placeholder="trading account id"
                          value={brokerForm.account_id ?? ''}
                          onChange={(e) => setBrokerForm((f) => ({ ...f, account_id: e.target.value }))}
                          style={{ width: '100%' }}
                        />
                      </div>
                      <label style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 14, fontSize: 12, color: '#8888a0', cursor: 'pointer' }}>
                        <input
                          type="checkbox"
                          checked={brokerForm.observe_only ?? true}
                          onChange={(e) => setBrokerForm((f) => ({ ...f, observe_only: e.target.checked }))}
                        />
                        Observe-only (no automated orders) — recommended for prop-firm accounts
                      </label>
                    </>
                  ) : (
                    <>
                      <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 12, color: '#8888a0', display: 'block', marginBottom: 5 }}>API Key</label>
                        <input
                          type="password"
                          placeholder="Your API key"
                          value={brokerForm.api_key ?? ''}
                          onChange={(e) => setBrokerForm((f) => ({ ...f, api_key: e.target.value }))}
                          style={{ width: '100%' }}
                        />
                      </div>
                      <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 12, color: '#8888a0', display: 'block', marginBottom: 5 }}>Account ID (optional)</label>
                        <input
                          type="text"
                          placeholder="Your account ID"
                          value={brokerForm.account_id ?? ''}
                          onChange={(e) => setBrokerForm((f) => ({ ...f, account_id: e.target.value }))}
                          style={{ width: '100%' }}
                        />
                      </div>
                    </>
                  )}

                  {(() => {
                    const caps = BROKER_CAPABILITIES[brokerForm.broker as SupportedBroker]
                    if (!caps) return null
                    // A single-environment broker gets a label, not a dropdown: a
                    // "choice" with one option is noise, and offering the others
                    // guarantees a failure (that was the "Practice" bug).
                    return (
                      <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 12, color: '#8888a0', display: 'block', marginBottom: 5 }}>Environment</label>
                        {caps.environments.length > 1 ? (
                          <select
                            value={brokerForm.environment}
                            onChange={(e) => setBrokerForm((f) => ({ ...f, environment: e.target.value as BrokerConnectRequest['environment'] }))}
                            style={{ width: '100%' }}
                          >
                            {caps.environments.map((env) => (
                              <option key={env.value} value={env.value}>{env.label}</option>
                            ))}
                          </select>
                        ) : (
                          <div style={{ fontSize: 12, color: '#e8e8ef', padding: '6px 0' }}>
                            {caps.environments[0].label}
                          </div>
                        )}
                        {caps.envNote && (
                          <div style={{ fontSize: 11, color: '#55556a', marginTop: 4, lineHeight: 1.45 }}>
                            {caps.envNote}
                          </div>
                        )}
                      </div>
                    )
                  })()}

                  {connectError && (
                    <div style={{ fontSize: 12, color: '#ff3b5c', marginBottom: 12, padding: '8px 12px', background: '#ff3b5c15', borderRadius: 6 }}>
                      {connectError}
                    </div>
                  )}

                  <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
                    <button
                      onClick={() => setShowAddBroker(false)}
                      style={{
                        flex: 1, padding: '9px 0', border: '1px solid #252540', borderRadius: 7,
                        background: 'transparent', color: '#8888a0', fontSize: 13, cursor: 'pointer',
                      }}
                    >Cancel</button>
                    <button
                      onClick={handleConnect}
                      disabled={connectLoading}
                      style={{
                        flex: 1, padding: '9px 0', border: 'none', borderRadius: 7,
                        background: connectLoading ? '#6b5fa0' : '#a78bfa', color: '#fff',
                        fontSize: 13, fontWeight: 600, cursor: connectLoading ? 'default' : 'pointer',
                      }}
                    >{connectLoading ? 'Connecting...' : 'Connect'}</button>
                  </div>
                </div>
              </div>
            )}
          </Section>
        )}

        {activeSection === 'ai' && !settings && (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: '#55556a' }}>Loading...</div>
        )}
        {activeSection === 'ai' && settings && (
          <Section title="AI Behavior" description="Configure AI integration and model preferences.">
            <SettingRow label="Enable AI Analysis" description="Allow AI to analyse charts and generate suggestions">
              <Toggle
                checked={settings.ai_enabled}
                onChange={(v) => updateSetting('ai_enabled', v)}
              />
            </SettingRow>
            <SettingRow label="Primary Model" description="Model used for full chart analysis">
              <select
                value={settings.ai_primary_model}
                onChange={(e) => updateSetting('ai_primary_model', e.target.value)}
                style={{ width: 240 }}
              >
                <option value="claude-sonnet-4-6">claude-sonnet-4-6</option>
                <option value="claude-haiku-4-5">claude-haiku-4-5</option>
              </select>
            </SettingRow>
            <SettingRow label="Screening Model" description="Lightweight model used for rapid screening">
              <select
                value={settings.ai_screening_model}
                onChange={(e) => updateSetting('ai_screening_model', e.target.value)}
                style={{ width: 240 }}
              >
                <option value="claude-haiku-4-5">claude-haiku-4-5</option>
              </select>
            </SettingRow>
            <SettingRow label="Monthly Budget ($)" description="Maximum AI spend per calendar month">
              <input
                type="number" min="0" step="1"
                value={settings.ai_monthly_budget_usd}
                onChange={(e) => updateSetting('ai_monthly_budget_usd', Number(e.target.value))}
                style={{ width: 90 }}
              />
            </SettingRow>
            <SettingRow label="Budget Usage" description="AI spend so far this month" last>
              <div style={{ width: 200 }}>
                {(() => {
                  const used = Number(settings.ai_used_current_month_usd)
                  const budget = Number(settings.ai_monthly_budget_usd)
                  const pct = budget > 0 ? Math.min(100, (used / budget) * 100) : 0
                  const color = pct >= 95 ? '#ff3b5c' : pct >= 80 ? '#f59e0b' : '#00d68f'
                  return (
                    <>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                        <span style={{ fontSize: 11, color: '#8888a0' }}>${used.toFixed(2)} / ${budget.toFixed(2)}</span>
                        {pct >= 95 && <span style={{ fontSize: 10, color: '#ff3b5c', fontWeight: 600 }}>Auto-downgrading to Haiku</span>}
                        {pct >= 80 && pct < 95 && <span style={{ fontSize: 10, color: '#f59e0b', fontWeight: 600 }}>Approaching limit</span>}
                      </div>
                      <div style={{ height: 4, background: '#252540', borderRadius: 2, overflow: 'hidden' }}>
                        <div style={{ width: `${pct}%`, height: '100%', background: color, borderRadius: 2, transition: 'width 300ms' }} />
                      </div>
                    </>
                  )
                })()}
              </div>
            </SettingRow>
          </Section>
        )}

        {activeSection === 'risk' && !settings && (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: '#55556a' }}>Loading...</div>
        )}
        {activeSection === 'risk' && settings && (
          <Section title="Risk Defaults" description="Default risk parameters applied to all trades.">
            <SettingRow label="Max Risk per Trade" description="Percentage of account to risk on a single trade">
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input
                  type="number" min="0.1" max="10" step="0.1"
                  value={settings.max_risk_pct}
                  onChange={(e) => updateSetting('max_risk_pct', Number(e.target.value))}
                  style={{ width: 70 }}
                />
                <span style={{ color: '#55556a', fontSize: 13 }}>%</span>
              </div>
            </SettingRow>
            <SettingRow label="Max Daily Loss" description="Stop trading when daily loss hits this threshold">
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input
                  type="number" min="1" max="20" step="0.1"
                  value={settings.max_daily_loss_pct}
                  onChange={(e) => updateSetting('max_daily_loss_pct', Number(e.target.value))}
                  style={{ width: 70 }}
                />
                <span style={{ color: '#55556a', fontSize: 13 }}>%</span>
              </div>
            </SettingRow>
            <SettingRow label="Max Concurrent Positions" description="Maximum number of open positions at any time">
              <input
                type="number" min="1" max="50" step="1"
                value={settings.max_concurrent_positions}
                onChange={(e) => updateSetting('max_concurrent_positions', Number(e.target.value))}
                style={{ width: 80 }}
              />
            </SettingRow>
            <SettingRow label="Require Checklist" description="Force pre-trade checklist before entering a position" last>
              <Toggle
                checked={settings.require_checklist}
                onChange={(v) => updateSetting('require_checklist', v)}
              />
            </SettingRow>
          </Section>
        )}

        {activeSection === 'notifications' && !settings && (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: '#55556a' }}>Loading...</div>
        )}
        {activeSection === 'notifications' && settings && (
          <Section title="Notifications" description="Control how you receive alerts and updates.">
            <SettingRow label="Alert Sound" description="Play a sound when an alert fires">
              <Toggle
                checked={settings.alert_sound}
                onChange={(v) => updateSetting('alert_sound', v)}
              />
            </SettingRow>
            <SettingRow label="Desktop Notifications" description="Show OS-level notifications for alerts">
              <Toggle
                checked={settings.desktop_notifications}
                onChange={(v) => updateSetting('desktop_notifications', v)}
              />
            </SettingRow>
            <SettingRow label="Auto Screenshot on Open" description="Capture chart screenshot when a position opens">
              <Toggle
                checked={settings.auto_screenshot_on_open}
                onChange={(v) => updateSetting('auto_screenshot_on_open', v)}
              />
            </SettingRow>
            <SettingRow label="Screenshot Interval" description="How often to auto-capture screenshots (minutes)" last>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <input
                  type="number" min="1" max="60" step="1"
                  value={settings.auto_screenshot_interval}
                  onChange={(e) => updateSetting('auto_screenshot_interval', Number(e.target.value))}
                  style={{ width: 70 }}
                />
                <span style={{ color: '#55556a', fontSize: 13 }}>min</span>
              </div>
            </SettingRow>
          </Section>
        )}

        {activeSection === 'appearance' && !settings && (
          <div style={{ padding: '40px 20px', textAlign: 'center', color: '#55556a' }}>Loading...</div>
        )}
        {activeSection === 'appearance' && settings && (
          <Section title="Appearance" description="Customize the visual theme." >
            <SettingRow label="Theme" description="Choose between dark and light mode" last>
              <div style={{ display: 'flex', gap: 8 }}>
                {(['dark', 'light'] as const).map((t) => (
                  <button
                    key={t}
                    onClick={() => updateSetting('theme', t)}
                    style={{
                      padding: '6px 16px', border: `1px solid ${settings.theme === t ? '#a78bfa' : '#252540'}`,
                      borderRadius: 6, background: settings.theme === t ? '#a78bfa22' : 'transparent',
                      color: settings.theme === t ? '#a78bfa' : '#8888a0', fontSize: 12, cursor: 'pointer',
                      fontWeight: settings.theme === t ? 600 : 400, textTransform: 'capitalize',
                    }}
                  >{t}</button>
                ))}
              </div>
            </SettingRow>
          </Section>
        )}
      </div>
    </div>
  )
}
