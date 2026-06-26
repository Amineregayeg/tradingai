import type { WSChannel, WSMessage } from '@/types/ws'
import { useWSStore } from '@/stores/wsStore'
import { usePositionsStore } from '@/stores/positionsStore'
import { useAlertsStore } from '@/stores/alertsStore'
import { usePricesStore } from '@/stores/pricesStore'
import { api } from './api'

// ─── Types ───────────────────────────────────────────────────────────────────

export type WSHandler<T = unknown> = (data: T, event: string) => void

type HandlerKey = `${WSChannel}:${string}` | `${WSChannel}:*`

// ─── WebSocket Service ────────────────────────────────────────────────────────

const MAX_RECONNECT_DELAY = 30_000
const INITIAL_RECONNECT_DELAY = 1_000

export class WebSocketService {
  private ws: WebSocket | null = null
  private handlers: Map<HandlerKey, WSHandler[]> = new Map()
  private reconnectDelay = INITIAL_RECONNECT_DELAY
  private pingInterval: ReturnType<typeof setInterval> | null = null
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private intentionalClose = false

  // ── Public API ────────────────────────────────────────────────────────────

  connect(): void {
    if (this.ws && this.ws.readyState === WebSocket.OPEN) return
    this.intentionalClose = false
    this._connect()
  }

  disconnect(): void {
    this.intentionalClose = true
    this._clearTimers()
    if (this.ws) {
      this.ws.close(1000, 'client disconnect')
      this.ws = null
    }
    useWSStore.getState().setStatus('disconnected')
  }

  /**
   * Subscribe to a channel+event combination.
   * Use '*' as the event to receive all events on a channel.
   * Returns an unsubscribe function.
   */
  on<T = unknown>(channel: WSChannel, event: string, handler: WSHandler<T>): () => void {
    const key: HandlerKey = `${channel}:${event}`
    const list = this.handlers.get(key) ?? []
    list.push(handler as WSHandler)
    this.handlers.set(key, list)
    return () => {
      const current = this.handlers.get(key) ?? []
      const next = current.filter((h) => h !== handler)
      if (next.length === 0) {
        this.handlers.delete(key)
      } else {
        this.handlers.set(key, next)
      }
    }
  }

  // ── Private ───────────────────────────────────────────────────────────────

  private _connect(): void {
    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const url = `${protocol}://${window.location.host}/ws`

    useWSStore.getState().setStatus('connecting')

    try {
      this.ws = new WebSocket(url)
    } catch {
      this._scheduleReconnect()
      return
    }

    this.ws.onopen = () => {
      useWSStore.getState().setStatus('connected')
      useWSStore.getState().resetReconnects()
      this.reconnectDelay = INITIAL_RECONNECT_DELAY
      this._startPing()
      this._onReconnect()
    }

    this.ws.onmessage = (event: MessageEvent<string>) => {
      try {
        const msg = JSON.parse(event.data) as WSMessage
        this._handleMessage(msg)
      } catch {
        // ignore malformed messages
      }
    }

    this.ws.onclose = (event) => {
      this._clearTimers()
      if (!this.intentionalClose) {
        useWSStore.getState().setStatus('disconnected')
        this._scheduleReconnect()
      }
      // Close code 1000 = normal closure
      if (event.code !== 1000) {
        console.warn(`[WS] Closed with code ${event.code}: ${event.reason}`)
      }
    }

    this.ws.onerror = () => {
      // onerror is always followed by onclose; handle reconnect there
    }
  }

  private _handleMessage(msg: WSMessage): void {
    // Handle server ping — reply with pong
    if (msg.channel === 'system' && msg.event === 'ping') {
      this._send({ channel: 'system', event: 'pong', data: { ts: Date.now() } })
    }

    // Route to specific event handlers
    const specificKey: HandlerKey = `${msg.channel}:${msg.event}`
    const wildcardKey: HandlerKey = `${msg.channel}:*`

    const specificHandlers = this.handlers.get(specificKey) ?? []
    const wildcardHandlers = this.handlers.get(wildcardKey) ?? []

    for (const handler of [...specificHandlers, ...wildcardHandlers]) {
      try {
        handler(msg.data, msg.event)
      } catch (err) {
        console.error('[WS] Handler error', err)
      }
    }
  }

  private _scheduleReconnect(): void {
    if (this.intentionalClose) return
    useWSStore.getState().incrementReconnects()

    this.reconnectTimer = setTimeout(() => {
      this._connect()
    }, this.reconnectDelay)

    // Exponential backoff: 1 → 2 → 4 → 8 → 16 → 30 (capped)
    this.reconnectDelay = Math.min(this.reconnectDelay * 2, MAX_RECONNECT_DELAY)
  }

  private _startPing(): void {
    this._clearPing()
    // Server sends ping every 30s; we also send our own keepalive
    this.pingInterval = setInterval(() => {
      this._send({ channel: 'system', event: 'ping', data: { ts: Date.now() } })
    }, 25_000)
  }

  private _clearPing(): void {
    if (this.pingInterval !== null) {
      clearInterval(this.pingInterval)
      this.pingInterval = null
    }
  }

  private _clearTimers(): void {
    this._clearPing()
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
  }

  private _send(msg: object): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(msg))
    }
  }

  /**
   * Called after a successful reconnect to re-fetch volatile state.
   */
  private _onReconnect(): void {
    // Re-fetch positions; only overwrite the store when we get a non-empty list
    // (avoids stomping the dashboard's OPEN-trades fallback when no broker is connected).
    api.positions
      .list()
      .then((positions) => {
        if (Array.isArray(positions) && positions.length > 0) {
          usePositionsStore.getState().setPositions(positions)
        }
      })
      .catch(console.error)

    // Re-fetch pending alerts
    api.alerts
      .list({ status: 'PENDING', per_page: 100 })
      .then((alerts) => useAlertsStore.getState().loadPending(alerts))
      .catch(console.error)
  }
}

// ─── Register default store handlers ─────────────────────────────────────────

function registerDefaultHandlers(service: WebSocketService): void {
  // Price ticks
  service.on<import('@/types/ws').TickData>('prices', 'tick', (data) => {
    usePricesStore.getState().updateTick(data)
  })

  // Position updates (full list). Only overwrite when the broker sends a non-empty
  // list — empty lists from a freshly-reconnected broker would stomp the dashboard
  // fallback of "show open trades as positions".
  service.on<import('@/types/ws').PositionUpdateData>('positions', 'update', (data) => {
    if (Array.isArray(data?.positions) && data.positions.length > 0) {
      usePositionsStore.getState().setPositions(data.positions)
    }
  })

  // Position added
  service.on<import('@/types/ws').PositionEventData>('positions', 'added', (data) => {
    usePositionsStore.getState().updatePosition(data.position)
  })

  // Position removed
  service.on<import('@/types/ws').PositionEventData>('positions', 'removed', (data) => {
    usePositionsStore.getState().removePosition(data.position.id)
  })

  // New alert
  service.on<import('@/types/ws').AlertNewData>('alerts', 'new', (data) => {
    useAlertsStore.getState().addAlert(data.alert)
  })

  // Alert status changed
  service.on<import('@/types/ws').AlertStatusData>('alerts', 'status_changed', (data) => {
    useAlertsStore.getState().resolveAlert(data.alert_id, data.status)
  })

  // Alert expired
  service.on<import('@/types/ws').AlertStatusData>('alerts', 'expired', (data) => {
    useAlertsStore.getState().expireAlert(data.alert_id)
  })
}

// ─── Singleton ────────────────────────────────────────────────────────────────

export const wsService = new WebSocketService()
registerDefaultHandlers(wsService)
