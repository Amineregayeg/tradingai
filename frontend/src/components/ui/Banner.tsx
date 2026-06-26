import { useState, type ReactNode } from 'react'
import { clsx } from 'clsx'

export type BannerVariant = 'warning' | 'error' | 'info'

export interface BannerProps {
  variant?: BannerVariant
  title?: string
  children: ReactNode
  dismissible?: boolean
  fixed?: boolean
  onDismiss?: () => void
  className?: string
}

const variantConfig: Record<
  BannerVariant,
  { bg: string; border: string; text: string; icon: ReactNode }
> = {
  warning: {
    bg: 'bg-[var(--accent-amber-dim)]',
    border: 'border-[var(--accent-amber)]/30',
    text: 'text-[var(--accent-amber)]',
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <path
          d="M8 2L14.5 13H1.5L8 2Z"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        <path d="M8 6v3M8 11v.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
  },
  error: {
    bg: 'bg-[var(--accent-red-dim)]',
    border: 'border-[var(--accent-red)]/30',
    text: 'text-[var(--accent-red)]',
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
        <path d="M8 5v3M8 10v.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
  },
  info: {
    bg: 'bg-[var(--accent-blue-dim)]',
    border: 'border-[var(--accent-blue)]/30',
    text: 'text-[var(--accent-blue)]',
    icon: (
      <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
        <circle cx="8" cy="8" r="6" stroke="currentColor" strokeWidth="1.5" />
        <path d="M8 7.5v3M8 5.5v.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    ),
  },
}

export function Banner({
  variant = 'info',
  title,
  children,
  dismissible = false,
  fixed = false,
  onDismiss,
  className,
}: BannerProps) {
  const [dismissed, setDismissed] = useState(false)
  const config = variantConfig[variant]

  if (dismissed) return null

  const handleDismiss = () => {
    setDismissed(true)
    onDismiss?.()
  }

  return (
    <div
      role="alert"
      className={clsx(
        'flex items-start gap-3 px-4 py-3',
        'rounded-[var(--radius-lg)] border',
        config.bg,
        config.border,
        config.text,
        fixed && 'fixed top-4 left-1/2 -translate-x-1/2 min-w-80 max-w-lg shadow-[var(--shadow-md)]',
        fixed && 'z-[var(--z-banner)]',
        className
      )}
    >
      <span className="flex-shrink-0 mt-0.5">{config.icon}</span>

      <div className="flex-1 text-[var(--text-sm)]">
        {title && <p className="font-semibold mb-0.5">{title}</p>}
        <div>{children}</div>
      </div>

      {dismissible && (
        <button
          onClick={handleDismiss}
          className="flex-shrink-0 opacity-70 hover:opacity-100 transition-opacity"
          aria-label="Dismiss"
        >
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <path
              d="M11 3L3 11M3 3l8 8"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </button>
      )}
    </div>
  )
}
