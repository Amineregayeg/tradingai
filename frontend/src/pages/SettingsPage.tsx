import { useState, useEffect } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'
import { api } from '@/services/api'
import type { Settings, BrokerConnection, BrokerConnectRequest } from '@/types/api'

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
  const [showAddBroker, setShowAddBroker] = useState(false)
  const [brokerForm, setBrokerForm] = useState<BrokerConnectRequest>({
    broker: 'oanda',
    api_key: '',
    account_id: '',
    environment: 'practice',
    observe_only: true,
  })
  const [connectLoading, setConnectLoading] = useState(false)
  const [connectError, setConnectError] = useState('')

  useEffect(() => {
    api.brokers.list().then((b) => setBrokers(Array.isArray(b) ? b : [])).catch(() => {})
    if (!settings) api.settings.get().then(setSettings).catch(() => {})
  }, [settings, setSettings])

  const updateSetting = (key: keyof Settings, value: unknown) => {
    if (!settings) return
    const updated = { ...settings, [key]: value }
    setSettings(updated)
    api.settings.update({ [key]: value }).catch(() => {})
  }

  const handleConnect = async () => {
    setConnectLoading(true)
    setConnectError('')
    try {
      const conn = await api.brokers.connect(brokerForm)
      setBrokers((b) => [...b, conn])
      setShowAddBroker(false)
      setBrokerForm({ broker: 'oanda', api_key: '', account_id: '', environment: 'practice', observe_only: true })
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
            {brokers.length === 0 ? (
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
                        onClick={() => api.brokers.disconnect(b.id).then(() => setBrokers((brs) => brs.filter((x) => x.id !== b.id))).catch(() => {})}
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
                      <option value="oanda">OANDA</option>
                      <option value="cryptofundtrader">Crypto Fund Trader</option>
                      <option value="alpaca">Alpaca</option>
                      <option value="metaapi">MetaAPI</option>
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

                  {brokerForm.broker === 'cryptofundtrader' ? (
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
                      <div style={{ marginBottom: 14 }}>
                        <label style={{ fontSize: 12, color: '#8888a0', display: 'block', marginBottom: 5 }}>API Base URL</label>
                        <input
                          type="text"
                          placeholder="https://<host>/mtr-api/<system-uuid>"
                          value={brokerForm.server ?? ''}
                          onChange={(e) => setBrokerForm((f) => ({ ...f, server: e.target.value }))}
                          style={{ width: '100%' }}
                        />
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

                  <div style={{ marginBottom: 14 }}>
                    <label style={{ fontSize: 12, color: '#8888a0', display: 'block', marginBottom: 5 }}>Environment</label>
                    <select
                      value={brokerForm.environment}
                      onChange={(e) => setBrokerForm((f) => ({ ...f, environment: e.target.value as BrokerConnectRequest['environment'] }))}
                      style={{ width: '100%' }}
                    >
                      <option value="practice">Practice</option>
                      <option value="live">Live</option>
                    </select>
                  </div>

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
