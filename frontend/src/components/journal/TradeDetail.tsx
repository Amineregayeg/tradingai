import { useState, useRef } from 'react'
import { Badge, Modal, Button, Banner } from '@/components/ui'
import { AlertItem } from '@/components/shared/AlertItem'
import { PnLCell } from '@/components/shared/PnLCell'
import type { Trade, Screenshot, Analysis, Alert, EditDiff } from '@/types/api'
import {
  formatPrice,
  formatRMultiple,
  formatDuration,
  formatDateTime,
} from '@/utils/format'
import { api } from '@/services/api'

export interface TradeDetailProps {
  trade: Trade & {
    screenshots?: Screenshot[]
    analyses?: Analysis[]
    alerts?: Alert[]
    edit_diffs?: EditDiff[]
  }
  onClose: () => void
}

const outcomeVariant: Record<string, 'success' | 'danger' | 'neutral' | 'warning'> = {
  WIN: 'success',
  LOSS: 'danger',
  BE: 'neutral',
  OPEN: 'warning',
}

function biasColorOf(bias: string | null): string {
  if (!bias) return 'var(--text-muted)'
  const b = bias.toUpperCase()
  if (b.includes('LONG') || b.includes('BULL')) return 'var(--accent-green)'
  if (b.includes('SHORT') || b.includes('BEAR')) return 'var(--accent-red)'
  return 'var(--text-muted)'
}

function InfoRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-1)' }}>
      <span
        style={{
          fontSize: 'var(--text-xs)',
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          fontWeight: 'var(--weight-medium)',
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontSize: 'var(--text-sm)',
          color: 'var(--text-primary)',
          fontWeight: 'var(--weight-medium)',
        }}
      >
        {children}
      </span>
    </div>
  )
}

export function TradeDetail({ trade, onClose }: TradeDetailProps) {
  const [notes, setNotes] = useState(trade.notes ?? '')
  const [setupTag, setSetupTag] = useState(trade.setup_tag ?? '')
  const [savingNotes, setSavingNotes] = useState(false)
  const [savingTag, setSavingTag] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [selectedImage, setSelectedImage] = useState<Screenshot | null>(null)
  const [editingTag, setEditingTag] = useState(false)
  const tagInputRef = useRef<HTMLInputElement>(null)

  const latestAnalysis = trade.analyses?.length
    ? trade.analyses.sort(
        (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
      )[0]
    : null

  const handleNotesSave = async () => {
    if (notes === (trade.notes ?? '')) return
    setSavingNotes(true)
    setSaveError(null)
    try {
      await api.trades.update(trade.id, { notes })
    } catch {
      setSaveError('Failed to save notes.')
    } finally {
      setSavingNotes(false)
    }
  }

  const handleTagSave = async () => {
    setEditingTag(false)
    if (setupTag === (trade.setup_tag ?? '')) return
    setSavingTag(true)
    setSaveError(null)
    try {
      await api.trades.update(trade.id, { setup_tag: setupTag })
    } catch {
      setSaveError('Failed to save setup tag.')
    } finally {
      setSavingTag(false)
    }
  }

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        background: 'var(--bg-card)',
        borderLeft: '1px solid var(--border)',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
          padding: 'var(--space-4)',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontSize: 'var(--text-lg)',
            fontWeight: 'var(--weight-bold)',
            color: 'var(--text-primary)',
          }}
        >
          {trade.pair}
        </span>
        <Badge
          variant={trade.direction === 'LONG' ? 'success' : 'danger'}
          size="sm"
        >
          {trade.direction}
        </Badge>
        <Badge variant={outcomeVariant[trade.outcome] ?? 'neutral'} size="sm">
          {trade.outcome}
        </Badge>
        <div style={{ marginLeft: 'auto' }}>
          <Button variant="ghost" size="sm" onClick={onClose}>
            <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
              <path
                d="M11 3L3 11M3 3l8 8"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
              />
            </svg>
          </Button>
        </div>
      </div>

      {/* Scrollable content */}
      <div style={{ flex: 1, overflowY: 'auto', padding: 'var(--space-4)', display: 'flex', flexDirection: 'column', gap: 'var(--space-5)' }}>

        {saveError && (
          <Banner variant="error" dismissible>
            {saveError}
          </Banner>
        )}

        {/* Top metrics row */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: 'var(--space-3)',
          }}
        >
          <InfoRow label="Entry">
            {formatPrice(trade.entry_price)}
          </InfoRow>
          <InfoRow label="Exit">
            {trade.exit_price !== null ? formatPrice(trade.exit_price) : '—'}
          </InfoRow>
          <InfoRow label="PnL">
            <PnLCell value={trade.pnl_dollars} suffix="$" />
          </InfoRow>
          <InfoRow label="R-Multiple">
            {trade.r_multiple !== null ? (
              <span
                style={{
                  color:
                    trade.r_multiple >= 0
                      ? 'var(--accent-green)'
                      : 'var(--accent-red)',
                }}
              >
                {formatRMultiple(trade.r_multiple)}
              </span>
            ) : (
              '—'
            )}
          </InfoRow>
          <InfoRow label="Duration">
            {trade.exit_time
              ? formatDuration(
                  (new Date(trade.exit_time).getTime() -
                    new Date(trade.entry_time).getTime()) /
                    1000
                )
              : '—'}
          </InfoRow>
          <InfoRow label="Session">
            {trade.session ?? '—'}
          </InfoRow>
        </div>

        {/* Setup Tag */}
        <div>
          <p
            style={{
              fontSize: 'var(--text-xs)',
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              fontWeight: 'var(--weight-medium)',
              marginBottom: 'var(--space-2)',
            }}
          >
            Setup Tag
          </p>
          {editingTag ? (
            <input
              ref={tagInputRef}
              value={setupTag}
              onChange={(e) => setSetupTag(e.target.value)}
              onBlur={handleTagSave}
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleTagSave()
                if (e.key === 'Escape') {
                  setSetupTag(trade.setup_tag ?? '')
                  setEditingTag(false)
                }
              }}
              autoFocus
              style={{
                background: 'var(--bg-accent)',
                border: '1px solid var(--accent-blue)',
                borderRadius: 'var(--radius-sm)',
                padding: '2px 8px',
                color: 'var(--text-primary)',
                fontSize: 'var(--text-sm)',
                outline: 'none',
              }}
            />
          ) : (
            <span
              onClick={() => setEditingTag(true)}
              title="Click to edit"
              style={{
                display: 'inline-block',
                padding: '2px 8px',
                borderRadius: 'var(--radius-sm)',
                background: setupTag ? 'var(--bg-accent)' : 'transparent',
                border: setupTag ? '1px solid var(--border)' : '1px dashed var(--border)',
                fontSize: 'var(--text-sm)',
                color: setupTag ? 'var(--text-secondary)' : 'var(--text-muted)',
                cursor: 'pointer',
              }}
            >
              {savingTag ? 'Saving...' : setupTag || 'Add tag...'}
            </span>
          )}
        </div>

        {/* Screenshots */}
        {trade.screenshots && trade.screenshots.length > 0 && (
          <div>
            <p
              style={{
                fontSize: 'var(--text-sm)',
                fontWeight: 'var(--weight-semibold)',
                color: 'var(--text-primary)',
                marginBottom: 'var(--space-2)',
              }}
            >
              Screenshots
            </p>
            <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
              {trade.screenshots.map((ss) => (
                <div
                  key={ss.id}
                  onClick={() => setSelectedImage(ss)}
                  style={{
                    width: 80,
                    height: 56,
                    borderRadius: 'var(--radius-md)',
                    overflow: 'hidden',
                    border: '1px solid var(--border)',
                    cursor: 'pointer',
                    flexShrink: 0,
                  }}
                >
                  <img
                    src={api.screenshots.image(ss.id)}
                    alt={ss.filename}
                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  />
                </div>
              ))}
            </div>
          </div>
        )}

        {/* AI Analysis */}
        {latestAnalysis && (
          <div>
            <p
              style={{
                fontSize: 'var(--text-sm)',
                fontWeight: 'var(--weight-semibold)',
                color: 'var(--text-primary)',
                marginBottom: 'var(--space-2)',
              }}
            >
              AI Analysis
            </p>
            <div
              style={{
                background: 'var(--bg-accent)',
                border: '1px solid var(--border)',
                borderRadius: 'var(--radius-lg)',
                padding: 'var(--space-3)',
                display: 'flex',
                flexDirection: 'column',
                gap: 'var(--space-2)',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-3)' }}>
                <span
                  style={{
                    fontSize: 'var(--text-sm)',
                    fontWeight: 'var(--weight-semibold)',
                    color: biasColorOf(latestAnalysis.trade_bias),
                  }}
                >
                  {latestAnalysis.trade_bias ?? '—'}
                </span>
                {latestAnalysis.confidence != null && (
                  <span style={{ fontSize: 'var(--text-xs)', color: 'var(--text-muted)' }}>
                    Confidence: {(Number(latestAnalysis.confidence) * 100).toFixed(0)}%
                  </span>
                )}
                <Badge variant="ai" size="sm">
                  {latestAnalysis.model}
                </Badge>
              </div>
              {(latestAnalysis.trend_assessment || latestAnalysis.raw_text) && (
                <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
                  {latestAnalysis.trend_assessment ?? latestAnalysis.raw_text}
                </p>
              )}
              {(latestAnalysis.analysis_json?.key_levels?.length ?? 0) > 0 && (
                <div>
                  <p
                    style={{
                      fontSize: 'var(--text-xs)',
                      color: 'var(--text-muted)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                      marginBottom: 'var(--space-1)',
                    }}
                  >
                    Key Levels
                  </p>
                  <div style={{ display: 'flex', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
                    {latestAnalysis.analysis_json!.key_levels!.map((kl, i) => (
                      <span
                        key={i}
                        style={{
                          fontSize: 'var(--text-xs)',
                          padding: '2px 6px',
                          borderRadius: 'var(--radius-sm)',
                          background: 'var(--bg-card)',
                          border: '1px solid var(--border)',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        {kl.label}: {formatPrice(kl.price)}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Related Alerts */}
        {trade.alerts && trade.alerts.length > 0 && (
          <div>
            <p
              style={{
                fontSize: 'var(--text-sm)',
                fontWeight: 'var(--weight-semibold)',
                color: 'var(--text-primary)',
                marginBottom: 'var(--space-2)',
              }}
            >
              Related Alerts
            </p>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 'var(--space-2)' }}>
              {trade.alerts.map((alert) => (
                <AlertItem key={alert.id} alert={alert} compact />
              ))}
            </div>
          </div>
        )}

        {/* Edit History */}
        {trade.edit_diffs && trade.edit_diffs.length > 0 && (
          <div>
            <p
              style={{
                fontSize: 'var(--text-sm)',
                fontWeight: 'var(--weight-semibold)',
                color: 'var(--text-primary)',
                marginBottom: 'var(--space-2)',
              }}
            >
              Edit History
            </p>
            <table
              style={{
                width: '100%',
                borderCollapse: 'collapse',
                fontSize: 'var(--text-xs)',
              }}
            >
              <thead>
                <tr>
                  {['Field', 'Before', 'After'].map((h) => (
                    <th
                      key={h}
                      style={{
                        textAlign: 'left',
                        padding: 'var(--space-1) var(--space-2)',
                        color: 'var(--text-muted)',
                        fontWeight: 'var(--weight-medium)',
                        borderBottom: '1px solid var(--border)',
                      }}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {trade.edit_diffs.map((diff, i) => (
                  <tr key={i}>
                    <td
                      style={{
                        padding: 'var(--space-1) var(--space-2)',
                        color: 'var(--text-secondary)',
                        fontWeight: 'var(--weight-medium)',
                      }}
                    >
                      {diff.field}
                    </td>
                    <td
                      style={{
                        padding: 'var(--space-1) var(--space-2)',
                        color: 'var(--accent-red)',
                      }}
                    >
                      {String(diff.original)}
                    </td>
                    <td
                      style={{
                        padding: 'var(--space-1) var(--space-2)',
                        color: 'var(--accent-green)',
                      }}
                    >
                      {String(diff.edited)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Notes */}
        <div>
          <p
            style={{
              fontSize: 'var(--text-sm)',
              fontWeight: 'var(--weight-semibold)',
              color: 'var(--text-primary)',
              marginBottom: 'var(--space-2)',
            }}
          >
            Notes
            {savingNotes && (
              <span
                style={{
                  marginLeft: 'var(--space-2)',
                  fontSize: 'var(--text-xs)',
                  color: 'var(--text-muted)',
                }}
              >
                Saving...
              </span>
            )}
          </p>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            onBlur={handleNotesSave}
            rows={4}
            placeholder="Add trade notes..."
            style={{
              width: '100%',
              background: 'var(--bg-accent)',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-md)',
              padding: 'var(--space-3)',
              color: 'var(--text-primary)',
              fontSize: 'var(--text-sm)',
              resize: 'vertical',
              outline: 'none',
              fontFamily: 'inherit',
              lineHeight: 1.6,
              boxSizing: 'border-box',
            }}
            onFocus={(e) => {
              e.currentTarget.style.borderColor = 'var(--accent-blue)'
            }}
            onBlurCapture={(e) => {
              e.currentTarget.style.borderColor = 'var(--border)'
            }}
          />
        </div>

        {/* Opened / Closed info */}
        <div
          style={{
            fontSize: 'var(--text-xs)',
            color: 'var(--text-muted)',
            display: 'flex',
            gap: 'var(--space-4)',
            paddingTop: 'var(--space-2)',
            borderTop: '1px solid var(--border)',
          }}
        >
          <span>Opened: {formatDateTime(trade.entry_time)}</span>
          {trade.exit_time && <span>Closed: {formatDateTime(trade.exit_time)}</span>}
          <span>Broker: {trade.broker ?? '—'}</span>
        </div>
      </div>

      {/* Screenshot lightbox modal */}
      <Modal
        open={selectedImage !== null}
        onClose={() => setSelectedImage(null)}
        title={selectedImage?.filename}
        size="full"
      >
        {selectedImage && (
          <div style={{ textAlign: 'center' }}>
            <img
              src={api.screenshots.image(selectedImage.id)}
              alt={selectedImage.filename}
              style={{
                maxWidth: '100%',
                maxHeight: '70vh',
                objectFit: 'contain',
                borderRadius: 'var(--radius-md)',
              }}
            />
            <p
              style={{
                marginTop: 'var(--space-2)',
                fontSize: 'var(--text-xs)',
                color: 'var(--text-muted)',
              }}
            >
              {selectedImage.pair} • {selectedImage.timeframe} •{' '}
              {selectedImage.captured_at
                ? formatDateTime(selectedImage.captured_at)
                : formatDateTime(selectedImage.created_at)}
            </p>
          </div>
        )}
      </Modal>
    </div>
  )
}
