import { clsx } from 'clsx'

export type SpinnerSize = 'xs' | 'sm' | 'md' | 'lg'

export interface SpinnerProps {
  size?: SpinnerSize
  className?: string
  label?: string
}

const sizeClasses: Record<SpinnerSize, string> = {
  xs: 'w-3 h-3 border-[1.5px]',
  sm: 'w-4 h-4 border-2',
  md: 'w-5 h-5 border-2',
  lg: 'w-8 h-8 border-[3px]',
}

export function Spinner({ size = 'md', className, label = 'Loading...' }: SpinnerProps) {
  return (
    <span
      role="status"
      aria-label={label}
      className={clsx(
        'inline-block rounded-full',
        'border-[var(--border-light)] border-t-[var(--accent-blue)]',
        'animate-spin',
        sizeClasses[size],
        className
      )}
      style={{ animationDuration: '0.65s' }}
    />
  )
}
