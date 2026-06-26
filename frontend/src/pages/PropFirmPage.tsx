import { useState, useEffect } from 'react'
import { api } from '@/services/api'
import type { PropFirmProfile, PropFirmStatus } from '@/types/api'

function RuleBar({ label, value, limit, color }: { label: string; value: number; limit: number | null; color: string }) {
  const pct = limit && limit > 0 ? Math.min(100, (value / limit) * 100) : 0
  return (
    <div style={{ marginBottom: 14 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
        <span style={{ fontSize: 11, color: '#8888a0' }}>{label}</span>
        <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: pct > 80 ? '#ff3b5c' : '#e8e8ef' }}>
          {value.toFixed(2)}% {limit ? `/ ${limit.toFixed(1)}%` : ''}
        </span>
      </div>
      <div style={{ height: 4, background: '#1a1a26', borderRadius: 2 }}>
        <div style={{
          width: `${pct}%`, height: '100%', borderRadius: 2, transition: 'width 0.3s ease',
          background: pct > 80 ? '#ff3b5c' : pct > 60 ? '#f59e0b' : color,
        }} />
      </div>
    </div>
  )
}

function StatusBadge({ state }: { state: string }) {
  const map: Record<string, { label: string; color: string; bg: string }> = {
    ACTIVE: { label: 'ACTIVE', color: '#00d68f', bg: 'rgba(0,214,143,0.12)' },
    WARNING: { label: 'WARNING', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
    BREACHED: { label: 'BREACHED', color: '#ff3b5c', bg: 'rgba(255,59,92,0.12)' },
    HALTED: { label: 'HALTED', color: '#ff3b5c', bg: 'rgba(255,59,92,0.12)' },
    PASSED: { label: 'PASSED', color: '#00d68f', bg: 'rgba(0,214,143,0.12)' },
  }
  const s = map[state] ?? { label: state, color: '#8888a0', bg: '#1e2035' }
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '3px 8px', borderRadius: 4,
      background: s.bg, color: s.color, letterSpacing: '0.06em',
    }}>
      {s.label}
    </span>
  )
}

// ── Add Profile Modal ──────────────────────────────────────────────────────────

function AddProfileModal({ onClose, onSaved }: { onClose: () => void; onSaved: () => void }) {
  const [firmName, setFirmName] = useState('')
  const [challengeType, setChallengeType] = useState('FUNDED')
  const [accountId, setAccountId] = useState('')
  const [dailyDd, setDailyDd] = useState('5')
  const [maxDd, setMaxDd] = useState('10')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async () => {
    if (!firmName.trim()) { setError('Firm name is required'); return }
    setSaving(true)
    setError(null)
    try {
      await api.propFirm.createProfile({
        firm_name: firmName.trim(),
        challenge_type: challengeType,
        account_id: accountId.trim() || undefined,
        rules_json: {
          daily_dd_pct: parseFloat(dailyDd) || 5,
          max_dd_pct: parseFloat(maxDd) || 10,
        },
      })
      onSaved()
      onClose()
    } catch (e: any) {
      setError(e?.detail ?? 'Failed to save profile')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.7)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 100,
    }} onClick={onClose}>
      <div style={{
        background: '#12121a', border: '1px solid #1e2035', borderRadius: 12,
        padding: 24, width: 400, maxWidth: '90vw',
      }} onClick={(e) => e.stopPropagation()}>
        <h3 style={{ fontSize: 16, fontWeight: 700, color: '#e8e8ef', marginBottom: 20 }}>Add Prop Firm Profile</h3>

        {error && <div style={{ fontSize: 11, color: '#ff3b5c', background: 'rgba(255,59,92,0.1)', padding: '8px 12px', borderRadius: 6, marginBottom: 16 }}>{error}</div>}

        {[
          { label: 'Firm Name', value: firmName, setter: setFirmName, placeholder: 'e.g. FTMO, MyForexFunds' },
          { label: 'Account ID', value: accountId, setter: setAccountId, placeholder: 'Optional broker account ID' },
        ].map(({ label, value, setter, placeholder }) => (
          <div key={label} style={{ marginBottom: 14 }}>
            <label style={{ fontSize: 10, color: '#55556a', fontWeight: 600, letterSpacing: '0.06em', display: 'block', marginBottom: 5 }}>{label.toUpperCase()}</label>
            <input value={value} onChange={(e) => setter(e.target.value)} placeholder={placeholder} style={{ width: '100%', boxSizing: 'border-box' }} />
          </div>
        ))}

        <div style={{ marginBottom: 14 }}>
          <label style={{ fontSize: 10, color: '#55556a', fontWeight: 600, letterSpacing: '0.06em', display: 'block', marginBottom: 5 }}>CHALLENGE TYPE</label>
          <select value={challengeType} onChange={(e) => setChallengeType(e.target.value)} style={{ width: '100%' }}>
            <option value="CHALLENGE">Challenge Phase</option>
            <option value="VERIFICATION">Verification Phase</option>
            <option value="FUNDED">Funded Account</option>
          </select>
        </div>

        <div style={{ display: 'flex', gap: 12, marginBottom: 20 }}>
          {[
            { label: 'Daily DD Limit %', value: dailyDd, setter: setDailyDd },
            { label: 'Max DD Limit %', value: maxDd, setter: setMaxDd },
          ].map(({ label, value, setter }) => (
            <div key={label} style={{ flex: 1 }}>
              <label style={{ fontSize: 10, color: '#55556a', fontWeight: 600, letterSpacing: '0.06em', display: 'block', marginBottom: 5 }}>{label.toUpperCase()}</label>
              <input type="number" value={value} onChange={(e) => setter(e.target.value)} style={{ width: '100%', boxSizing: 'border-box' }} />
            </div>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 10 }}>
          <button onClick={onClose} style={{ flex: 1, padding: '9px 0', borderRadius: 7, border: '1px solid #252540', background: 'transparent', color: '#8888a0', fontSize: 12, cursor: 'pointer' }}>Cancel</button>
          <button onClick={submit} disabled={saving} style={{ flex: 1, padding: '9px 0', borderRadius: 7, border: 'none', background: '#a78bfa', color: '#fff', fontSize: 12, fontWeight: 600, cursor: saving ? 'not-allowed' : 'pointer', opacity: saving ? 0.7 : 1 }}>
            {saving ? 'Saving…' : 'Save Profile'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ─── PropFirmPage ─────────────────────────────────────────────────────────────

export default function PropFirmPage() {
  const [statuses, setStatuses] = useState<PropFirmStatus[]>([])
  const [profiles, setProfiles] = useState<PropFirmProfile[]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [showAdd, setShowAdd] = useState(false)

  const load = async () => {
    setIsLoading(true)
    const [s, p] = await Promise.allSettled([
      api.propFirm.status(),
      api.propFirm.profiles(),
    ])
    setStatuses(s.status === 'fulfilled' && Array.isArray(s.value) ? s.value : [])
    setProfiles(p.status === 'fulfilled' && Array.isArray(p.value) ? p.value : [])
    setIsLoading(false)
  }

  useEffect(() => { load() }, [])

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: '#0a0a0f' }}>
      {showAdd && <AddProfileModal onClose={() => setShowAdd(false)} onSaved={load} />}

      {/* Header */}
      <div style={{ padding: '16px 24px 12px', borderBottom: '1px solid #1e2035', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: '#0d0d14', flexShrink: 0 }}>
        <div>
          <h1 style={{ fontSize: 18, fontWeight: 700, color: '#e8e8ef', marginBottom: 2 }}>Prop Firm Status</h1>
          <span style={{ fontSize: 12, color: '#55556a' }}>Real-time compliance monitoring</span>
        </div>
        <button onClick={() => setShowAdd(true)} style={{
          padding: '7px 16px', border: '1px solid #a78bfa33', borderRadius: 7,
          background: 'rgba(167,139,250,0.08)', color: '#a78bfa', fontSize: 12, cursor: 'pointer',
        }}>
          + Add Profile
        </button>
      </div>

      {/* Content */}
      <div style={{ flex: 1, overflow: 'auto', padding: 24 }}>
        {isLoading ? (
          <div style={{ textAlign: 'center', color: '#55556a', padding: 40 }}>Loading…</div>
        ) : statuses.length === 0 ? (
          <div style={{
            maxWidth: 480, margin: '60px auto', textAlign: 'center',
            background: '#12121a', border: '1px solid #1e2035', borderRadius: 12, padding: '40px 32px',
          }}>
            <div style={{ fontSize: 32, marginBottom: 16 }}>🏢</div>
            <h2 style={{ fontSize: 16, fontWeight: 700, color: '#e8e8ef', marginBottom: 8 }}>No prop firm profiles yet</h2>
            <p style={{ fontSize: 13, color: '#55556a', lineHeight: 1.6, marginBottom: 24 }}>
              Add your prop firm profile to track daily drawdown, maximum drawdown, and compliance state in real time.
            </p>
            <button onClick={() => setShowAdd(true)} style={{
              padding: '10px 24px', borderRadius: 8, border: 'none',
              background: '#a78bfa', color: '#fff', fontSize: 13, fontWeight: 600, cursor: 'pointer',
            }}>
              Add Your First Profile
            </button>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 16 }}>
            {statuses.map((s) => {
              const profile = profiles.find((p) => p.id === s.profile_id)
              const dailyLimitPct = s.daily_loss_limit_pct ? Number(s.daily_loss_limit_pct) : null
              const totalLimitPct = s.total_loss_limit_pct ? Number(s.total_loss_limit_pct) : null
              const equity = Number(s.equity)
              const balance = Number(s.balance)
              const dailyLoss = Number(s.daily_loss)
              const totalLoss = Number(s.total_loss)
              // Convert dollar losses to % of initial balance so the bars compare like-to-like.
              const initialBalance = Number((profile?.rules_json?.initial_balance as number | undefined) ?? balance) || balance || 1
              const dailyLossPct = (dailyLoss / initialBalance) * 100
              const totalLossPct = (totalLoss / initialBalance) * 100

              return (
                <div key={String(s.profile_id)} style={{
                  background: '#12121a', border: '1px solid #1e2035', borderRadius: 12, padding: 20,
                }}>
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
                    <div>
                      <div style={{ fontSize: 15, fontWeight: 700, color: '#e8e8ef' }}>{s.firm_name}</div>
                      {profile?.challenge_type && (
                        <div style={{ fontSize: 10, color: '#55556a', marginTop: 2 }}>{profile.challenge_type}</div>
                      )}
                    </div>
                    <StatusBadge state={s.state} />
                  </div>

                  {/* Account balances */}
                  <div style={{ display: 'flex', gap: 12, marginBottom: 16 }}>
                    {[
                      { label: 'Equity', value: equity },
                      { label: 'Balance', value: balance },
                    ].map(({ label, value }) => (
                      <div key={label} style={{ flex: 1, background: '#0d0d14', borderRadius: 8, padding: '10px 12px' }}>
                        <div style={{ fontSize: 10, color: '#55556a', marginBottom: 4 }}>{label.toUpperCase()}</div>
                        <div style={{ fontSize: 16, fontWeight: 700, fontFamily: 'var(--font-mono)', color: '#e8e8ef' }}>
                          ${value > 0 ? value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) : '—'}
                        </div>
                      </div>
                    ))}
                  </div>

                  {/* Drawdown bars — both value and limit are in percent now */}
                  <RuleBar label="Daily Drawdown" value={dailyLossPct} limit={dailyLimitPct} color="#4f8fff" />
                  <RuleBar label="Total Drawdown" value={totalLossPct} limit={totalLimitPct} color="#a78bfa" />

                  {/* Timestamp */}
                  <div style={{ fontSize: 10, color: '#3a3a50', textAlign: 'right' }}>
                    Updated {new Date(s.timestamp).toLocaleTimeString()}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
