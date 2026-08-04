import { useState, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import { usePositionsStore } from '@/stores/positionsStore'
import { useAlertsStore } from '@/stores/alertsStore'
import { api } from '@/services/api'
import { useLoadState } from '@/hooks/useLoadState'
import { LoadFailure } from '@/components/shared'
import { ChartArea } from '@/components/dashboard/ChartArea'
import { PositionsPanel } from '@/components/dashboard/PositionsPanel'
import { RightRail } from '@/components/dashboard/RightRail'

export default function DashboardPage() {
  const { activePair } = useOutletContext<{ activePair: string; setActivePair: (p: string) => void }>()
  const [timeframe, setTimeframe] = useState('1H')
  const [score, setScore] = useState<number | null>(null)
  const [aiBias, setAiBias] = useState<string | null>(null)
  const { failed, track } = useLoadState()

  useEffect(() => {
    // Try live broker positions first; if empty, fall back to OPEN trades in the
    // journal so the demo + observe-only deployments still show a working panel.
    // Reported as ONE thing because that is how it is read. A live-positions
    // failure alone is survivable — the trades fallback below still describes
    // what is open. Only when BOTH fail does nobody know, and "no open
    // positions" on a trading dashboard is the most dangerous empty state in
    // the app: it is indistinguishable from a flat book (E3).
    const loadPositions = () => track('open positions', (async () => {
      const p = await api.positions.list().catch(() => null)
      if (Array.isArray(p) && p.length > 0) {
        usePositionsStore.getState().setPositions(p)
        return
      }

      // Fallback: synthesise positions from OPEN trades (demo / observe-only mode).
      // Deliberately NOT caught — a failure here is the case worth reporting.
      const trades = await api.trades.list({ page_size: 200 })
      const opens = (Array.isArray(trades) ? trades : []).filter(
        (t: any) => t.status === 'OPEN' || t.outcome === 'OPEN'
      )
      const positions = opens.map((t: any) => {
        const sl = t.sl ?? t.sl_price
        const tp = t.tp ?? t.tp_price
        return {
          id: `trade-${t.id}`,
          broker_id: t.broker_id || 'demo',
          pair: t.pair,
          direction: t.direction,
          lot_size: Number(t.lot_size) || 0,
          entry_price: Number(t.entry_price) || 0,
          current_price: Number(t.entry_price) || 0,
          sl_price: sl !== null && sl !== undefined ? Number(sl) : null,
          tp_price: tp !== null && tp !== undefined ? Number(tp) : null,
          unrealized_pnl: 0,
          unrealized_pips: 0,
          open_time: t.entry_time,
          margin_used: null,
          broker_position_id: null,
        }
      })
      usePositionsStore.getState().setPositions(positions)
    })(), undefined)
    loadPositions()

    track('alerts', api.alerts.list({ status: 'PENDING', per_page: 100 }), [])
      .then((alerts) => useAlertsStore.getState().loadPending(Array.isArray(alerts) ? alerts : []))
  }, [])

  // Fetch latest AI analysis for this pair
  useEffect(() => {
    setScore(null)
    setAiBias(null)
    api.analysis.list({ page_size: 1 })
      .then((items) => {
        const latest = Array.isArray(items) ? items[0] : null
        if (latest) {
          setScore(latest.confidence != null ? Math.round(Number(latest.confidence) * 100) : null)
          setAiBias(latest.trade_bias ?? latest.trend_assessment ?? null)
        }
      })
      .catch(() => {})
  }, [activePair])

  // Load settings on first mount
  useEffect(() => {
    api.settings.get().catch(() => {})
  }, [])

  return (
    <div style={{ display: 'flex', flex: 1, overflow: 'hidden', minHeight: 0 }}>
      {/* Center: chart + positions */}
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, overflow: 'hidden', minWidth: 0 }}>
        {failed.length > 0 && (
          <div style={{ padding: '10px 14px 0' }}><LoadFailure what={failed} /></div>
        )}
        <ChartArea
          pair={activePair}
          timeframe={timeframe}
          onTimeframeChange={setTimeframe}
          score={score}
          aiBias={aiBias}
        />
        <PositionsPanel />
      </div>
      {/* Right rail */}
      <RightRail />
    </div>
  )
}
