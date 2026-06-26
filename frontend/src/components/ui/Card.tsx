import { type HTMLAttributes, forwardRef } from 'react'
import { clsx } from 'clsx'

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  hoverable?: boolean
  padded?: boolean
}

export const Card = forwardRef<HTMLDivElement, CardProps>(
  ({ hoverable = false, padded = true, children, className, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={clsx(
          'rounded-[var(--radius-lg)] border border-[var(--border)]',
          'bg-[var(--bg-card)]',
          'transition-colors duration-[var(--duration-fast)]',
          padded && 'p-4',
          hoverable && 'cursor-pointer hover:bg-[var(--bg-card-hover)] hover:border-[var(--border-light)]',
          className
        )}
        {...props}
      >
        {children}
      </div>
    )
  }
)

Card.displayName = 'Card'

// ─── Card sub-components ──────────────────────────────────────────────────────

export interface CardHeaderProps extends HTMLAttributes<HTMLDivElement> {}

export function CardHeader({ children, className, ...props }: CardHeaderProps) {
  return (
    <div
      className={clsx(
        'flex items-center justify-between pb-3 mb-3 border-b border-[var(--border)]',
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}

export interface CardTitleProps extends HTMLAttributes<HTMLHeadingElement> {}

export function CardTitle({ children, className, ...props }: CardTitleProps) {
  return (
    <h3
      className={clsx('text-[var(--text-md)] font-semibold text-[var(--text-primary)]', className)}
      {...props}
    >
      {children}
    </h3>
  )
}

export interface CardFooterProps extends HTMLAttributes<HTMLDivElement> {}

export function CardFooter({ children, className, ...props }: CardFooterProps) {
  return (
    <div
      className={clsx(
        'flex items-center gap-2 pt-3 mt-3 border-t border-[var(--border)]',
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
}
