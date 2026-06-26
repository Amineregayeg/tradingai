// ─── WebSocket channel/event types ────────────────────────────────────────────

export type WSChannel = 'prices' | 'positions' | 'alerts' | 'ict' | 'propfirm' | 'system'

export interface WSMessage<T = unknown> {
  channel: WSChannel
  event: string
  data: T
  timestamp: string
  user_id?: string
}

// ─── Channel-specific data types ─────────────────────────────────────────────

/** prices / tick */
export interface TickData {
  pair: string
  bid: number
  ask: number
  spread: number
  timestamp: string
}

/** positions / update — full position snapshot */
export interface PositionUpdateData {
  positions: import('./api').Position[]
}

/** positions / added or removed — single position */
export interface PositionEventData {
  position: import('./api').Position
}

/** alerts / new — a new alert arrived */
export interface AlertNewData {
  alert: import('./api').Alert
}

/** alerts / status_changed — alert status update */
export interface AlertStatusData {
  alert_id: string
  status: import('./api').AlertStatus
  updated_at: string
}

/** ict / detection — new ICT detection */
export interface ICTNewData {
  detection: import('./api').ICTDetection
}

/** ict / mitigated — ICT detection was mitigated */
export interface ICTMitigatedData {
  detection_id: string
  mitigated_at: string
}

/** propfirm / status — compliance state update */
export interface PropFirmStatusData {
  status: import('./api').PropFirmStatus
}

/** system / ping — heartbeat from server */
export interface SystemPingData {
  ts: number
}

/** system / pong — client reply */
export interface SystemPongData {
  ts: number
}

/** system / broadcast — general system message */
export interface SystemBroadcastData {
  level: 'info' | 'warning' | 'error'
  message: string
}

/** Typed union for WSMessage to narrow by channel */
export type PricesMessage = WSMessage<TickData>
export type PositionUpdateMessage = WSMessage<PositionUpdateData>
export type PositionEventMessage = WSMessage<PositionEventData>
export type AlertNewMessage = WSMessage<AlertNewData>
export type AlertStatusMessage = WSMessage<AlertStatusData>
export type ICTNewMessage = WSMessage<ICTNewData>
export type ICTMitigatedMessage = WSMessage<ICTMitigatedData>
export type PropFirmStatusMessage = WSMessage<PropFirmStatusData>
export type SystemPingMessage = WSMessage<SystemPingData>
export type SystemBroadcastMessage = WSMessage<SystemBroadcastData>
