import { useState, useEffect } from 'react'
import { useOutletContext } from 'react-router-dom'
import { usePositionsStore } from '@/stores/positionsStore'
import { useAlertsStore } from '@/stores/alertsStore'
import { api } from '@/services/api'
import { ChartArea } from '@/components/dashboard/ChartArea'
import { PositionsPanel } from '@/components/dashboard/PositionsPanel'
import { RightRail } from '@/components/dashboard/RightRail'

export default function DashboardPage() {
  const { activePair } = useOutletContext<{ activePair: string; setActivePair: (p: string) => void }>()
  const [timeframe, setTimeframe] = useState('1H')
  const [score, setScore] = useState<number | null>(null)
  const [aiBias, setAiBias] = useState<string | null>(null)

  useEffect(() => {
    // Try live broker positions first; if empty, fall back to OPEN trades in the
    // journal so the demo + observe-only deployments still show a working panel.
    const loadPositions = async () => {
      try {
        const p = await api.positions.list().catch(() => [])
        if (Array.isArray(p) && p.length > 0) {
          usePositionsStore.getState().setPositions(p)
          return
        }
      } catch { /* fall through */ }

      // Fallback: synthesise positions from OPEN trades (demo / observe-only mode).
      const trades = await api.trades.list({ per_page: 200 }).catch(() => [])
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
    }
    loadPositions()

    api.alerts.list({ status: 'PENDING', per_page: 100 })
      .then((alerts) => useAlertsStore.getState().loadPending(Array.isArray(alerts) ? alerts : []))
      .catch(() => {})
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
