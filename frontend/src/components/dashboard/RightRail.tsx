import { useEffect, useState } from 'react'
import { api } from '@/services/api'
import { wsService } from '@/services/ws'
import { InlineApprovalQueue } from '@/components/governance/InlineApprovalQueue'
import { EnginePanel } from '@/components/dashboard/EnginePanel'
import type { Analysis, AuditEvent } from '@/types/api'
import type { AlertNewData, AlertStatusData } from '@/types/ws'

// ─── Event type styling map ────────────────────────────────────────────────────

interface BadgeStyle {
  label: string
  color: string
  bg: string
}

const TYPE_STYLES: Record<string, BadgeStyle> = {
  analysis_completed: { label: 'AI', color: '#a78bfa', bg: 'rgba(167,139,250,0.12)' },
  alert_created: { label: 'ALERT', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  alert_resolved: { label: 'ALERT', color: '#00d68f', bg: 'rgba(0,214,143,0.12)' },
  position_opened: { label: 'TRADE', color: '#00d68f', bg: 'rgba(0,214,143,0.12)' },
  position_closed: { label: 'TRADE', color: '#00d68f', bg: 'rgba(0,214,143,0.12)' },
  screenshot_taken: { label: 'AI', color: '#a78bfa', bg: 'rgba(167,139,250,0.12)' },
  settings_updated: { label: 'BRIEF', color: '#4f8fff', bg: 'rgba(79,143,255,0.12)' },
  broker_connected: { label: 'BRIEF', color: '#4f8fff', bg: 'rgba(79,143,255,0.12)' },
  broker_disconnected: { label: 'ALERT', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
}

function getTypeStyle(eventType: string): BadgeStyle {
  return TYPE_STYLES[eventType] ?? { label: 'AI', color: '#a78bfa', bg: 'rgba(167,139,250,0.12)' }
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso)
    return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
  } catch {
    return '—'
  }
}

function formatEventMsg(event: AuditEvent): string {
  const a = event.after as Record<string, unknown> | null
  const b = event.before as Record<string, unknown> | null
  switch (event.event_type) {
    case 'position_opened':
      return `${a?.pair ?? ''} ${a?.direction ?? ''} opened @ ${a?.entry_price ?? ''}`
    case 'position_closed':
      return `Closed ${b?.pair ?? ''} ${b?.direction ?? ''}`
    case 'alert_created':
      return `${a?.title ?? a?.type ?? 'New alert'}`
    case 'analysis_completed':
      return `AI analysis: ${a?.bias ?? 'NEUTRAL'} bias`
    case 'screenshot_taken':
      return `Screenshot captured for ${a?.pair ?? 'chart'}`
    case 'settings_updated':
      return 'Settings updated'
    case 'broker_connected':
      return `Broker connected: ${a?.name ?? ''}`
    case 'broker_disconnected':
      return `Broker disconnected: ${b?.name ?? ''}`
    default:
      return event.event_type.replace(/_/g, ' ').toLowerCase()
  }
}

// ─── Feed item ─────────────────────────────────────────────────────────────────

function FeedItem({ time, label, color, bg, msg }: {
  time: string; label: string; color: string; bg: string; msg: string
}) {
  return (
    <div style={{ display: 'flex', gap: 10, padding: '8px 0', borderBottom: '1px solid #1a1a26' }}>
      <span style={{ fontSize: 10, color: '#55556a', fontFamily: 'var(--font-mono)', flexShrink: 0, paddingTop: 1, minWidth: 36 }}>
        {time}
      </span>
      <div style={{ minWidth: 0 }}>
        <span style={{
          display: 'inline-block', fontSize: 9, fontWeight: 700, padding: '1px 6px',
          borderRadius: 3, background: bg, color, marginBottom: 3, letterSpacing: '0.05em',
        }}>
          {label}
        </span>
        <div style={{
          fontSize: 11, color: '#8888a0', lineHeight: 1.4,
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }} title={msg}>
          {msg}
        </div>
      </div>
    </div>
  )
}

// ─── RightRail component ───────────────────────────────────────────────────────

interface LiveAct { time: string; kind: string; msg: string }

const ACT_STYLE: Record<string, BadgeStyle> = {
  engine: { label: 'ENGINE', color: '#4f8fff', bg: 'rgba(79,143,255,0.12)' },
  eval: { label: 'SCAN', color: '#55556a', bg: 'rgba(85,85,106,0.18)' },
  signal: { label: 'SIGNAL', color: '#f59e0b', bg: 'rgba(245,158,11,0.12)' },
  entry: { label: 'ENTRY', color: '#00d68f', bg: 'rgba(0,214,143,0.12)' },
  exit: { label: 'EXIT', color: '#a78bfa', bg: 'rgba(167,139,250,0.12)' },
}

export function RightRail() {
  const [events, setEvents] = useState<AuditEvent[]>([])
  const [liveActs, setLiveActs] = useState<LiveAct[]>([])
  const [lastAnalysis, setLastAnalysis] = useState<Analysis | null>(null)
  const [aiCardDismissed, setAiCardDismissed] = useState(false)

  const reloadFeed = () => {
    api.audit
      .list({ per_page: 20 })
      .then((items) => setEvents(Array.isArray(items) ? items : []))
      .catch(() => {})
  }

  const loadLastAnalysis = () => {
    api.analysis.list({ page_size: 1 })
      .then((items) => setLastAnalysis(Array.isArray(items) && items[0] ? items[0] : null))
      .catch(() => setLastAnalysis(null))
  }

  useEffect(() => {
    reloadFeed()
    loadLastAnalysis()
    // seed the live activity feed from the engine's recent history
    fetch('/api/engine/status')
      .then((r) => r.json())
      .then((d) => setLiveActs(Array.isArray(d?.activity) ? d.activity : []))
      .catch(() => {})
  }, [])

  // Subscribe to live activity
  useEffect(() => {
    const unsubAct = wsService.on<LiveAct>('system', 'activity', (a) =>
      setLiveActs((prev) => [a, ...prev].slice(0, 50)),
    )
    const unsubAlert = wsService.on<AlertNewData>('alerts', 'new', reloadFeed)
    const unsubAlertStatus = wsService.on<AlertStatusData>('alerts', 'status_changed', reloadFeed)
    return () => { unsubAct(); unsubAlert(); unsubAlertStatus() }
  }, [])

  // AI card content from real analysis
  const aiTitle = lastAnalysis?.trend_assessment ?? (lastAnalysis?.trade_bias ? `${lastAnalysis.trade_bias} bias detected` : null)
  const aiBody = lastAnalysis?.raw_text
    ? lastAnalysis.raw_text.slice(0, 160).replace(/\n/g, ' ') + (lastAnalysis.raw_text.length > 160 ? '…' : '')
    : null
  const showAiCard = !aiCardDismissed && lastAnalysis !== null && aiTitle !== null

  return (
    <aside style={{
      width: 380, flexShrink: 0, background: '#12121a',
      borderLeft: '1px solid #1e2035', display: 'flex',
      flexDirection: 'column', height: '100%', overflow: 'hidden',
    }}>
      {/* LIVE ENGINE — status, metrics, control */}
      <EnginePanel />

      {/* APPROVAL QUEUE — the product's headline differentiator */}
      <InlineApprovalQueue />

      {/* AI ASSISTANT CARD — only shown when real analysis exists */}
      {showAiCard && (
        <div style={{
          margin: 12, marginBottom: 0, borderRadius: 10, padding: '14px',
          background: '#13102a', border: '1px solid #2a1f4a', borderLeft: '3px solid #a78bfa',
          flexShrink: 0,
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
            <span style={{ color: '#a78bfa', fontSize: 12, lineHeight: 1 }}>✦</span>
            <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.12em', color: '#a78bfa', textTransform: 'uppercase' }}>
              AI Assistant
            </span>
          </div>
          <div style={{ fontSize: 14, fontWeight: 700, color: '#e8e8ef', marginBottom: 6, lineHeight: 1.3 }}>
            {aiTitle}
          </div>
          {aiBody && (
            <div style={{ fontSize: 11, color: '#8888a0', lineHeight: 1.55, marginBottom: 12 }}>
              {aiBody}
            </div>
          )}
          {lastAnalysis?.confidence != null && (
            <div style={{ fontSize: 11, color: '#55556a', marginBottom: 10 }}>
              Confidence: <span style={{ color: '#a78bfa', fontWeight: 600 }}>
                {Math.round(Number(lastAnalysis.confidence) * 100)}%
              </span>
            </div>
          )}
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => setAiCardDismissed(true)}
              style={{
                flex: 1, padding: '7px 0', borderRadius: 6,
                border: '1px solid #2a1f4a', background: 'transparent',
                color: '#8888a0', fontSize: 12, cursor: 'pointer',
              }}
            >
              Dismiss
            </button>
          </div>
        </div>
      )}
      {aiCardDismissed && lastAnalysis && (
        <div style={{
          margin: 12, padding: '10px 14px', borderRadius: 8,
          background: '#12121a', border: '1px solid #1e2035',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        }}>
          <span style={{ fontSize: 11, color: '#55556a' }}>✦ AI Assistant dismissed</span>
          <button onClick={() => setAiCardDismissed(false)} style={{ fontSize: 11, color: '#a78bfa', background: 'none', border: 'none', cursor: 'pointer' }}>Show</button>
        </div>
      )}

      {/* ACTIVITY FEED header */}
      <div style={{ padding: '12px 12px 6px', flexShrink: 0 }}>
        <span style={{ fontSize: 9, fontWeight: 700, letterSpacing: '0.1em', color: '#55556a', textTransform: 'uppercase' }}>
          Activity Feed
        </span>
      </div>

      {/* Feed list — live engine activity first, then DB audit events */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '0 12px 12px' }}>
        {liveActs.length === 0 && events.length === 0 ? (
          <div style={{ paddingTop: 24, textAlign: 'center' }}>
            <div style={{ fontSize: 13, marginBottom: 6 }}>📡</div>
            <div style={{ fontSize: 11, color: '#55556a', lineHeight: 1.5 }}>
              Waiting for the engine…
              <br />
              It evaluates each pair on every bar close.
            </div>
          </div>
        ) : (
          <>
            {liveActs.map((a, i) => {
              const style = ACT_STYLE[a.kind] ?? ACT_STYLE.engine
              return (
                <FeedItem
                  key={`act-${a.time}-${i}`}
                  time={formatTime(a.time)}
                  label={style.label}
                  color={style.color}
                  bg={style.bg}
                  msg={a.msg}
                />
              )
            })}
            {events.map((e) => {
              const style = getTypeStyle(e.event_type)
              return (
                <FeedItem
                  key={e.id}
                  time={formatTime(e.created_at)}
                  label={style.label}
                  color={style.color}
                  bg={style.bg}
                  msg={formatEventMsg(e)}
                />
              )
            })}
          </>
        )}
      </div>
    </aside>
  )
}
