import { useNavigate, useLocation } from 'react-router-dom'

const TABS = [
  { label: 'Dashboard', path: '/' },
]

const RIGHT_TABS: { label: string; path: string }[] = []

export function TopNav() {
  const navigate = useNavigate()
  const { pathname } = useLocation()

  const isActive = (path: string) => pathname === path

  return (
    <header
      style={{
        height: 48,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '0 20px',
        background: '#0d0d14',
        borderBottom: '1px solid #1e2035',
        flexShrink: 0,
        zIndex: 200,
        position: 'relative',
      }}
    >
      {/* Brand */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, minWidth: 160 }}>
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
        <span style={{ fontSize: 15, fontWeight: 700, letterSpacing: '-0.3px', color: '#e8e8ef' }}>
          Trading <span style={{ color: '#00d68f' }}>AI</span>
        </span>
      </div>

      {/* Center: Tabs */}
      <nav style={{ display: 'flex', alignItems: 'center', gap: 2 }}>
        {TABS.map((tab) => {
          const active = isActive(tab.path)
          return (
            <button
              key={tab.path}
              onClick={() => navigate(tab.path)}
              style={{
                padding: '5px 14px',
                borderRadius: 6,
                border: 'none',
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: active ? 600 : 400,
                background: active ? '#e8e8ef' : 'transparent',
                color: active ? '#0a0a0f' : '#8888a0',
                transition: 'all 150ms ease',
              }}
            >
              {tab.label}
            </button>
          )
        })}

        <div style={{ width: 16 }} />

        {RIGHT_TABS.map((tab) => {
          const active = isActive(tab.path)
          return (
            <button
              key={tab.path}
              onClick={() => navigate(tab.path)}
              style={{
                padding: '5px 14px',
                borderRadius: 6,
                border: 'none',
                cursor: 'pointer',
                fontSize: 13,
                fontWeight: active ? 600 : 400,
                background: active ? '#e8e8ef' : 'transparent',
                color: active ? '#0a0a0f' : '#8888a0',
                transition: 'all 150ms ease',
              }}
            >
              {tab.label}
            </button>
          )
        })}
      </nav>

      {/* User chip */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 10,
          minWidth: 160,
          justifyContent: 'flex-end',
        }}
      >
        <div
          style={{
            width: 28,
            height: 28,
            borderRadius: '50%',
            background: '#2d1f5e',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 11,
            fontWeight: 700,
            color: '#a78bfa',
            border: '1px solid #4a3a7a',
            flexShrink: 0,
          }}
        >
          MZ
        </div>
        <span style={{ fontSize: 13, color: '#8888a0' }}>Moez</span>
      </div>
    </header>
  )
}
