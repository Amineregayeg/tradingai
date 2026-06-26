import { Badge } from '@/components/ui'
import type { Alert, AlertPriority, AlertType } from '@/types/api'
import { formatDateTime } from '@/utils/format'
import { parseISO, formatDistanceToNow } from 'date-fns'

export interface AlertItemProps {
  alert: Alert
  compact?: boolean
}

const priorityBorderColor: Record<AlertPriority, string> = {
  INFO: 'var(--accent-blue)',
  SUGGESTION: 'var(--accent-green)',
  WARNING: 'var(--accent-amber)',
  CRITICAL: 'var(--accent-red)',
}

const priorityBadgeVariant: Record<AlertPriority, 'info' | 'success' | 'warning' | 'danger'> = {
  INFO: 'info',
  SUGGESTION: 'success',
  WARNING: 'warning',
  CRITICAL: 'danger',
}

const typeLabel: Record<AlertType, string> = {
  ENTRY_SIGNAL: 'Entry Signal',
  EXIT_MGMT: 'Exit Mgmt',
  RISK_WARNING: 'Risk Warning',
  PATTERN: 'Pattern',
  PSYCHOLOGY: 'Psychology',
}

const statusVariant: Record<string, 'success' | 'warning' | 'danger' | 'neutral' | 'info'> = {
  PENDING: 'warning',
  APPROVED: 'success',
  REJECTED: 'danger',
  EDITED: 'info',
  EXECUTING: 'info',
  EXECUTED: 'success',
  FAILED: 'danger',
  EXPIRED: 'neutral',
  SUPERSEDED: 'neutral',
}

function timeAgo(iso: string): string {
  try {
    return formatDistanceToNow(parseISO(iso), { addSuffix: true })
  } catch {
    return formatDateTime(iso)
  }
}

export function AlertItem({ alert, compact = false }: AlertItemProps) {
  const borderColor = priorityBorderColor[alert.priority]

  return (
    <div
      style={{
        borderLeft: `3px solid ${borderColor}`,
        paddingLeft: 'var(--space-3)',
        paddingTop: 'var(--space-2)',
        paddingBottom: 'var(--space-2)',
        display: 'flex',
        flexDirection: 'column',
        gap: 'var(--space-1)',
      }}
    >
      {/* Top row: type chip + pair + status */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 'var(--space-2)', flexWrap: 'wrap' }}>
        <Badge variant={priorityBadgeVariant[alert.priority]} size="sm">
          {alert.priority}
        </Badge>
        <Badge variant="neutral" size="sm">
          {typeLabel[alert.type]}
        </Badge>
        {alert.pair && (
          <span
            style={{
              fontSize: 'var(--text-sm)',
              fontWeight: 'var(--weight-semibold)',
              color: 'var(--text-primary)',
            }}
          >
            {alert.pair}
          </span>
        )}
        <div style={{ marginLeft: 'auto' }}>
          <Badge variant={statusVariant[alert.status] ?? 'neutral'} size="sm">
            {alert.status}
          </Badge>
        </div>
      </div>

      {/* Title + message */}
      <div>
        <p
          style={{
            fontSize: 'var(--text-sm)',
            fontWeight: 'var(--weight-medium)',
            color: 'var(--text-primary)',
            marginBottom: compact ? 0 : 'var(--space-0-5)',
          }}
        >
          {alert.title}
        </p>
        {!compact && (
          <p style={{ fontSize: 'var(--text-sm)', color: 'var(--text-secondary)' }}>
            {alert.message}
          </p>
        )}
      </div>

      {/* Bottom row: time + confidence */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: 'var(--space-3)',
          fontSize: 'var(--text-xs)',
          color: 'var(--text-muted)',
        }}
      >
        <span>{timeAgo(alert.created_at)}</span>
        {alert.r_ratio !== null && alert.r_ratio !== undefined && (
          <span>R: {alert.r_ratio.toFixed(2)}</span>
        )}
      </div>
    </div>
  )
}
