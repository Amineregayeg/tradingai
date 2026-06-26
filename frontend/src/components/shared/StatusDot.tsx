import { clsx } from 'clsx'
import { Tooltip } from '@/components/ui/Tooltip'

export type ConnectionStatus = 'connected' | 'degraded' | 'disconnected' | 'connecting'

export interface StatusDotProps {
  status: ConnectionStatus
  label?: string
  showLabel?: boolean
  size?: 'sm' | 'md'
  className?: string
}

const statusConfig: Record<
  ConnectionStatus,
  { color: string; pulse: boolean; defaultLabel: string }
> = {
  connected: {
    color: 'bg-[var(--accent-green)]',
    pulse: true,
    defaultLabel: 'Connected',
  },
  degraded: {
    color: 'bg-[var(--accent-amber)]',
    pulse: true,
    defaultLabel: 'Degraded',
  },
  disconnected: {
    color: 'bg-[var(--accent-red)]',
    pulse: false,
    defaultLabel: 'Disconnected',
  },
  connecting: {
    color: 'bg-[var(--accent-blue)]',
    pulse: true,
    defaultLabel: 'Connecting',
  },
}

const sizeClasses = {
  sm: 'w-1.5 h-1.5',
  md: 'w-2 h-2',
}

export function StatusDot({
  status,
  label,
  showLabel = false,
  size = 'md',
  className,
}: StatusDotProps) {
  const config = statusConfig[status]
  const displayLabel = label ?? config.defaultLabel

  const dot = (
    <span className={clsx('relative inline-flex', className)}>
      <span
        className={clsx(
          'rounded-full inline-block flex-shrink-0',
          config.color,
          sizeClasses[size]
        )}
      />
      {config.pulse && (
        <span
          className={clsx(
            'absolute inline-flex rounded-full opacity-75 animate-ping',
            config.color,
            sizeClasses[size]
          )}
        />
      )}
    </span>
  )

  if (showLabel) {
    return (
      <span className="inline-flex items-center gap-1.5">
        {dot}
        <span className="text-[var(--text-sm)] text-[var(--text-secondary)]">{displayLabel}</span>
      </span>
    )
  }

  return <Tooltip content={displayLabel}>{dot}</Tooltip>
}
