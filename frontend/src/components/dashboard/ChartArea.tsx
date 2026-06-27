import { useEffect, useRef, useState, useCallback } from 'react'
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type IPriceLine,
  type SeriesMarker,
  type Time,
  type UTCTimestamp,
  ColorType,
  LineStyle,
} from 'lightweight-charts'
import { api } from '@/services/api'
import { wsService } from '@/services/ws'
import type { TickData } from '@/types/ws'

const TIMEFRAMES = ['1m', '5m', '15m', '1H', '4H', 'D'] as const

// The live /api/positions + WS shapes send numbers as strings and use `sl`/`tp`
// (REST) or `sl_price`/`tp_price` (WS). Normalize both into one numeric view.
interface PosView {
  pair: string
  direction: string
  entry: number
  sl: number | null
  tp: number | null
  lot: number
  upnl: number | null
}
const num = (x: unknown): number | null => {
  const n = Number(x)
  return Number.isFinite(n) ? n : null
}
function normalizePos(p: Record<string, unknown>): PosView {
  return {
    pair: String(p.pair),
    direction: String(p.direction),
    entry: Number(p.entry_price),
    sl: num(p.sl ?? p.sl_price),
    tp: num(p.tp ?? p.tp_price),
    lot: Number(p.lot_size ?? 0),
    upnl: num(p.unrealized_pnl),
  }
}

export interface ChartAreaProps {
  pair: string
  timeframe: string
  onTimeframeChange: (tf: string) => void
  score: number | null
  aiBias: string | null
}

export function ChartArea({ pair, timeframe, onTimeframeChange, score, aiBias }: ChartAreaProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const chartRef = useRef<IChartApi | null>(null)
  const seriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null)
  const priceLinesRef = useRef<IPriceLine[]>([])
  const lastPriceRef = useRef<number | null>(null)
  const [screenshotLoading, setScreenshotLoading] = useState(false)
  const [openPos, setOpenPos] = useState<PosView | null>(null)
  const [livePnl, setLivePnl] = useState<number | null>(null)
  const [lastAct, setLastAct] = useState<string | null>(null)
  const [tradeCount, setTradeCount] = useState(0)

  // ── Draw entry / SL / TP lines for open positions on this pair ───────────────
  const drawPositionLines = useCallback((raw: Array<Record<string, unknown>>) => {
    const series = seriesRef.current
    if (!series) return
    priceLinesRef.current.forEach((l) => series.removePriceLine(l))
    priceLinesRef.current = []
    const mine = (Array.isArray(raw) ? raw : []).map(normalizePos).filter((p) => p.pair === pair)
    setOpenPos(mine[0] ?? null)
    for (const p of mine) {
      if (Number.isFinite(p.entry)) priceLinesRef.current.push(series.createPriceLine({
        price: p.entry, color: '#4f8fff', lineWidth: 2, lineStyle: LineStyle.Solid,
        axisLabelVisible: true, title: `ENTRY ${p.direction}`,
      }))
      if (p.sl != null) priceLinesRef.current.push(series.createPriceLine({
        price: p.sl, color: '#ff3b5c', lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: true, title: 'STOP',
      }))
      if (p.tp != null) priceLinesRef.current.push(series.createPriceLine({
        price: p.tp, color: '#00d68f', lineWidth: 1, lineStyle: LineStyle.Dashed,
        axisLabelVisible: true, title: 'TARGET',
      }))
    }
  }, [pair])

  // ── Draw buy/sell entry + exit markers for this pair's trades ─────────────────
  const drawTradeMarkers = useCallback((trades: Array<Record<string, unknown>>) => {
    const series = seriesRef.current
    if (!series) return
    const mine = trades.filter((t) => t.pair === pair)
    setTradeCount(mine.length)
    const markers: SeriesMarker<Time>[] = []
    for (const t of mine) {
      const long = t.direction === 'LONG'
      markers.push({
        time: Math.floor(new Date(t.entry_time).getTime() / 1000) as UTCTimestamp,
        position: long ? 'belowBar' : 'aboveBar',
        color: long ? '#00d68f' : '#ff3b5c',
        shape: long ? 'arrowUp' : 'arrowDown',
        text: long ? 'BUY' : 'SELL',
      })
      if (t.exit_time) {
        const win = t.outcome === 'WIN'
        const r = t.r_multiple != null ? Number(t.r_multiple) : null
        markers.push({
          time: Math.floor(new Date(t.exit_time).getTime() / 1000) as UTCTimestamp,
          position: 'aboveBar',
          color: win ? '#00d68f' : '#ff3b5c',
          shape: 'circle',
          text: r != null ? `${r >= 0 ? '+' : ''}${r.toFixed(1)}R` : (win ? 'TP' : 'SL'),
        })
      }
    }
    markers.sort((a, b) => (a.time as number) - (b.time as number))
    series.setMarkers(markers)
  }, [pair])

  const refreshOverlays = useCallback(() => {
    api.positions.list().then(drawPositionLines).catch(() => {})
    fetch(`/api/trades?pair=${encodeURIComponent(pair)}&page_size=500`)
      .then((r) => r.json())
      .then((ts) => { if (Array.isArray(ts)) drawTradeMarkers(ts) })
      .catch(() => {})
  }, [pair, drawPositionLines, drawTradeMarkers])

  // ── Create chart on mount ────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return
    const el = containerRef.current
    const chart = createChart(el, {
      layout: {
        background: { type: ColorType.Solid, color: '#0a0a0f' },
        textColor: '#55556a', fontSize: 11,
        fontFamily: "'JetBrains Mono', 'SF Mono', ui-monospace, monospace",
      },
      grid: { vertLines: { color: '#1a1a26' }, horzLines: { color: '#1a1a26' } },
      crosshair: {
        vertLine: { color: '#4f8fff55', width: 1, style: 1 },
        horzLine: { color: '#4f8fff55', width: 1, style: 1 },
      },
      rightPriceScale: { borderColor: '#1e2035', textColor: '#55556a' },
      timeScale: { borderColor: '#1e2035', timeVisible: true, secondsVisible: false },
      handleScroll: true, handleScale: true,
      width: el.clientWidth, height: el.clientHeight,
    })
    const series = chart.addCandlestickSeries({
      upColor: '#00d68f', downColor: '#ff3b5c',
      borderUpColor: '#00d68f', borderDownColor: '#ff3b5c',
      wickUpColor: '#00d68f88', wickDownColor: '#ff3b5c88',
    })
    chartRef.current = chart
    seriesRef.current = series
    const ro = new ResizeObserver(() => {
      if (el && chartRef.current) chartRef.current.resize(el.clientWidth, el.clientHeight)
    })
    ro.observe(el)
    return () => {
      ro.disconnect(); chart.remove()
      chartRef.current = null; seriesRef.current = null; priceLinesRef.current = []
    }
  }, [])

  // ── Load candles when pair/timeframe changes, then draw overlays ─────────────
  useEffect(() => {
    if (!seriesRef.current) return
    api.candles
      .list({ pair, timeframe, limit: 500 })
      .then((candles) => {
        if (!seriesRef.current || !candles.length) return
        const data: CandlestickData[] = candles
          .map((c) => ({
            time: (new Date(c.time).getTime() / 1000) as CandlestickData['time'],
            open: c.open, high: c.high, low: c.low, close: c.close,
          }))
          .sort((a, b) => (a.time as number) - (b.time as number))
        seriesRef.current.setData(data)
        chartRef.current?.timeScale().fitContent()
        refreshOverlays()
      })
      .catch(() => {})
  }, [pair, timeframe, refreshOverlays])

  // ── Live: ticks (price), position updates (redraw lines), engine activity ────
  useEffect(() => {
    const unsub = wsService.on<TickData>('prices', 'tick', (tick) => {
      if (tick.pair !== pair || !seriesRef.current) return
      const mid = (tick.bid + tick.ask) / 2
      lastPriceRef.current = mid
      const now = Math.floor(Date.now() / 1000) as CandlestickData['time']
      seriesRef.current.update({ time: now, open: mid, high: mid, low: mid, close: mid })
      setOpenPos((p) => {
        if (p && p.pair === pair && Number.isFinite(p.entry) && p.lot) {
          const diff = p.direction === 'LONG' ? mid - p.entry : p.entry - mid
          setLivePnl(diff * p.lot)
        }
        return p
      })
    })
    const unsubPos = wsService.on('positions', 'update', () => {
      api.positions.list().then(drawPositionLines).catch(() => {})
    })
    const unsubAct = wsService.on<{ kind: string; msg: string }>('system', 'activity', (a) =>
      setLastAct(`${a.kind.toUpperCase()} · ${a.msg}`),
    )
    return () => { unsub(); unsubPos(); unsubAct() }
  }, [pair, drawPositionLines])

  // seed latest engine action
  useEffect(() => {
    fetch('/api/engine/status').then((r) => r.json()).then((d) => {
      const a = Array.isArray(d?.activity) && d.activity[0] ? d.activity[0] : null
      if (a) setLastAct(`${String(a.kind).toUpperCase()} · ${a.msg}`)
    }).catch(() => {})
  }, [])

  // ── Screenshot capture ───────────────────────────────────────────────────────
  const handleScreenshot = useCallback(async () => {
    const canvas = containerRef.current?.querySelector('canvas')
    if (!canvas) return
    setScreenshotLoading(true)
    try {
      await new Promise<void>((resolve, reject) => {
        canvas.toBlob(async (blob) => {
          if (!blob) { reject(new Error('no blob')); return }
          const formData = new FormData()
          formData.append('pair', pair)
          formData.append('timeframe', timeframe)
          formData.append('trigger_type', 'MANUAL')
          formData.append('image', blob, 'chart.png')
          try { await api.screenshots.upload(formData); resolve() } catch (err) { reject(err) }
        }, 'image/png')
      })
    } catch { /* ignore */ } finally { setScreenshotLoading(false) }
  }, [pair, timeframe])

  const scoreColor = score === null ? '#8888a0' : score >= 70 ? '#00d68f' : score >= 40 ? '#f59e0b' : '#ff3b5c'
  const scoreBg = score === null ? '#1a1a26' : score >= 70 ? 'rgba(0,214,143,0.08)' : score >= 40 ? 'rgba(245,158,11,0.08)' : 'rgba(255,59,92,0.08)'
  const scoreBorder = score === null ? '#252540' : score >= 70 ? 'rgba(0,214,143,0.25)' : score >= 40 ? 'rgba(245,158,11,0.25)' : 'rgba(255,59,92,0.25)'

  const isLong = openPos?.direction === 'LONG'
  const pnlVal = livePnl ?? openPos?.upnl ?? null

  return (
    <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, background: '#0a0a0f' }}>
      {/* Toolbar */}
      <div style={{ height: 48, display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '0 16px', background: '#12121a', borderBottom: '1px solid #1e2035', flexShrink: 0, gap: 12 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <span style={{ fontSize: 17, fontWeight: 700, color: '#e8e8ef', letterSpacing: '-0.3px', whiteSpace: 'nowrap' }}>{pair}</span>
          {score !== null && (
            <span style={{ padding: '3px 10px', borderRadius: 6, fontSize: 11, fontWeight: 700, background: scoreBg, color: scoreColor, border: `1px solid ${scoreBorder}`, whiteSpace: 'nowrap' }}>
              Score: <strong>{score}</strong>/100
            </span>
          )}
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {TIMEFRAMES.map((tf) => {
            const active = timeframe === tf
            return (
              <button key={tf} onClick={() => onTimeframeChange(tf)} style={{ padding: '4px 10px', border: 'none', borderRadius: 5, cursor: 'pointer', fontSize: 12, fontWeight: active ? 700 : 400, background: active ? 'rgba(167,139,250,0.12)' : 'transparent', color: active ? '#a78bfa' : '#55556a', borderBottom: `2px solid ${active ? '#a78bfa' : 'transparent'}`, transition: 'all 120ms ease' }}>
                {tf}
              </button>
            )
          })}
        </div>
        <button onClick={handleScreenshot} disabled={screenshotLoading} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px', border: '1px solid #252540', borderRadius: 6, background: 'transparent', color: '#8888a0', fontSize: 12, cursor: screenshotLoading ? 'not-allowed' : 'pointer', whiteSpace: 'nowrap', flexShrink: 0, opacity: screenshotLoading ? 0.6 : 1 }}>
          📷 Screenshot
        </button>
      </div>

      {/* AI bias strip */}
      {aiBias && (
        <div style={{ padding: '5px 16px', background: '#13102a', borderBottom: '1px solid #2a1f4a', display: 'flex', alignItems: 'center', gap: 8, flexShrink: 0 }}>
          <span style={{ color: '#a78bfa', fontSize: 12, lineHeight: 1 }}>✦</span>
          <span style={{ fontSize: 11, color: '#a78bfa', fontWeight: 500 }}>
            AI: {aiBias}{score !== null && <span style={{ opacity: 0.7 }}> — {score}/100</span>}
          </span>
        </div>
      )}

      {/* Chart canvas area + live overlay */}
      <div ref={containerRef} style={{ flex: 1, minHeight: 0, position: 'relative' }}>
        {/* Live trade overlay (top-left) */}
        <div style={{ position: 'absolute', top: 10, left: 10, zIndex: 5, pointerEvents: 'none', display: 'flex', flexDirection: 'column', gap: 6, maxWidth: '70%' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, background: 'rgba(13,13,20,0.85)', border: '1px solid #1e2035', borderRadius: 7, padding: '6px 10px', backdropFilter: 'blur(2px)' }}>
            <span className="pulse-dot" style={{ width: 7, height: 7, borderRadius: '50%', background: '#00d68f', flexShrink: 0 }} />
            <span style={{ fontSize: 10, fontWeight: 700, letterSpacing: '0.06em', color: '#00d68f' }}>LIVE ENGINE</span>
            {openPos ? (
              <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: '#e8e8ef' }}>
                {openPos.pair}{' '}
                <span style={{ color: isLong ? '#00d68f' : '#ff3b5c', fontWeight: 700 }}>{openPos.direction}</span>{' '}
                @ {openPos.entry.toLocaleString()}
                {pnlVal != null && (
                  <span style={{ color: pnlVal >= 0 ? '#00d68f' : '#ff3b5c', fontWeight: 700, marginLeft: 8 }}>
                    {pnlVal >= 0 ? '+' : ''}{Math.round(pnlVal).toLocaleString()} USDT
                  </span>
                )}
              </span>
            ) : (
              <span style={{ fontSize: 11, color: '#8888a0' }}>scanning {pair} — no open trade</span>
            )}
          </div>
          {openPos && (
            <div style={{ display: 'flex', gap: 6 }}>
              <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: '#4f8fff', background: 'rgba(13,13,20,0.85)', border: '1px solid #1e2035', borderRadius: 5, padding: '2px 7px' }}>━ ENTRY {openPos.entry.toLocaleString()}</span>
              {openPos.sl != null && <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: '#ff3b5c', background: 'rgba(13,13,20,0.85)', border: '1px solid #1e2035', borderRadius: 5, padding: '2px 7px' }}>┄ STOP {openPos.sl.toLocaleString()}</span>}
              {openPos.tp != null && <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: '#00d68f', background: 'rgba(13,13,20,0.85)', border: '1px solid #1e2035', borderRadius: 5, padding: '2px 7px' }}>┄ TARGET {openPos.tp.toLocaleString()}</span>}
            </div>
          )}
          {lastAct && (
            <div style={{ fontSize: 10, color: '#8888a0', background: 'rgba(13,13,20,0.85)', border: '1px solid #1e2035', borderRadius: 5, padding: '3px 8px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {lastAct}
            </div>
          )}
          {tradeCount > 0 && (
            <div style={{ fontSize: 10, color: '#55556a', background: 'rgba(13,13,20,0.7)', borderRadius: 5, padding: '2px 8px' }}>
              ▲ BUY / ▼ SELL markers + ● exits ({tradeCount} trades on {pair})
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
