import { useState, useEffect } from 'react'
import { api } from '@/services/api'

interface CheckItem {
  id: string
  label: string
  category: 'bias' | 'risk' | 'timing' | 'setup'
}

const DEFAULT_ITEMS: CheckItem[] = [
  { id: 'htf-bias', label: 'Identified higher timeframe (D/4H) market bias', category: 'bias' },
  { id: 'liquidity', label: 'Located key liquidity pools above/below price', category: 'bias' },
  { id: 'pois', label: 'Marked Points of Interest (OB, FVG, Breaker)', category: 'bias' },
  { id: 'session', label: 'Confirmed active session (London / NY overlap)', category: 'timing' },
  { id: 'no-news', label: 'Checked high-impact news — no immediate event', category: 'timing' },
  { id: 'kill-zones', label: 'Entry within ICT kill-zone (London 7–9, NY 13–16)', category: 'timing' },
  { id: 'risk-pct', label: 'Max risk per trade set (≤1% of account)', category: 'risk' },
  { id: 'daily-dd', label: 'Daily drawdown limit has not been hit today', category: 'risk' },
  { id: 'position-limit', label: 'Open positions within prop firm limits', category: 'risk' },
  { id: 'entry-model', label: 'Entry model confirmed (MSS, BOS, Inducement swept)', category: 'setup' },
  { id: 'sl-placed', label: 'Stop Loss placed beyond last swing / structure', category: 'setup' },
  { id: 'rr-ratio', label: 'Minimum 1:2 R:R confirmed before entry', category: 'setup' },
]

const CATEGORY_LABELS: Record<CheckItem['category'], string> = {
  bias: 'Market Bias',
  timing: 'Timing',
  risk: 'Risk Management',
  setup: 'Entry Setup',
}

const CATEGORY_COLORS: Record<CheckItem['category'], string> = {
  bias: '#4f8fff',
  timing: '#f59e0b',
  risk: '#ff3b5c',
  setup: '#00d68f',
}

const STORAGE_KEY = 'tradingai_checklist_date'
const CHECKS_KEY = 'tradingai_checklist_checks'

export default function ChecklistPage() {
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [maxRiskPct, setMaxRiskPct] = useState<number | null>(null)

  // Reset checklist daily
  useEffect(() => {
    const today = new Date().toDateString()
    const storedDate = localStorage.getItem(STORAGE_KEY)
    if (storedDate === today) {
      try {
        const saved = JSON.parse(localStorage.getItem(CHECKS_KEY) ?? '{}')
        setChecked(saved)
      } catch { /* ignore */ }
    } else {
      setChecked({})
      localStorage.setItem(STORAGE_KEY, today)
      localStorage.removeItem(CHECKS_KEY)
    }
  }, [])

  // Load risk settings
  useEffect(() => {
    api.settings.get()
      .then((s) => setMaxRiskPct(s.max_risk_pct))
      .catch(() => {})
  }, [])

  const toggle = (id: string) => {
    setChecked((prev) => {
      const next = { ...prev, [id]: !prev[id] }
      localStorage.setItem(CHECKS_KEY, JSON.stringify(next))
      return next
    })
  }

  const completedCount = Object.values(checked).filter(Boolean).length
  const total = DEFAULT_ITEMS.length
  const pct = Math.round((completedCount / total) * 100)
  const allDone = completedCount === total

  const categories = ['bias', 'timing', 'risk', 'setup'] as CheckItem['category'][]

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', background: '#0a0a0f' }}>
      {/* Header */}
      <div style={{ padding: '16px 24px 12px', borderBottom: '1px solid #1e2035', background: '#0d0d14', flexShrink: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div>
            <h1 style={{ fontSize: 18, fontWeight: 700, color: '#e8e8ef', marginBottom: 2 }}>Pre-Trade Checklist</h1>
            <span style={{ fontSize: 12, color: '#55556a' }}>Resets daily at midnight — {completedCount}/{total} complete</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 28, fontWeight: 700, fontFamily: 'var(--font-mono)', color: allDone ? '#00d68f' : '#e8e8ef' }}>{pct}%</div>
            </div>
            {allDone && (
              <div style={{ padding: '6px 14px', borderRadius: 8, background: 'rgba(0,214,143,0.12)', border: '1px solid rgba(0,214,143,0.3)', color: '#00d68f', fontSize: 12, fontWeight: 600 }}>
                ✓ Ready to trade
              </div>
            )}
          </div>
        </div>
        {/* Progress bar */}
        <div style={{ height: 3, background: '#1a1a26', borderRadius: 2, marginTop: 12 }}>
          <div style={{ width: `${pct}%`, height: '100%', borderRadius: 2, background: allDone ? '#00d68f' : '#a78bfa', transition: 'width 0.3s ease' }} />
        </div>
      </div>

      {/* Risk context banner */}
      {maxRiskPct !== null && (
        <div style={{ padding: '10px 24px', background: 'rgba(79,143,255,0.05)', borderBottom: '1px solid #1e2035', fontSize: 12, color: '#4f8fff', flexShrink: 0 }}>
          ⚡ Max risk per trade from settings: <strong>{maxRiskPct}%</strong> of account
        </div>
      )}

      {/* Checklist */}
      <div style={{ flex: 1, overflow: 'auto', padding: '20px 24px' }}>
        <div style={{ maxWidth: 640 }}>
          {categories.map((cat) => {
            const items = DEFAULT_ITEMS.filter((i) => i.category === cat)
            const catColor = CATEGORY_COLORS[cat]
            return (
              <div key={cat} style={{ marginBottom: 28 }}>
                <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.1em', color: catColor, marginBottom: 10 }}>
                  {CATEGORY_LABELS[cat].toUpperCase()}
                </div>
                {items.map((item) => {
                  const done = Boolean(checked[item.id])
                  return (
                    <label key={item.id} style={{
                      display: 'flex', alignItems: 'center', gap: 12, padding: '11px 14px',
                      borderRadius: 8, marginBottom: 6, cursor: 'pointer',
                      background: done ? 'rgba(0,214,143,0.04)' : '#12121a',
                      border: `1px solid ${done ? 'rgba(0,214,143,0.2)' : '#1e2035'}`,
                      transition: 'all 150ms ease',
                    }}>
                      <div style={{
                        width: 18, height: 18, borderRadius: 5, flexShrink: 0,
                        border: `2px solid ${done ? '#00d68f' : '#2a2a40'}`,
                        background: done ? '#00d68f' : 'transparent',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        transition: 'all 150ms ease',
                      }}>
                        {done && <span style={{ color: '#000', fontSize: 11, fontWeight: 700 }}>✓</span>}
                      </div>
                      <span style={{
                        fontSize: 12, lineHeight: 1.4, flex: 1,
                        color: done ? '#55556a' : '#e8e8ef',
                        textDecoration: done ? 'line-through' : 'none',
                      }}>
                        {item.label}
                      </span>
                      <input
                        type="checkbox"
                        checked={done}
                        onChange={() => toggle(item.id)}
                        style={{ display: 'none' }}
                      />
                    </label>
                  )
                })}
              </div>
            )
          })}

          {/* Reset button */}
          <button
            onClick={() => {
              setChecked({})
              localStorage.removeItem(CHECKS_KEY)
            }}
            style={{
              padding: '8px 18px', borderRadius: 7, border: '1px solid #252540',
              background: 'transparent', color: '#55556a', fontSize: 12, cursor: 'pointer', marginTop: 8,
            }}
          >
            Reset checklist
          </button>
        </div>
      </div>
    </div>
  )
}
