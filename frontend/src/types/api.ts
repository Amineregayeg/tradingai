// ─── Enums / Union Types ───────────────────────────────────────────────────────

export type Direction = 'LONG' | 'SHORT'
export type Outcome = 'WIN' | 'LOSS' | 'BE' | 'OPEN'

export type AlertType = 'ENTRY_SIGNAL' | 'EXIT_MGMT' | 'RISK_WARNING' | 'PATTERN' | 'PSYCHOLOGY'
export type AlertPriority = 'INFO' | 'SUGGESTION' | 'WARNING' | 'CRITICAL'
export type AlertStatus =
  | 'PENDING'
  | 'APPROVED'
  | 'REJECTED'
  | 'EDITED'
  | 'EXECUTING'
  | 'EXECUTED'
  | 'FAILED'
  | 'EXPIRED'
  | 'SUPERSEDED'

export type ICTType = 'OB' | 'FVG' | 'BOS' | 'CHOCH' | 'LIQ' | 'SFP' | 'BREAKER' | 'SD_ZONE'
export type ICTDir = 'BULL' | 'BEAR'
export type ICTStatus = 'ACTIVE' | 'MITIGATED' | 'EXPIRED'

export type Timeframe = '1m' | '5m' | '15m' | '1H' | '4H' | 'D'

export type TradeStatus = 'OPEN' | 'CLOSED' | 'CANCELLED'

export type ComplianceState =
  | 'ACTIVE'
  | 'AT_RISK'
  | 'CRITICAL'
  | 'HALTED'
  | 'COOLDOWN'
  | 'BREACHED'

export type BrokerName = 'oanda' | 'alpaca' | 'metaapi' | 'cryptofundtrader'
export type Environment = 'practice' | 'live'
export type Theme = 'dark' | 'light'

// ─── Trade ────────────────────────────────────────────────────────────────────

export interface Trade {
  id: string
  user_id: string
  broker_id: string
  broker: string
  pair: string
  direction: Direction
  entry_price: number
  exit_price: number | null
  sl: number | null
  tp: number | null
  lot_size: number
  entry_time: string
  exit_time: string | null
  r_multiple: number | null
  outcome: Outcome
  session: string | null
  status: TradeStatus
  pnl_dollars: number | null
  pnl_pips: number | null
  notes: string | null
  setup_tag: string | null
  created_at: string
  updated_at: string
}

// ─── Position ─────────────────────────────────────────────────────────────────

export interface Position {
  id: string
  broker_id: string
  pair: string
  direction: Direction
  lot_size: number
  entry_price: number
  current_price: number | null
  sl_price: number | null
  tp_price: number | null
  unrealized_pnl: number | null
  unrealized_pips: number | null
  open_time: string
  margin_used: number | null
  broker_position_id: string | null
}

// ─── Alert ────────────────────────────────────────────────────────────────────

export interface Alert {
  id: string
  user_id: string
  type: AlertType
  priority: AlertPriority
  status: AlertStatus
  pair: string | null
  message: string
  suggested_action: Record<string, unknown> | null
  context_json: Record<string, unknown> | null
  ai_confidence: number | null
  score: number | null
  created_at: string
  expires_at: string | null
  resolved_at: string | null
  resolved_by: string | null
  // Optional/legacy convenience fields used by EditModal
  title?: string
  entry_price?: number | null
  sl_price?: number | null
  tp_price?: number | null
  r_ratio?: number | null
  lot_size?: number | null
}

export interface AlertActionRequest {
  action: 'approve' | 'reject' | 'edit'
  changes?: Record<string, unknown>
  reason?: string
}

export interface EditDiff {
  field: string
  original: unknown
  edited: unknown
}

// ─── Screenshot ───────────────────────────────────────────────────────────────

export interface Screenshot {
  id: string
  filename: string
  content_type: string
  size_bytes: number
  pair: string | null
  timeframe: Timeframe | null
  captured_at: string | null
  created_at: string
  image_url: string
}

// ─── Analysis ─────────────────────────────────────────────────────────────────

export interface KeyLevel {
  price: number
  label: string
  type: 'support' | 'resistance' | 'pivot'
}

// Structured Claude output stored verbatim in `analysis_json`.
export interface AnalysisJson {
  trend_assessment?: string
  trade_bias?: string
  key_levels?: KeyLevel[]
  ict_concepts_found?: string[]
  risk_factors?: string[]
  confidence?: number
  raw_text?: string
  [key: string]: unknown
}

export interface Analysis {
  id: string
  user_id: string
  screenshot_id: string
  model: string
  analysis_json: AnalysisJson
  trend_assessment: string | null
  trade_bias: string | null
  confidence: number | null
  raw_text: string | null
  prompt_tokens: number
  completion_tokens: number
  cost_usd: number
  downgraded: boolean
  created_at: string
}

// ─── ICT Detection ────────────────────────────────────────────────────────────

export interface ICTDetection {
  id: string
  pair: string
  timeframe: Timeframe
  type: ICTType
  direction: ICTDir
  status: ICTStatus
  high_price: number | null
  low_price: number | null
  open_price: number | null
  close_price: number | null
  detected_at: string
  mitigated_at: string | null
  expires_at: string | null
  analysis_id: string | null
  metadata: Record<string, unknown> | null
  created_at: string
}

// ─── Broker ───────────────────────────────────────────────────────────────────

export interface BrokerConnection {
  id: string
  user_id: string
  broker: BrokerName
  label: string | null
  account_id: string | null
  environment: Environment | null
  connected: boolean
  last_connected_at: string | null
  created_at: string
}

export interface BrokerConnectRequest {
  broker: BrokerName
  label?: string
  api_key?: string
  api_secret?: string
  account_id?: string
  environment: Environment
  // Match-Trader / Crypto Fund Trader credentials
  email?: string
  password?: string
  server?: string
  observe_only?: boolean
}

// ─── Settings ─────────────────────────────────────────────────────────────────

export interface Settings {
  user_id?: string
  ai_enabled: boolean
  ai_primary_model: string
  ai_screening_model: string
  ai_monthly_budget_usd: number
  ai_used_current_month_usd: number
  alert_sound: boolean
  desktop_notifications: boolean
  auto_screenshot_on_open: boolean
  auto_screenshot_interval: number
  max_risk_pct: number
  max_daily_loss_pct: number
  max_concurrent_positions: number
  require_checklist: boolean
  timezone: string
  theme: 'dark' | 'light'
  updated_at?: string
}

// ─── Audit ────────────────────────────────────────────────────────────────────

export interface AuditEvent {
  id: string
  event_type: string
  entity_type: string
  entity_id: string | null
  user_id: string | null
  before: Record<string, unknown> | null
  after: Record<string, unknown> | null
  metadata: Record<string, unknown> | null
  ip_address: string | null
  created_at: string
}

// ─── Prop Firm ────────────────────────────────────────────────────────────────

export interface PropFirmStatus {
  profile_id: string
  firm_name: string
  state: ComplianceState
  equity: number
  balance: number
  daily_loss: number
  total_loss: number
  daily_loss_limit_pct: number | null
  total_loss_limit_pct: number | null
  timestamp: string
}

export interface PropFirmProfile {
  id: string
  user_id: string
  firm_name: string
  challenge_type: string | null
  rules_json: Record<string, unknown>
  account_id: string | null
  active: boolean
  created_at: string
  updated_at: string
}

export interface PropFirmProfileCreate {
  firm_name: string
  challenge_type?: string | null
  rules_json: Record<string, unknown>
  account_id?: string | null
}

export interface KillSwitchRequest {
  profile_id: string
  reason?: string
  close_all_positions?: boolean
}

export interface KillSwitchTriggerResponse {
  profile_id: string
  armed: boolean
  positions_closed: number
  state: ComplianceState
  message: string
}

// ─── API helpers ──────────────────────────────────────────────────────────────

export interface Problem {
  type: string
  title: string
  status: number
  detail: string
}

export interface PaginatedResponse<T> {
  items: T[]
  total: number
  page: number
  per_page: number
}

// ─── Health ───────────────────────────────────────────────────────────────────

export interface HealthStatus {
  status: string
  db: string
  redis: string
  brokers: Record<string, string>
  ai: string
  version: string
}
