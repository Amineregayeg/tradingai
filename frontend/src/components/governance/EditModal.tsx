import { useState, useCallback } from 'react'
import { Modal } from '@/components/ui/Modal'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { Badge } from '@/components/ui/Badge'
import { formatPrice, formatDateTime } from '@/utils/format'
import type { Alert } from '@/types/api'

export interface EditModalProps {
  alert: Alert
  onClose: () => void
  onSubmit: (changes: Record<string, unknown>, reason: string) => Promise<void>
}

interface EditFields {
  sl: string
  tp: string
  lot_size: string
}

function DiffRow({
  label,
  original,
  edited,
}: {
  label: string
  original: number | null
  edited: number | null
}) {
  const hasChange = edited !== null && edited !== original
  return (
    <div className="flex items-center gap-2">
      <span className="text-[var(--text-xs)] text-[var(--text-muted)] w-16 flex-shrink-0">
        {label}
      </span>
      <span className="font-mono text-[var(--text-xs)] text-[var(--text-secondary)]">
        {original !== null ? formatPrice(original, 5) : '—'}
      </span>
      {hasChange && (
        <>
          <span className="text-[var(--text-muted)]">→</span>
          <span className="font-mono text-[var(--text-xs)] text-[var(--accent-amber)] font-medium">
            {edited !== null ? formatPrice(edited, 5) : '—'}
          </span>
        </>
      )}
    </div>
  )
}

export function EditModal({ alert, onClose, onSubmit }: EditModalProps) {
  const [fields, setFields] = useState<EditFields>({
    sl: alert.sl_price !== null ? String(alert.sl_price) : '',
    tp: alert.tp_price !== null ? String(alert.tp_price) : '',
    lot_size: alert.lot_size !== null ? String(alert.lot_size) : '',
  })
  const [reason, setReason] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const parsed = {
    sl: fields.sl !== '' ? parseFloat(fields.sl) : null,
    tp: fields.tp !== '' ? parseFloat(fields.tp) : null,
    lot_size: fields.lot_size !== '' ? parseFloat(fields.lot_size) : null,
  }

  const hasChanges =
    parsed.sl !== alert.sl_price ||
    parsed.tp !== alert.tp_price ||
    parsed.lot_size !== alert.lot_size

  const handleSubmit = useCallback(async () => {
    if (!hasChanges) {
      setError('No changes made.')
      return
    }
    setError(null)
    setIsSubmitting(true)
    const changes: Record<string, unknown> = {}
    if (parsed.sl !== alert.sl_price) changes.sl_price = parsed.sl
    if (parsed.tp !== alert.tp_price) changes.tp_price = parsed.tp
    if (parsed.lot_size !== alert.lot_size) changes.lot_size = parsed.lot_size
    try {
      await onSubmit(changes, reason)
    } catch {
      setError('Failed to submit changes. Please try again.')
      setIsSubmitting(false)
    }
  }, [hasChanges, parsed, alert, reason, onSubmit])

  return (
    <Modal open onClose={onClose} title="Edit Alert" description={alert.title} size="md">
      <div className="flex flex-col gap-4">
        {/* Alert summary */}
        <div
          className="rounded-[var(--radius-md)] p-3 flex items-start gap-3"
          style={{ background: 'var(--bg-accent)', border: '1px solid var(--border)' }}
        >
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <Badge
                variant={
                  alert.priority === 'CRITICAL'
                    ? 'danger'
                    : alert.priority === 'WARNING'
                      ? 'warning'
                      : 'info'
                }
                size="sm"
              >
                {alert.priority}
              </Badge>
              {alert.pair && (
                <span className="text-[var(--text-xs)] text-[var(--text-muted)]">{alert.pair}</span>
              )}
              <span className="text-[var(--text-xs)] text-[var(--text-muted)]">
                {formatDateTime(alert.created_at)}
              </span>
            </div>
            <p className="text-[var(--text-sm)] text-[var(--text-secondary)] leading-snug">
              {alert.message}
            </p>
          </div>
        </div>

        {/* Edit fields */}
        <div className="grid grid-cols-3 gap-3">
          <Input
            label="Stop Loss"
            type="number"
            step="0.00001"
            value={fields.sl}
            onChange={(e) => setFields((f) => ({ ...f, sl: e.target.value }))}
            placeholder={alert.sl_price !== null ? String(alert.sl_price) : 'e.g. 1.08000'}
            fullWidth
          />
          <Input
            label="Take Profit"
            type="number"
            step="0.00001"
            value={fields.tp}
            onChange={(e) => setFields((f) => ({ ...f, tp: e.target.value }))}
            placeholder={alert.tp_price !== null ? String(alert.tp_price) : 'e.g. 1.09000'}
            fullWidth
          />
          <Input
            label="Lot Size"
            type="number"
            step="0.01"
            min="0.01"
            value={fields.lot_size}
            onChange={(e) => setFields((f) => ({ ...f, lot_size: e.target.value }))}
            placeholder={alert.lot_size !== null ? String(alert.lot_size) : 'e.g. 0.10'}
            fullWidth
          />
        </div>

        {/* Diff preview */}
        {hasChanges && (
          <div
            className="rounded-[var(--radius-md)] p-3 flex flex-col gap-1"
            style={{ background: 'var(--bg-accent-2)', border: '1px solid var(--border)' }}
          >
            <span className="text-[var(--text-xs)] font-medium text-[var(--text-muted)] mb-1 uppercase tracking-wider">
              Changes
            </span>
            <DiffRow label="SL" original={alert.sl_price ?? null} edited={parsed.sl} />
            <DiffRow label="TP" original={alert.tp_price ?? null} edited={parsed.tp} />
            <DiffRow label="Lots" original={alert.lot_size ?? null} edited={parsed.lot_size} />
          </div>
        )}

        {/* Reason textarea */}
        <div className="flex flex-col gap-1.5">
          <label className="text-[var(--text-sm)] font-medium text-[var(--text-secondary)]">
            Reason (optional)
          </label>
          <textarea
            className="w-full rounded-[var(--radius-md)] px-3 py-2 text-[var(--text-sm)] resize-none"
            rows={2}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Why are you changing this?"
            style={{
              background: 'var(--bg-accent)',
              border: '1px solid var(--border)',
              color: 'var(--text-primary)',
              outline: 'none',
            }}
          />
        </div>

        {/* Error */}
        {error && (
          <p className="text-[var(--text-sm)] text-[var(--accent-red)]">{error}</p>
        )}

        {/* Actions */}
        <div className="flex gap-2 justify-end">
          <Button variant="secondary" size="sm" onClick={onClose} disabled={isSubmitting}>
            Cancel
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleSubmit}
            loading={isSubmitting}
            disabled={!hasChanges}
          >
            Submit Edit
          </Button>
        </div>
      </div>
    </Modal>
  )
}
