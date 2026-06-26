import { useNavigate, useLocation } from 'react-router-dom'
import { useState, useEffect } from 'react'
import { usePricesStore } from '@/stores/pricesStore'
import { formatPrice } from '@/utils/format'

const NAV_ITEMS = [
  { key: 'D', label: 'Dashboard', path: '/' },
  { key: 'J', label: 'Trade Journal', path: '/journal' },
  { key: 'P', label: 'Prop Firm Status', path: '/prop-firm' },
  { key: 'S', label: 'Settings', path: '/settings' },
]

const DISPLAY_PAIRS = ['BTC/USD', 'ETH/USD', 'SOL/USD']

// ─── Session info hook ─────────────────────────────────────────────────────────

function useSessionInfo() {
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 1000)
    return () => clearInterval(t)
  }, [])

  const h = now.getUTCHours()
  const m = now.getUTCMinutes()
  const s = now.getUTCSeconds()

  let session = 'OFF-HOURS'
  let sessionColor = '#55556a'
  let startH = 22
  let endH = 7 // wraps around midnight
  let isOvernight = true

  if (h >= 7 && h < 13) {
    session = 'LONDON SESSION'
    sessionColor = '#f59e0b'
    startH = 7
    endH = 13
    isOvernight = false
  } else if (h >= 13 && h < 17) {
    session = 'NY/LONDON OVERLAP'
    sessionColor = '#f59e0b'
    startH = 13
    endH = 17
    isOvernight = false
  } else if (h >= 17 && h < 22) {
    session = 'NEW YORK SESSION'
    sessionColor = '#4f8fff'
    startH = 17
    endH = 22
    isOvernight = false
  } else if (h >= 22 || h < 7) {
    session = 'ASIAN SESSION'
    sessionColor = '#a78bfa'
    startH = 22
    endH = 31 // 22+9=31 (next day 7:00)
    isOvernight = true
  }

  const totalMins = (isOvernight ? endH - startH : endH - startH) * 60
  const currentMins = isOvernight
    ? h >= 22
      ? (h - startH) * 60 + m
      : (h + 24 - startH) * 60 + m
    : (h - startH) * 60 + m
  const pct = Math.min(100, Math.max(0, (currentMins / totalMins) * 100))

  // Countdown to session end
  const endHNorm = isOvernight ? endH % 24 : endH
  const endMins = endHNorm * 60
  const currMins = h * 60 + m
  let minsLeft = endMins - currMins
  if (minsLeft < 0) minsLeft += 24 * 60
  const hLeft = Math.floor(minsLeft / 60)
  const mLeft = minsLeft % 60
  const sLeft = s === 0 ? 0 : 60 - s

  const pad = (n: number) => String(n).padStart(2, '0')
  const countdown = `${pad(hLeft)}:${pad(mLeft)}:${pad(sLeft)}`
  const startStr = `${pad(startH % 24)}:00`
  const endStr = `${pad(endHNorm)}:00`

  return { session, sessionColor, pct, countdown, startStr, endStr }
}

// ─── Sidebar component ─────────────────────────────────────────────────────────

interface SidebarProps {
  activePair: string
  onPairSelect: (pair: string) => void
}

export function Sidebar({ activePair, onPairSelect }: SidebarProps) {
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const ticks = usePricesStore((s) => s.ticks)
  const { session, sessionColor, pct, countdown, startStr, endStr } = useSessionInfo()

  const isNavActive = (path: string) => {
    if (path === '/') return pathname === '/'
    return pathname.startsWith(path)
  }

  return (
    <aside
      style={{
        width: 164,
        flexShrink: 0,
        background: '#0d0d14',
        borderRight: '1px solid #1e2035',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        overflow: 'hidden',
      }}
    >
      {/* Brand + Session block */}
      <div style={{ padding: '14px 14px 0', flexShrink: 0 }}>
        {/* Brand */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 14 }}>
          <div
            className="pulse-dot"
            style={{
              width: 7,
              height: 7,
              borderRadius: '50%',
              background: '#00d68f',
              flexShrink: 0,
            }}
          />
          <span style={{ fontSize: 14, fontWeight: 700, letterSpacing: '-0.2px', color: '#e8e8ef' }}>
            Trading <span style={{ color: '#00d68f' }}>AI</span>
          </span>
        </div>

        {/* Session name */}
        <div
          style={{
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: '0.09em',
            color: sessionColor,
            marginBottom: 2,
          }}
        >
          {session}
        </div>

        {/* Time range */}
        <div style={{ fontSize: 10, color: '#55556a', marginBottom: 6 }}>
          {startStr} — {endStr} GMT
        </div>

        {/* Progress bar */}
        <div
          style={{
            height: 3,
            background: '#1a1a26',
            borderRadius: 2,
            marginBottom: 6,
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              width: `${pct}%`,
              height: '100%',
              background: sessionColor,
              borderRadius: 2,
              transition: 'width 1s linear',
            }}
          />
        </div>

        {/* Countdown */}
        <div
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: 13,
            color: '#e8e8ef',
            fontWeight: 600,
            marginBottom: 4,
          }}
        >
          {countdown}
        </div>
      </div>

      {/* Nav items */}
      <nav style={{ flex: 1, padding: '10px 0', overflowY: 'auto' }}>
        {NAV_ITEMS.map((item) => {
          const active = isNavActive(item.path)
          return (
            <button
              key={item.key}
              onClick={() => navigate(item.path)}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                width: '100%',
                padding: '7px 14px',
                border: 'none',
                cursor: 'pointer',
                textAlign: 'left',
                background: active ? '#1a1a26' : 'transparent',
                borderLeft: `2px solid ${active ? '#00d68f' : 'transparent'}`,
                color: active ? '#e8e8ef' : '#55556a',
                fontSize: 12,
                fontWeight: active ? 600 : 400,
                transition: 'all 100ms ease',
              }}
            >
              {/* Key badge */}
              <span
                style={{
                  width: 16,
                  height: 16,
                  borderRadius: 4,
                  background: active ? 'rgba(0,214,143,0.12)' : '#1a1a26',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: 9,
                  fontWeight: 700,
                  color: active ? '#00d68f' : '#55556a',
                  flexShrink: 0,
                  lineHeight: 1,
                }}
              >
                {item.key}
              </span>
              <span
                style={{
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  fontSize: 11,
                }}
              >
                {item.label}
              </span>
            </button>
          )
        })}
      </nav>

      {/* Active Pairs section */}
      <div
        style={{
          padding: '10px 14px 14px',
          borderTop: '1px solid #1e2035',
          flexShrink: 0,
        }}
      >
        <div
          style={{
            fontSize: 9,
            fontWeight: 700,
            letterSpacing: '0.1em',
            color: '#55556a',
            marginBottom: 8,
          }}
        >
          ACTIVE PAIRS
        </div>

        {DISPLAY_PAIRS.map((pair) => {
          const tick = ticks[pair]
          const mid = tick ? (tick.bid + tick.ask) / 2 : null
          const decimals = 2  // crypto (BTC/ETH/SOL in USD)
          const isActive = pair === activePair

          return (
            <button
              key={pair}
              onClick={() => onPairSelect(pair)}
              style={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
                width: '100%',
                padding: '5px 0',
                border: 'none',
                cursor: 'pointer',
                background: 'transparent',
              }}
            >
              <span
                style={{
                  fontSize: 11,
                  fontWeight: isActive ? 700 : 400,
                  color: isActive ? '#e8e8ef' : '#8888a0',
                }}
              >
                {pair}
              </span>
              <div style={{ textAlign: 'right' }}>
                <div
                  style={{
                    fontSize: 11,
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                    color: '#00d68f',
                    lineHeight: 1.3,
                  }}
                >
                  {mid ? formatPrice(mid, decimals) : '—'}
                </div>
              </div>
            </button>
          )
        })}
      </div>
    </aside>
  )
}
