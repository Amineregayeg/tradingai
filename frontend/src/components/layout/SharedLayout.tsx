import { Outlet } from 'react-router-dom'
import { useState, useCallback } from 'react'
import { TopNav } from './TopNav'
import { Sidebar } from './Sidebar'

export function SharedLayout() {
  const [activePair, setActivePair] = useState('BTC/USD')
  const handlePairSelect = useCallback((pair: string) => setActivePair(pair), [])

  return (
    <div style={{
      display: 'flex', flexDirection: 'column',
      height: '100vh', background: '#0a0a0f', overflow: 'hidden',
    }}>
      <TopNav />
      <div style={{ display: 'flex', flex: 1, overflow: 'hidden', minHeight: 0 }}>
        <Sidebar activePair={activePair} onPairSelect={handlePairSelect} />
        {/* Page content fills remaining space */}
        <div style={{ flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minWidth: 0 }}>
          <Outlet context={{ activePair, setActivePair }} />
        </div>
      </div>
    </div>
  )
}
