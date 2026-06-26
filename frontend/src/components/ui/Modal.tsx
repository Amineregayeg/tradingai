import { useEffect, useCallback, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { clsx } from 'clsx'

export interface ModalProps {
  open: boolean
  onClose: () => void
  title?: string
  description?: string
  children: ReactNode
  /** Max width of the modal panel */
  size?: 'sm' | 'md' | 'lg' | 'xl' | 'full'
  /** Whether to show the default header with title */
  showHeader?: boolean
  className?: string
}

const sizeClasses = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-xl',
  full: 'max-w-[90vw]',
}

export function Modal({
  open,
  onClose,
  title,
  description,
  children,
  size = 'md',
  showHeader = true,
  className,
}: ModalProps) {
  // Close on ESC key
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    },
    [onClose]
  )

  useEffect(() => {
    if (open) {
      document.addEventListener('keydown', handleKeyDown)
      document.body.style.overflow = 'hidden'
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      document.body.style.overflow = ''
    }
  }, [open, handleKeyDown])

  if (!open) return null

  return createPortal(
    <div
      className="fixed inset-0 flex items-center justify-center p-4"
      style={{ zIndex: 'var(--z-modal)' }}
      role="dialog"
      aria-modal="true"
      aria-labelledby={title ? 'modal-title' : undefined}
      aria-describedby={description ? 'modal-description' : undefined}
    >
      {/* Backdrop */}
      <div
        className="absolute inset-0 bg-black/60 backdrop-blur-sm"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Panel */}
      <div
        className={clsx(
          'relative w-full rounded-[var(--radius-xl)]',
          'bg-[var(--bg-card)] border border-[var(--border)]',
          'shadow-[var(--shadow-lg)]',
          'animate-fade-in',
          sizeClasses[size],
          className
        )}
      >
        {showHeader && title && (
          <div className="flex items-center justify-between px-6 py-4 border-b border-[var(--border)]">
            <div>
              <h2
                id="modal-title"
                className="text-[var(--text-lg)] font-semibold text-[var(--text-primary)]"
              >
                {title}
              </h2>
              {description && (
                <p
                  id="modal-description"
                  className="mt-0.5 text-[var(--text-sm)] text-[var(--text-secondary)]"
                >
                  {description}
                </p>
              )}
            </div>
            <button
              onClick={onClose}
              className={clsx(
                'w-8 h-8 flex items-center justify-center rounded-[var(--radius-md)]',
                'text-[var(--text-muted)] hover:text-[var(--text-primary)]',
                'hover:bg-[var(--bg-accent)]',
                'transition-colors duration-[var(--duration-fast)]'
              )}
              aria-label="Close modal"
            >
              <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                <path
                  d="M12 4L4 12M4 4l8 8"
                  stroke="currentColor"
                  strokeWidth="1.5"
                  strokeLinecap="round"
                />
              </svg>
            </button>
          </div>
        )}

        <div className="p-6">{children}</div>
      </div>
    </div>,
    document.body
  )
}
