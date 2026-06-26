import { useEffect, useRef, useState, useCallback } from 'react' // useState used for screenshotLoading
import {
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  ColorType,
} from 'lightweight-charts'
import { api } from '@/services/api'
import { wsService } from '@/services/ws'
import type { TickData } from '@/types/ws'

const TIMEFRAMES = ['1m', '5m', '15m', '1H', '4H', 'D'] as const

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
  const [screenshotLoading, setScreenshotLoading] = useState(false)

  // ── Create chart on mount ────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return

    const el = containerRef.current

    const chart = createChart(el, {
      layout: {
        background: { type: ColorType.Solid, color: '#0a0a0f' },
        textColor: '#55556a',
        fontSize: 11,
        fontFamily: "'JetBrains Mono', 'SF Mono', ui-monospace, monospace",
      },
      grid: {
        vertLines: { color: '#1a1a26' },
        horzLines: { color: '#1a1a26' },
      },
      crosshair: {
        vertLine: { color: '#4f8fff55', width: 1, style: 1 },
        horzLine: { color: '#4f8fff55', width: 1, style: 1 },
      },
      rightPriceScale: {
        borderColor: '#1e2035',
        textColor: '#55556a',
      },
      timeScale: {
        borderColor: '#1e2035',
        timeVisible: true,
        secondsVisible: false,
      },
      handleScroll: true,
      handleScale: true,
      width: el.clientWidth,
      height: el.clientHeight,
    })

    const series = chart.addCandlestickSeries({
      upColor: '#00d68f',
      downColor: '#ff3b5c',
      borderUpColor: '#00d68f',
      borderDownColor: '#ff3b5c',
      wickUpColor: '#00d68f88',
      wickDownColor: '#ff3b5c88',
    })

    chartRef.current = chart
    seriesRef.current = series

    const ro = new ResizeObserver(() => {
      if (el && chartRef.current) {
        chartRef.current.resize(el.clientWidth, el.clientHeight)
      }
    })
    ro.observe(el)

    return () => {
      ro.disconnect()
      chart.remove()
      chartRef.current = null
      seriesRef.current = null
    }
  }, [])

  // ── Load candles when pair/timeframe changes ─────────────────────────────────
  useEffect(() => {
    if (!seriesRef.current) return

    api.candles
      .list({ pair, timeframe, limit: 500 })
      .then((candles) => {
        if (!seriesRef.current || !candles.length) return
        const data: CandlestickData[] = candles
          .map((c) => ({
            time: (new Date(c.time).getTime() / 1000) as CandlestickData['time'],
            open: c.open,
            high: c.high,
            low: c.low,
            close: c.close,
          }))
          .sort((a, b) => (a.time as number) - (b.time as number))

        seriesRef.current.setData(data)
        chartRef.current?.timeScale().fitContent()
      })
      .catch(() => {
        // Silently fail — chart stays empty
      })
  }, [pair, timeframe])

  // ── Subscribe to live ticks ──────────────────────────────────────────────────
  useEffect(() => {
    const unsub = wsService.on<TickData>('prices', 'tick', (tick) => {
      if (tick.pair !== pair || !seriesRef.current) return
      const now = Math.floor(Date.now() / 1000) as CandlestickData['time']
      const mid = (tick.bid + tick.ask) / 2
      seriesRef.current.update({
        time: now,
        open: mid,
        high: mid,
        low: mid,
        close: mid,
      })
    })
    return unsub
  }, [pair])

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
          try {
            await api.screenshots.upload(formData)
            resolve()
          } catch (err) {
            reject(err)
          }
        }, 'image/png')
      })
    } catch {
      // ignore
    } finally {
      setScreenshotLoading(false)
    }
  }, [pair, timeframe])

  // Score styling
  const scoreColor =
    score === null
      ? '#8888a0'
      : score >= 70
      ? '#00d68f'
      : score >= 40
      ? '#f59e0b'
      : '#ff3b5c'

  const scoreBg =
    score === null
      ? '#1a1a26'
      : score >= 70
      ? 'rgba(0,214,143,0.08)'
      : score >= 40
      ? 'rgba(245,158,11,0.08)'
      : 'rgba(255,59,92,0.08)'

  const scoreBorder =
    score === null
      ? '#252540'
      : score >= 70
      ? 'rgba(0,214,143,0.25)'
      : score >= 40
      ? 'rgba(245,158,11,0.25)'
      : 'rgba(255,59,92,0.25)'

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        flex: 1,
        minHeight: 0,
        background: '#0a0a0f',
      }}
    >
      {/* Toolbar */}
      <div
        style={{
          height: 48,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0 16px',
          background: '#12121a',
          borderBottom: '1px solid #1e2035',
          flexShrink: 0,
          gap: 12,
        }}
      >
        {/* Left: pair name + score */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, minWidth: 0 }}>
          <span
            style={{
              fontSize: 17,
              fontWeight: 700,
              color: '#e8e8ef',
              letterSpacing: '-0.3px',
              whiteSpace: 'nowrap',
            }}
          >
            {pair}
          </span>
          {score !== null && (
            <span
              style={{
                padding: '3px 10px',
                borderRadius: 6,
                fontSize: 11,
                fontWeight: 700,
                background: scoreBg,
                color: scoreColor,
                border: `1px solid ${scoreBorder}`,
                whiteSpace: 'nowrap',
              }}
            >
              Score: <strong>{score}</strong>/100
            </span>
          )}
        </div>

        {/* Center: timeframe pills */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {TIMEFRAMES.map((tf) => {
            const active = timeframe === tf
            return (
              <button
                key={tf}
                onClick={() => onTimeframeChange(tf)}
                style={{
                  padding: '4px 10px',
                  border: 'none',
                  borderRadius: 5,
                  cursor: 'pointer',
                  fontSize: 12,
                  fontWeight: active ? 700 : 400,
                  background: active ? 'rgba(167,139,250,0.12)' : 'transparent',
                  color: active ? '#a78bfa' : '#55556a',
                  borderBottom: `2px solid ${active ? '#a78bfa' : 'transparent'}`,
                  transition: 'all 120ms ease',
                }}
              >
                {tf}
              </button>
            )
          })}
        </div>

        {/* Right: screenshot button */}
        <button
          onClick={handleScreenshot}
          disabled={screenshotLoading}
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: 6,
            padding: '5px 12px',
            border: '1px solid #252540',
            borderRadius: 6,
            background: 'transparent',
            color: '#8888a0',
            fontSize: 12,
            cursor: screenshotLoading ? 'not-allowed' : 'pointer',
            whiteSpace: 'nowrap',
            flexShrink: 0,
            opacity: screenshotLoading ? 0.6 : 1,
          }}
        >
          📷 Screenshot
        </button>
      </div>

      {/* AI bias strip */}
      {aiBias && (
        <div
          style={{
            padding: '5px 16px',
            background: '#13102a',
            borderBottom: '1px solid #2a1f4a',
            display: 'flex',
            alignItems: 'center',
            gap: 8,
            flexShrink: 0,
          }}
        >
          <span style={{ color: '#a78bfa', fontSize: 12, lineHeight: 1 }}>✦</span>
          <span
            style={{
              fontSize: 11,
              color: '#a78bfa',
              fontWeight: 500,
            }}
          >
            AI: {aiBias}
            {score !== null && (
              <span style={{ opacity: 0.7 }}> — {score}/100</span>
            )}
          </span>
        </div>
      )}

      {/* Chart canvas area */}
      <div
        ref={containerRef}
        style={{ flex: 1, minHeight: 0, position: 'relative' }}
      />
    </div>
  )
}
