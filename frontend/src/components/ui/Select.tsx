import { forwardRef, type SelectHTMLAttributes } from 'react'
import { clsx } from 'clsx'

export interface SelectOption {
  value: string
  label: string
  disabled?: boolean
}

export interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string
  error?: string
  helperText?: string
  options: SelectOption[]
  placeholder?: string
  fullWidth?: boolean
}

export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  (
    {
      label,
      error,
      helperText,
      options,
      placeholder,
      fullWidth = false,
      className,
      id,
      disabled,
      ...props
    },
    ref
  ) => {
    const selectId = id ?? (label ? label.toLowerCase().replace(/\s+/g, '-') : undefined)

    return (
      <div className={clsx('flex flex-col gap-1.5', fullWidth && 'w-full')}>
        {label && (
          <label
            htmlFor={selectId}
            className="text-[var(--text-sm)] font-medium text-[var(--text-secondary)]"
          >
            {label}
          </label>
        )}

        <div className="relative">
          <select
            ref={ref}
            id={selectId}
            disabled={disabled}
            className={clsx(
              'w-full h-9 rounded-[var(--radius-md)] appearance-none',
              'bg-[var(--bg-accent)] border border-[var(--border)]',
              'text-[var(--text-primary)] text-[var(--text-md)]',
              'pl-3 pr-8',
              'transition-colors duration-[var(--duration-fast)]',
              'focus:outline-none focus:border-[var(--accent-blue)] focus:ring-1 focus:ring-[var(--accent-blue)]/30',
              error &&
                'border-[var(--accent-red)] focus:border-[var(--accent-red)] focus:ring-[var(--accent-red)]/30',
              disabled && 'opacity-50 cursor-not-allowed',
              className
            )}
            {...props}
          >
            {placeholder && (
              <option value="" disabled>
                {placeholder}
              </option>
            )}
            {options.map((opt) => (
              <option key={opt.value} value={opt.value} disabled={opt.disabled}>
                {opt.label}
              </option>
            ))}
          </select>

          {/* Chevron icon */}
          <div className="absolute right-2.5 top-1/2 -translate-y-1/2 pointer-events-none text-[var(--text-muted)]">
            <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
              <path
                d="M2.5 4.5L6 8L9.5 4.5"
                stroke="currentColor"
                strokeWidth="1.5"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </div>
        </div>

        {error && <p className="text-[var(--text-sm)] text-[var(--accent-red)]">{error}</p>}

        {!error && helperText && (
          <p className="text-[var(--text-sm)] text-[var(--text-muted)]">{helperText}</p>
        )}
      </div>
    )
  }
)

Select.displayName = 'Select'
