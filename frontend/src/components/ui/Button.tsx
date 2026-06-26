import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react'
import { clsx } from 'clsx'
import { Spinner } from './Spinner'

export type ButtonVariant = 'primary' | 'secondary' | 'danger' | 'ghost'
export type ButtonSize = 'sm' | 'md' | 'lg'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
  size?: ButtonSize
  loading?: boolean
  leftIcon?: ReactNode
  rightIcon?: ReactNode
}

const variantClasses: Record<ButtonVariant, string> = {
  primary: [
    'bg-[var(--accent-blue)] text-white',
    'hover:bg-[var(--accent-blue)]/90',
    'active:bg-[var(--accent-blue)]/80',
    'disabled:bg-[var(--accent-blue)]/40 disabled:cursor-not-allowed',
  ].join(' '),
  secondary: [
    'bg-[var(--bg-accent)] text-[var(--text-primary)]',
    'border border-[var(--border)]',
    'hover:bg-[var(--bg-card-hover)] hover:border-[var(--border-light)]',
    'active:bg-[var(--bg-accent-2)]',
    'disabled:opacity-50 disabled:cursor-not-allowed',
  ].join(' '),
  danger: [
    'bg-[var(--accent-red)] text-white',
    'hover:bg-[var(--accent-red)]/90',
    'active:bg-[var(--accent-red)]/80',
    'disabled:bg-[var(--accent-red)]/40 disabled:cursor-not-allowed',
  ].join(' '),
  ghost: [
    'bg-transparent text-[var(--text-secondary)]',
    'hover:bg-[var(--bg-accent)] hover:text-[var(--text-primary)]',
    'active:bg-[var(--bg-accent-2)]',
    'disabled:opacity-50 disabled:cursor-not-allowed',
  ].join(' '),
}

const sizeClasses: Record<ButtonSize, string> = {
  sm: 'h-7 px-3 text-[var(--text-sm)] gap-1.5',
  md: 'h-9 px-4 text-[var(--text-md)] gap-2',
  lg: 'h-11 px-5 text-[var(--text-lg)] gap-2',
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = 'primary',
      size = 'md',
      loading = false,
      leftIcon,
      rightIcon,
      children,
      className,
      disabled,
      ...props
    },
    ref
  ) => {
    const isDisabled = disabled || loading

    return (
      <button
        ref={ref}
        className={clsx(
          'inline-flex items-center justify-center font-medium rounded-[var(--radius-md)]',
          'transition-all duration-[var(--duration-fast)]',
          'focus-visible:outline focus-visible:outline-2 focus-visible:outline-[var(--accent-blue)] focus-visible:outline-offset-2',
          'select-none whitespace-nowrap',
          variantClasses[variant],
          sizeClasses[size],
          className
        )}
        disabled={isDisabled}
        aria-busy={loading}
        {...props}
      >
        {loading ? (
          <Spinner size={size === 'lg' ? 'md' : 'sm'} />
        ) : (
          leftIcon && <span className="flex-shrink-0">{leftIcon}</span>
        )}
        {children && <span>{children}</span>}
        {!loading && rightIcon && <span className="flex-shrink-0">{rightIcon}</span>}
      </button>
    )
  }
)

Button.displayName = 'Button'
