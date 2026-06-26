/**
 * InlineApprovalQueue
 *
 * The right-rail Approval Queue rendered with explicit inline styles so it survives
 * the CSS scoping in RightRail. Same behaviour as ApprovalQueue (load PENDING,
 * approve/reject/edit, badge clear), with a dashboard-native look.
 */
import { useEffect, useState, useCallback } from 'react'
import { useAlertsStore } from '@/stores/alertsStore'
import { usePositionsStore } from '@/stores/positionsStore'
import { api } from '@/services/api'
import { EditModal } from './EditModal'
import type { Alert, AlertPriority, Position } from '@/types/api'

const PRIORITY_STYLE: Record<AlertPriority, { color: string; bg: string; border: string }> = {
  CRITICAL: { color: '#ff3b5c', bg: 'rgba(255,59,92,0.10)', border: '#ff3b5c' },
  WARNING:  { color: '#f59e0b', bg: 'rgba(245,158,11,0.10)', border: '#f59e0b' },
  SUGGESTION: { color: '#4f8fff', bg: 'rgba(79,143,255,0.10)', border: '#4f8fff' },
  INFO:     { color: '#8888a0', bg: 'rgba(136,136,160,0.10)', border: '#55556a' },
}

const PRIORITY_ORDER: Record<AlertPriority, number> = {
  CRITICAL: 0, WARNING: 1, SUGGESTION: 2, INFO: 3,
}

function formatHHmm(iso: string): string {
  try {
    const d = new Date(iso)
    return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  } catch { return '' }
}

/**
 * Convert an approved ENTRY_SIGNAL alert into a synthetic OPEN position so the
 * trader sees their action flow from "Approve" → live position immediately.
 */
function alertToPosition(alert: Alert): Position | null {
  const sa = (alert.suggested_action ?? {}) as Record<string, unknown>
  const pair = alert.pair ?? (sa.pair as string | undefined)
  const entry = Number(sa.suggested_entry ?? sa.entry_price ?? 0)
  const sl = Number(sa.suggested_sl ?? sa.sl ?? 0)
  const tp = Number(sa.suggested_tp ?? sa.tp ?? 0)
  const lot = Number(sa.lot_size ?? 0.1)
  if (!pair || !entry) return null
  const direction = String(sa.direction ?? 'LONG').toUpperCase() === 'SHORT' ? 'SHORT' : 'LONG'
  return {
    id: `sim-${alert.id}`,
    broker_id: 'cft-365105',
    pair,
    direction: direction as 'LONG' | 'SHORT',
    lot_size: lot,
    entry_price: entry,
    current_price: entry,
    sl_price: sl || null,
    tp_price: tp || null,
    unrealized_pnl: 0,
    unrealized_pips: 0,
    open_time: new Date().toISOString(),
    margin_used: null,
    broker_position_id: null,
  }
}

export function InlineApprovalQueue() {
  const pending = useAlertsStore((s) => s.pending)
  const badge = useAlertsStore((s) => s.badge)
  const clearBadge = useAlertsStore((s) => s.clearBadge)
  const resolveAlert = useAlertsStore((s) => s.resolveAlert)

  const [loadingId, setLoadingId] = useState<string | null>(null)
  const [editing, setEditing] = useState<Alert | null>(null)
  const [toast, setToast] = useState<string | null>(null)

  useEffect(() => {
    if (badge > 0) clearBadge()
  }, [badge, clearBadge])

  const sorted = [...pending].sort((a, b) => {
    const po = PRIORITY_ORDER[a.priority] - PRIORITY_ORDER[b.priority]
    if (po !== 0) return po
    return new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
  })

  const showToast = (msg: string) => {
    setToast(msg)
    setTimeout(() => setToast(null), 2500)
  }

  const handleApprove = useCallback(async (alert: Alert) => {
    setLoadingId(alert.id)
    try {
      await api.alerts.action(alert.id, { action: 'approve' })
      resolveAlert(alert.id, 'APPROVED')
      // Headline UX: alert → position appears
      if (alert.type === 'ENTRY_SIGNAL') {
        const pos = alertToPosition(alert)
        if (pos) {
          usePositionsStore.getState().updatePosition(pos)
          showToast(`✓ Approved — ${pos.pair} ${pos.direction} opened`)
        } else {
          showToast('✓ Approved')
        }
      } else {
        showToast('✓ Approved')
      }
    } catch {
      showToast('Approve failed')
    } finally {
      setLoadingId(null)
    }
  }, [resolveAlert])

  const handleReject = useCallback(async (alert: Alert) => {
    setLoadingId(alert.id)
    try {
      await api.alerts.action(alert.id, { action: 'reject' })
      resolveAlert(alert.id, 'REJECTED')
      showToast('Rejected')
    } catch {
      showToast('Reject failed')
    } finally {
      setLoadingId(null)
    }
  }, [resolveAlert])

  const handleEditSubmit = useCallback(async (changes: Record<string, unknown>, reason: string) => {
    if (!editing) return
    setLoadingId(editing.id)
    try {
      await api.alerts.action(editing.id, { action: 'edit', changes, reason })
      resolveAlert(editing.id, 'EDITED')
      setEditing(null)
      showToast('✎ Edited & approved')
    } finally {
      setLoadingId(null)
    }
  }, [editing, resolveAlert])

  return (
    <>
      <div style={{
        flexShrink: 0,
        borderBottom: '1px solid #1e2035',
        maxHeight: '50%',
        display: 'flex',
        flexDirection: 'column',
      }}>
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10,
          padding: '12px 14px 10px',
          background: '#0d0d14',
          borderBottom: '1px solid #1e2035',
        }}>
          <span style={{
            fontSize: 11, fontWeight: 700, letterSpacing: '0.08em',
            color: '#e8e8ef', textTransform: 'uppercase',
          }}>
            Approval Queue
          </span>
          {sorted.length > 0 && (
            <span style={{
              display: 'inline-flex', alignItems: 'center', justifyContent: 'center',
              minWidth: 18, height: 18, padding: '0 6px',
              borderRadius: 9, fontSize: 10, fontWeight: 700,
              background: '#ff3b5c', color: '#fff',
            }}>
              {sorted.length}
            </span>
          )}
          <span style={{ marginLeft: 'auto', fontSize: 9, color: '#3a3a50', fontFamily: 'var(--font-mono)' }}>
            AI proposes · you decide
          </span>
        </div>

        {/* Alert cards */}
        <div style={{ overflowY: 'auto', padding: 10, display: 'flex', flexDirection: 'column', gap: 8 }}>
          {sorted.length === 0 ? (
            <div style={{
              padding: '24px 16px', textAlign: 'center',
              fontSize: 11, color: '#55556a', lineHeight: 1.5,
            }}>
              <div style={{ fontSize: 18, marginBottom: 8 }}>✓</div>
              No pending alerts.<br />
              The AI will surface the next setup here.
            </div>
          ) : sorted.map((alert) => {
            const ps = PRIORITY_STYLE[alert.priority]
            const sa = (alert.suggested_action ?? {}) as Record<string, unknown>
            const isLoading = loadingId === alert.id

            const entry: string | undefined =
              sa.suggested_entry !== undefined ? String(sa.suggested_entry)
              : sa.entry_price !== undefined ? String(sa.entry_price) : undefined
            const sl: string | undefined =
              sa.suggested_sl !== undefined ? String(sa.suggested_sl)
              : sa.sl !== undefined ? String(sa.sl) : undefined
            const tp: string | undefined =
              sa.suggested_tp !== undefined ? String(sa.suggested_tp)
              : sa.tp !== undefined ? String(sa.tp) : undefined
            const rr: number | undefined =
              sa.r_ratio !== undefined ? Number(sa.r_ratio)
              : sa.r_multiple !== undefined ? Number(sa.r_multiple) : undefined
            const score: number | null = alert.score

            return (
              <div key={alert.id} style={{
                background: '#12121a',
                border: '1px solid #1e2035',
                borderLeft: `3px solid ${ps.border}`,
                borderRadius: 7,
                padding: '10px 12px',
                opacity: isLoading ? 0.6 : 1,
                transition: 'opacity 200ms ease',
              }}>
                {/* Row 1: priority + type + time */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
                  <span style={{
                    fontSize: 9, fontWeight: 700, padding: '2px 6px',
                    borderRadius: 3, background: ps.bg, color: ps.color,
                    letterSpacing: '0.05em',
                  }}>
                    {alert.priority}
                  </span>
                  <span style={{
                    fontSize: 9, fontWeight: 600, padding: '2px 6px',
                    borderRadius: 3, background: '#1a1a26', color: '#8888a0',
                    letterSpacing: '0.05em',
                  }}>
                    {alert.type.replace(/_/g, ' ')}
                  </span>
                  {alert.pair && (
                    <span style={{
                      fontSize: 11, fontWeight: 700, color: '#e8e8ef',
                      fontFamily: 'var(--font-mono)', marginLeft: 4,
                    }}>
                      {alert.pair}
                    </span>
                  )}
                  <span style={{ marginLeft: 'auto', fontSize: 10, color: '#55556a', fontFamily: 'var(--font-mono)' }}>
                    {formatHHmm(alert.created_at)}
                  </span>
                </div>

                {/* Message */}
                <p style={{
                  fontSize: 12, color: '#e8e8ef', lineHeight: 1.4, marginBottom: 8,
                  display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden',
                }}>
                  {alert.message}
                </p>

                {/* Suggested action chip strip */}
                {(entry || sl || tp || rr) && (
                  <div style={{
                    display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 8,
                    padding: '6px 8px', background: '#0d0d14', borderRadius: 5,
                    fontSize: 10, fontFamily: 'var(--font-mono)',
                  }}>
                    {entry !== undefined && (
                      <span style={{ color: '#8888a0' }}>
                        Entry <b style={{ color: '#e8e8ef' }}>{entry}</b>
                      </span>
                    )}
                    {sl !== undefined && (
                      <span style={{ color: '#8888a0' }}>
                        SL <b style={{ color: '#ff3b5c' }}>{sl}</b>
                      </span>
                    )}
                    {tp !== undefined && (
                      <span style={{ color: '#8888a0' }}>
                        TP <b style={{ color: '#00d68f' }}>{tp}</b>
                      </span>
                    )}
                    {rr !== undefined && (
                      <span style={{ color: '#8888a0' }}>
                        RR <b style={{ color: '#a78bfa' }}>{rr.toFixed(1)}R</b>
                      </span>
                    )}
                    {score !== null && (
                      <span style={{ color: '#8888a0', marginLeft: 'auto' }}>
                        Score <b style={{ color: '#e8e8ef' }}>{Math.round(score)}</b>
                      </span>
                    )}
                  </div>
                )}

                {/* Action buttons */}
                <div style={{ display: 'flex', gap: 6 }}>
                  <button
                    disabled={isLoading}
                    onClick={() => handleApprove(alert)}
                    style={{
                      flex: 1, padding: '6px 0', borderRadius: 5, border: 'none',
                      background: '#00d68f', color: '#0a0a0f',
                      fontSize: 11, fontWeight: 700, cursor: isLoading ? 'not-allowed' : 'pointer',
                    }}>
                    Approve
                  </button>
                  <button
                    disabled={isLoading}
                    onClick={() => setEditing(alert)}
                    style={{
                      flex: 1, padding: '6px 0', borderRadius: 5,
                      border: '1px solid #252540', background: 'transparent',
                      color: '#a78bfa', fontSize: 11, fontWeight: 600,
                      cursor: isLoading ? 'not-allowed' : 'pointer',
                    }}>
                    Edit
                  </button>
                  <button
                    disabled={isLoading}
                    onClick={() => handleReject(alert)}
                    style={{
                      flex: 1, padding: '6px 0', borderRadius: 5,
                      border: '1px solid #252540', background: 'transparent',
                      color: '#8888a0', fontSize: 11, fontWeight: 600,
                      cursor: isLoading ? 'not-allowed' : 'pointer',
                    }}>
                    Reject
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Toast */}
      {toast && (
        <div style={{
          position: 'fixed', bottom: 24, right: 24, zIndex: 1000,
          padding: '10px 16px', borderRadius: 8,
          background: '#0d0d14', border: '1px solid #00d68f55',
          color: '#e8e8ef', fontSize: 13, fontWeight: 600,
          boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
        }}>
          {toast}
        </div>
      )}

      {editing && (
        <EditModal
          alert={editing}
          onClose={() => setEditing(null)}
          onSubmit={handleEditSubmit}
        />
      )}
    </>
  )
}
