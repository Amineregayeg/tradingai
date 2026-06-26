import { useState, useRef, type ReactNode, type CSSProperties } from 'react'
import { clsx } from 'clsx'

export type TooltipPlacement = 'top' | 'bottom' | 'left' | 'right'

export interface TooltipProps {
  content: ReactNode
  children: ReactNode
  placement?: TooltipPlacement
  delay?: number
  className?: string
}

const placementStyles: Record<TooltipPlacement, CSSProperties> = {
  top: { bottom: '100%', left: '50%', transform: 'translateX(-50%)', marginBottom: 6 },
  bottom: { top: '100%', left: '50%', transform: 'translateX(-50%)', marginTop: 6 },
  left: { right: '100%', top: '50%', transform: 'translateY(-50%)', marginRight: 6 },
  right: { left: '100%', top: '50%', transform: 'translateY(-50%)', marginLeft: 6 },
}

export function Tooltip({
  content,
  children,
  placement = 'top',
  delay = 400,
  className,
}: TooltipProps) {
  const [visible, setVisible] = useState(false)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const show = () => {
    timeoutRef.current = setTimeout(() => setVisible(true), delay)
  }

  const hide = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    setVisible(false)
  }

  return (
    <span
      className="relative inline-flex"
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}

      {visible && content && (
        <span
          role="tooltip"
          className={clsx(
            'absolute z-[var(--z-dropdown)] pointer-events-none',
            'px-2.5 py-1.5 rounded-[var(--radius-md)]',
            'bg-[var(--bg-secondary)] border border-[var(--border)]',
            'text-[var(--text-sm)] text-[var(--text-primary)] whitespace-nowrap',
            'shadow-[var(--shadow-md)]',
            'animate-fade-in',
            className
          )}
          style={placementStyles[placement]}
        >
          {content}
        </span>
      )}
    </span>
  )
}
