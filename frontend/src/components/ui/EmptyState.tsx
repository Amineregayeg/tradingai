import { type ReactNode } from 'react'
import { clsx } from 'clsx'
import { Button } from './Button'

export interface EmptyStateProps {
  icon?: ReactNode
  title: string
  description?: string
  action?: {
    label: string
    onClick: () => void
  }
  className?: string
}

export function EmptyState({ icon, title, description, action, className }: EmptyStateProps) {
  return (
    <div
      className={clsx(
        'flex flex-col items-center justify-center gap-3 py-12 px-6 text-center',
        className
      )}
    >
      {icon && (
        <div className="w-12 h-12 flex items-center justify-center rounded-[var(--radius-xl)] bg-[var(--bg-accent)] text-[var(--text-muted)]">
          {icon}
        </div>
      )}

      <div className="flex flex-col gap-1">
        <p className="text-[var(--text-md)] font-medium text-[var(--text-primary)]">{title}</p>
        {description && (
          <p className="text-[var(--text-sm)] text-[var(--text-secondary)] max-w-xs">{description}</p>
        )}
      </div>

      {action && (
        <Button variant="secondary" size="sm" onClick={action.onClick}>
          {action.label}
        </Button>
      )}
    </div>
  )
}
