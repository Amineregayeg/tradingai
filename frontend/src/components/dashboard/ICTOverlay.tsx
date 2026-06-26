import { useEffect, useImperativeHandle, forwardRef, useRef } from 'react'
import type { IChartApi, ISeriesApi, IPriceLine } from 'lightweight-charts'
import { wsService } from '@/services/ws'
import { api } from '@/services/api'
import type { ICTDetection } from '@/types/api'
import type { ICTNewData, ICTMitigatedData } from '@/types/ws'

export interface ICTOverlayProps {
  chart: IChartApi | null
  pair: string
  timeframe: string
}

export interface ICTOverlayHandle {
  refresh: () => void
}

// Colors for each ICT type
const ICT_COLORS: Record<string, string> = {
  OB: '#f59e0b',     // amber
  FVG: '#34d399',    // green
  LIQ: '#ef4444',    // red
  BOS: '#4f8fff',    // blue
  CHOCH: '#4f8fff',  // blue
  SFP: '#a78bfa',    // purple
  BREAKER: '#f59e0b',
  SD_ZONE: '#22d3ee',
}

interface PriceLineEntry {
  line: IPriceLine
  seriesRef: ISeriesApi<'Candlestick'>
}

/**
 * ICTOverlay renders ICT detections as price lines on the lightweight-charts instance.
 * The chart series reference is obtained from the parent via the chart prop.
 */
export const ICTOverlay = forwardRef<ICTOverlayHandle, ICTOverlayProps>(
  function ICTOverlay({ chart, pair, timeframe }, ref) {
    // Map detection id → price line entries
    const linesRef = useRef<Map<string, PriceLineEntry[]>>(new Map())
    const detectionsRef = useRef<Map<string, ICTDetection>>(new Map())

    const addDetection = (detection: ICTDetection, series: ISeriesApi<'Candlestick'>) => {
      if (!series) return
      const color = ICT_COLORS[detection.type] ?? '#8888a0'
      const lines: PriceLineEntry[] = []

      const makeEntry = (price: number, label: string, style: number): PriceLineEntry => ({
        line: series.createPriceLine({
          price,
          color,
          lineWidth: 1,
          lineStyle: style,
          axisLabelVisible: true,
          title: label,
        }),
        seriesRef: series,
      })

      // Render based on type
      if (detection.type === 'LIQ') {
        const p = detection.low_price ?? detection.high_price
        if (p != null) {
          lines.push(makeEntry(p, `LIQ ${detection.direction}`, 2 /* Dashed */))
        }
      } else if (detection.type === 'BOS' || detection.type === 'CHOCH') {
        const p = detection.high_price ?? detection.low_price
        if (p != null) {
          lines.push(makeEntry(p, detection.type, 0 /* Solid */))
        }
      } else {
        // OB, FVG, BREAKER, SD_ZONE, SFP — show high and low band
        if (detection.high_price != null) {
          lines.push(makeEntry(detection.high_price, `${detection.type} H`, 1 /* Dotted */))
        }
        if (detection.low_price != null) {
          lines.push(makeEntry(detection.low_price, `${detection.type} L`, 1 /* Dotted */))
        }
      }

      linesRef.current.set(detection.id, lines)
      detectionsRef.current.set(detection.id, detection)
    }

    const removeDetection = (id: string, _series: ISeriesApi<'Candlestick'> | null) => {
      const entries = linesRef.current.get(id)
      if (!entries) return
      for (const entry of entries) {
        try {
          entry.seriesRef.removePriceLine(entry.line)
        } catch {
          // Line may already be removed
        }
      }
      linesRef.current.delete(id)
      detectionsRef.current.delete(id)
    }

    const clearAll = (series: ISeriesApi<'Candlestick'> | null) => {
      for (const [id] of linesRef.current) {
        removeDetection(id, series)
      }
    }

    // Get the candlestick series from chart
    const getFirstSeries = (): ISeriesApi<'Candlestick'> | null => {
      if (!chart) return null
      try {
        // lightweight-charts v4 exposes getSeries() - try both APIs
        const c = chart as unknown as { getSeries?: () => ISeriesApi<'Candlestick'>[] }
        const all = c.getSeries?.()
        return all?.[0] ?? null
      } catch {
        return null
      }
    }

    // Load initial detections
    const loadDetections = () => {
      const series = getFirstSeries()
      if (!series || !chart) return

      clearAll(series)

      api.ict
        .detections({ pair, timeframe: timeframe as ICTDetection['timeframe'], status: 'ACTIVE' })
        .then((res) => {
          const currentSeries = getFirstSeries()
          if (!currentSeries) return
          for (const d of res) {
            addDetection(d, currentSeries)
          }
        })
        .catch(() => {})
    }

    useImperativeHandle(ref, () => ({
      refresh: loadDetections,
    }))

    // Load when chart/pair/timeframe changes
    useEffect(() => {
      if (!chart) return
      // Small delay to let chart initialize series
      const timer = setTimeout(loadDetections, 200)
      return () => clearTimeout(timer)
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [chart, pair, timeframe])

    // Subscribe to WS ICT events
    useEffect(() => {
      const unsubNew = wsService.on<ICTNewData>('ict', 'detected', (data) => {
        const d = data.detection
        if (d.pair !== pair || d.timeframe !== timeframe) return
        const series = getFirstSeries()
        if (!series) return
        addDetection(d, series)
      })

      const unsubMit = wsService.on<ICTMitigatedData>('ict', 'mitigated', (data) => {
        const series = getFirstSeries()
        removeDetection(data.detection_id, series)
      })

      return () => {
        unsubNew()
        unsubMit()
      }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [pair, timeframe, chart])

    // Clean up on unmount
    useEffect(() => {
      return () => {
        clearAll(getFirstSeries())
      }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    // This component renders no DOM — it only operates on the chart API
    return null
  }
)
