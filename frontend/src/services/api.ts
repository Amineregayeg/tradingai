import type {
  Alert,
  AlertActionRequest,
  AlertPriority,
  AlertStatus,
  AlertType,
  Analysis,
  AuditEvent,
  BrokerConnectRequest,
  BrokerConnection,
  HealthStatus,
  ICTDetection,
  ICTStatus,
  KillSwitchRequest,
  KillSwitchTriggerResponse,
  Outcome,
  Position,
  PropFirmProfile,
  PropFirmProfileCreate,
  PropFirmStatus,
  Screenshot,
  Settings,
  Timeframe,
  Trade,
} from '@/types/api'

const BASE = '/api'

// ─── Core request helper ─────────────────────────────────────────────────────

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({
      type: 'about:blank',
      title: 'Request Failed',
      status: res.status,
      detail: res.statusText,
    }))
    throw err
  }
  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

function buildQuery(params?: Record<string, string | number | boolean | undefined>): string {
  if (!params) return ''
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') {
      q.set(k, String(v))
    }
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}

// ─── Candle type (not in OpenAPI but used by ChartArea) ───────────────────────

export interface Candle {
  time: string
  open: number
  high: number
  low: number
  close: number
  volume: number
}

// ─── API namespace ────────────────────────────────────────────────────────────

export const api = {
  // ── Brokers ──────────────────────────────────────────────────────────────
  brokers: {
    // GET /api/brokers — list all connections
    list: () => request<BrokerConnection[]>('GET', '/brokers'),
    // alias kept for backward compat in components
    status: () => request<BrokerConnection[]>('GET', '/brokers'),
    // POST /api/brokers — create/connect
    connect: (req: BrokerConnectRequest) =>
      request<BrokerConnection>('POST', '/brokers', req),
    // DELETE /api/brokers/{id}
    disconnect: (id: string) => request<void>('DELETE', `/brokers/${id}`),
    // POST /api/brokers/{id}/reconnect
    reconnect: (id: string) => request<BrokerConnection>('POST', `/brokers/${id}/reconnect`),
  },

  // ── Positions ─────────────────────────────────────────────────────────────
  positions: {
    list: () => request<Position[]>('GET', '/positions'),
  },

  // ── Candles (internal, not in OpenAPI — backed by TimescaleDB) ────────────
  candles: {
    list: (params: { pair: string; timeframe: string; limit?: number }) =>
      request<Candle[]>('GET', `/candles${buildQuery(params as Record<string, string | number>)}`),
  },

  // ── Trades ────────────────────────────────────────────────────────────────
  trades: {
    list: (params?: {
      pair?: string
      from_dt?: string
      to_dt?: string
      outcome?: Outcome
      page?: number
      page_size?: number
    }) =>
      request<Trade[]>(
        'GET',
        `/trades${buildQuery(params as Record<string, string | number | boolean | undefined>)}`
      ),

    get: (id: string) => request<Trade>('GET', `/trades/${id}`),

    update: (id: string, changes: { notes?: string; setup_tag?: string }) =>
      request<Trade>('PATCH', `/trades/${id}`, changes),

    exportCsv: (params?: { from?: string; to?: string }) =>
      fetch(`/api/journal/export${buildQuery(params as Record<string, string | undefined>)}`),
  },

  // ── Alerts ────────────────────────────────────────────────────────────────
  alerts: {
    // GET /api/alerts — returns plain list
    list: (params?: {
      status?: AlertStatus
      from?: string
      to?: string
      type?: AlertType
      priority?: AlertPriority
      page?: number
      per_page?: number
    }) =>
      request<Alert[]>(
        'GET',
        `/alerts${buildQuery(params as Record<string, string | number | undefined>)}`
      ),

    get: (id: string) => request<Alert>('GET', `/alerts/${id}`),

    // PATCH /api/alerts/{id} — approve / reject / edit
    action: (id: string, req: AlertActionRequest) =>
      request<Alert>('PATCH', `/alerts/${id}`, req),
  },

  // ── Screenshots ───────────────────────────────────────────────────────────
  screenshots: {
    upload: (formData: FormData) =>
      fetch('/api/screenshots', { method: 'POST', body: formData }).then((r) => {
        if (!r.ok) throw r
        return r.json() as Promise<Screenshot>
      }),

    get: (id: string) => request<Screenshot>('GET', `/screenshots/${id}`),

    image: (id: string) => `/api/screenshots/${id}/image`,

    list: (params?: { pair?: string; page?: number; per_page?: number }) =>
      request<Screenshot[]>(
        'GET',
        `/screenshots${buildQuery(params as Record<string, string | number | undefined>)}`
      ),
  },

  // ── Analysis ─────────────────────────────────────────────────────────────
  analysis: {
    // POST /api/analysis/run
    run: (req: { screenshot_id: string; trade_context?: Record<string, unknown> }) =>
      request<{ analysis_id: string }>('POST', '/analysis/run', req),

    get: (id: string) => request<Analysis>('GET', `/analysis/${id}`),

    list: (params?: { screenshot_id?: string; page?: number; page_size?: number }) =>
      request<Analysis[]>('GET', `/analysis${buildQuery(params as Record<string, string | number | undefined>)}`),
  },

  // ── ICT Detections ────────────────────────────────────────────────────────
  ict: {
    detections: (params?: {
      pair?: string
      timeframe?: Timeframe
      status?: ICTStatus
    }) =>
      request<ICTDetection[]>(
        'GET',
        `/ict/detections${buildQuery(params as Record<string, string | undefined>)}`
      ),

    get: (id: string) => request<ICTDetection>('GET', `/ict/detections/${id}`),
  },

  // ── Settings ──────────────────────────────────────────────────────────────
  settings: {
    get: () => request<Settings>('GET', '/settings'),
    update: (changes: Partial<Settings>) => request<Settings>('PATCH', '/settings', changes),
  },

  // ── Audit Log ─────────────────────────────────────────────────────────────
  audit: {
    // GET /api/audit-log — returns plain list
    list: (params?: {
      event_type?: string
      entity_type?: string
      from?: string
      to?: string
      page?: number
      per_page?: number
    }) =>
      request<AuditEvent[]>(
        'GET',
        `/audit-log${buildQuery(params as Record<string, string | number | undefined>)}`
      ),
  },

  // ── System ────────────────────────────────────────────────────────────────
  system: {
    health: () => request<HealthStatus>('GET', '/system/health'),
  },

  // ── Prop Firm ─────────────────────────────────────────────────────────────
  propFirm: {
    // GET /api/prop-firm/status — returns list of PropFirmStatus
    status: () => request<PropFirmStatus[]>('GET', '/prop-firm/status'),

    profiles: () => request<PropFirmProfile[]>('GET', '/prop-firm/profiles'),

    createProfile: (req: PropFirmProfileCreate) =>
      request<PropFirmProfile>('POST', '/prop-firm/profiles', req),

    deleteProfile: (id: string) => request<void>('DELETE', `/prop-firm/profiles/${id}`),

    // POST /api/prop-firm/kill-switch — trigger (panic stop): closes all positions
    triggerKillSwitch: (req: KillSwitchRequest) =>
      request<KillSwitchTriggerResponse>('POST', '/prop-firm/kill-switch', req),
  },
}
