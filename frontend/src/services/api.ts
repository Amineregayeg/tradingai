import type {
  Alert,
  AlertActionRequest,
  AlertPriority,
  AlertStatus,
  AlertType,
  Analysis,
  AuditEvent,
  BrokerConnectRequest,
  BrokerAccount,
  DataHealth,
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

// ─── Auth token (single-user bearer) ──────────────────────────────────────────
// The API requires `Authorization: Bearer <token>` on every /api route. The
// token is entered once via the login gate and kept in localStorage. On a 401
// we clear it and reload so the gate reappears.

const TOKEN_KEY = 'tradingai_api_token'

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) || ''
  } catch {
    return ''
  }
}

export function setToken(token: string): void {
  try {
    localStorage.setItem(TOKEN_KEY, token.trim())
  } catch {
    /* ignore */
  }
}

export function clearToken(): void {
  try {
    localStorage.removeItem(TOKEN_KEY)
  } catch {
    /* ignore */
  }
}

/** Headers every request/raw-fetch should send. Exported for pages that fetch directly. */
export function authHeaders(): Record<string, string> {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

/**
 * Mint a short-lived, single-use WebSocket ticket. The /ws handshake takes this
 * ticket (NOT the master token) in its query string, so the long-lived
 * credential never lands in a URL / access log / browser history.
 */
export async function getWsTicket(): Promise<string> {
  const res = await fetch(BASE + '/auth/ws-ticket', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
  })
  if (!res.ok) {
    if (res.status === 401) onUnauthorized()
    throw new Error(`ws-ticket failed: ${res.status}`)
  }
  const d = await res.json()
  return String(d.ticket || '')
}

function onUnauthorized(): void {
  // Only act on a 401 for a request that CARRIED a token — i.e. a stale/rejected
  // token. If there is no token, we're simply not logged in yet; reloading would
  // loop forever before the login gate can be used.
  if (!getToken()) return
  clearToken()
  try {
    if (typeof window !== 'undefined') window.location.reload()
  } catch {
    /* ignore */
  }
}

// ─── Core request helper ─────────────────────────────────────────────────────

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(BASE + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    if (res.status === 401) onUnauthorized()
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
    /**
     * GET /api/brokers/accounts — live balance/equity per connected broker.
     *
     * Distinct from list(): that returns what is CONFIGURED, this returns what
     * is actually reachable right now. A broker can be configured and connected
     * in the database while its transport is down, and the two must not be
     * conflated — `reachable` is the honest signal.
     */
    accounts: () => request<BrokerAccount[]>('GET', '/brokers/accounts'),
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

  // ── Engine (live loop status, decision log, feedback loop, sim challenge) ──
  engine: {
    status: () => request<Record<string, unknown>>('GET', '/engine/status'),
    sim: () => request<Record<string, unknown>>('GET', '/engine/sim'),
    decisions: (limit = 50) =>
      request<Record<string, unknown>[]>('GET', `/engine/decisions${buildQuery({ limit })}`),
    feedback: (minEvidence = 30) =>
      request<Record<string, unknown>>('GET', `/engine/feedback${buildQuery({ min_evidence: minEvidence })}`),
    pause: () => request<Record<string, unknown>>('POST', '/engine/pause'),
    resume: () => request<Record<string, unknown>>('POST', '/engine/resume'),
    /**
     * POST /engine/reset — end the current run and start a clean one.
     *
     * Deletes NOTHING. The previous run's trades and decision records remain,
     * scoped to their run_id; the slate is clean because metrics are scoped to
     * the new run, not because history was removed.
     */
    /**
     * POST /engine/reset — apply a configuration and start a new run.
     *
     * Deletes NOTHING: the previous run keeps its trades and decisions and
     * stays viewable. An invalid setting is REFUSED with a reason rather than
     * silently defaulted, so the stored config always describes what actually
     * ran.
     */
    reset: (config?: Record<string, unknown>) =>
      request<Record<string, unknown>>('POST', '/engine/reset', config ?? {}),
    configOptions: () => request<Record<string, unknown>>('GET', '/engine/config-options'),
    runs: () => request<Record<string, unknown>[]>('GET', '/engine/runs'),
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
      /**
       * Which cohort to return. The API defaults to 'live', which excludes
       * injected backtest-replay rows — anything computing performance should
       * take that default. The trade journal passes 'all' on purpose: it is a
       * ledger, not a performance view, and it renders the setup tag so replay
       * rows are visibly labelled rather than silently counted.
       */
      cohort?: 'live' | 'replay' | 'all'
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
    /**
     * GET /api/system/data-health — the systems that fail silently.
     *
     * A component the backend cannot read reports status "unavailable", never
     * "healthy". Treat "unavailable" as a problem in the UI, not as an absence
     * of news: it means nothing is watching that component.
     */
    dataHealth: () => request<DataHealth>('GET', '/system/data-health'),
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
