import { forwardRef, type InputHTMLAttributes, type ReactNode } from 'react'
import { clsx } from 'clsx'

export interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string
  error?: string
  helperText?: string
  leftAddon?: ReactNode
  rightAddon?: ReactNode
  /** Full width */
  fullWidth?: boolean
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  (
    {
      label,
      error,
      helperText,
      leftAddon,
      rightAddon,
      fullWidth = false,
      className,
      id,
      disabled,
      ...props
    },
    ref
  ) => {
    const inputId = id ?? (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined)

    return (
      <div className={clsx('flex flex-col gap-1.5', fullWidth && 'w-full')}>
        {label && (
          <label
            htmlFor={inputId}
            className="text-[var(--text-sm)] font-medium text-[var(--text-secondary)]"
          >
            {label}
          </label>
        )}

        <div className="relative flex items-center">
          {leftAddon && (
            <div className="absolute left-3 flex items-center text-[var(--text-muted)] pointer-events-none">
              {leftAddon}
            </div>
          )}

          <input
            ref={ref}
            id={inputId}
            disabled={disabled}
            className={clsx(
              'w-full h-9 rounded-[var(--radius-md)]',
              'bg-[var(--bg-accent)] border border-[var(--border)]',
              'text-[var(--text-primary)] text-[var(--text-md)]',
              'placeholder:text-[var(--text-muted)]',
              'px-3',
              'transition-colors duration-[var(--duration-fast)]',
              'focus:outline-none focus:border-[var(--accent-blue)] focus:ring-1 focus:ring-[var(--accent-blue)]/30',
              error && 'border-[var(--accent-red)] focus:border-[var(--accent-red)] focus:ring-[var(--accent-red)]/30',
              disabled && 'opacity-50 cursor-not-allowed',
              leftAddon && 'pl-9',
              rightAddon && 'pr-9',
              className
            )}
            {...props}
          />

          {rightAddon && (
            <div className="absolute right-3 flex items-center text-[var(--text-muted)] pointer-events-none">
              {rightAddon}
            </div>
          )}
        </div>

        {error && (
          <p className="text-[var(--text-sm)] text-[var(--accent-red)]">{error}</p>
        )}

        {!error && helperText && (
          <p className="text-[var(--text-sm)] text-[var(--text-muted)]">{helperText}</p>
        )}
      </div>
    )
  }
)

Input.displayName = 'Input'
