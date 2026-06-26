import { type HTMLAttributes } from 'react'
import { clsx } from 'clsx'

export type BadgeVariant = 'success' | 'warning' | 'danger' | 'info' | 'neutral' | 'ai'
export type BadgeSize = 'sm' | 'md'

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant
  size?: BadgeSize
}

const variantClasses: Record<BadgeVariant, string> = {
  success: 'bg-[var(--accent-green-dim)] text-[var(--accent-green)] border-[var(--accent-green)]/20',
  warning: 'bg-[var(--accent-amber-dim)] text-[var(--accent-amber)] border-[var(--accent-amber)]/20',
  danger: 'bg-[var(--accent-red-dim)] text-[var(--accent-red)] border-[var(--accent-red)]/20',
  info: 'bg-[var(--accent-blue-dim)] text-[var(--accent-blue)] border-[var(--accent-blue)]/20',
  neutral: 'bg-[var(--bg-accent)] text-[var(--text-secondary)] border-[var(--border)]',
  ai: 'bg-[var(--accent-purple-dim)] text-[var(--accent-purple)] border-[var(--accent-purple)]/20',
}

const sizeClasses: Record<BadgeSize, string> = {
  sm: 'px-1.5 py-0.5 text-[10px] leading-none',
  md: 'px-2 py-1 text-[var(--text-sm)] leading-none',
}

export function Badge({
  variant = 'neutral',
  size = 'md',
  children,
  className,
  ...props
}: BadgeProps) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1 rounded-[var(--radius-sm)] border font-medium',
        'whitespace-nowrap',
        variantClasses[variant],
        sizeClasses[size],
        className
      )}
      {...props}
    >
      {children}
    </span>
  )
}
