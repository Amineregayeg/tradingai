import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Badge } from '@/components/ui/Badge'

describe('Badge', () => {
  it('renders children text', () => {
    render(<Badge>Hello Badge</Badge>)
    expect(screen.getByText('Hello Badge')).toBeInTheDocument()
  })

  it('renders as a span element', () => {
    const { container } = render(<Badge>Text</Badge>)
    expect(container.firstChild?.nodeName).toBe('SPAN')
  })

  it('applies neutral variant classes by default', () => {
    const { container } = render(<Badge>Neutral</Badge>)
    const span = container.firstChild as HTMLElement
    // Neutral variant includes bg-[var(--bg-accent)] — check the className contains neutral-related tokens
    expect(span.className).toContain('bg-[var(--bg-accent)]')
  })

  it('applies success variant class', () => {
    const { container } = render(<Badge variant="success">Success</Badge>)
    const span = container.firstChild as HTMLElement
    expect(span.className).toContain('bg-[var(--accent-green-dim)]')
  })

  it('applies danger variant class', () => {
    const { container } = render(<Badge variant="danger">Danger</Badge>)
    const span = container.firstChild as HTMLElement
    expect(span.className).toContain('bg-[var(--accent-red-dim)]')
  })

  it('applies warning variant class', () => {
    const { container } = render(<Badge variant="warning">Warning</Badge>)
    const span = container.firstChild as HTMLElement
    expect(span.className).toContain('bg-[var(--accent-amber-dim)]')
  })

  it('applies info variant class', () => {
    const { container } = render(<Badge variant="info">Info</Badge>)
    const span = container.firstChild as HTMLElement
    expect(span.className).toContain('bg-[var(--accent-blue-dim)]')
  })

  it('applies ai variant class', () => {
    const { container } = render(<Badge variant="ai">AI</Badge>)
    const span = container.firstChild as HTMLElement
    expect(span.className).toContain('bg-[var(--accent-purple-dim)]')
  })

  it('applies sm size class', () => {
    const { container } = render(<Badge size="sm">Small</Badge>)
    const span = container.firstChild as HTMLElement
    expect(span.className).toContain('px-1.5')
  })

  it('applies md size class by default', () => {
    const { container } = render(<Badge>Default size</Badge>)
    const span = container.firstChild as HTMLElement
    expect(span.className).toContain('px-2')
  })

  it('forwards additional HTML attributes', () => {
    render(<Badge data-testid="my-badge">Test</Badge>)
    expect(screen.getByTestId('my-badge')).toBeInTheDocument()
  })

  it('applies custom className', () => {
    const { container } = render(<Badge className="custom-class">Test</Badge>)
    const span = container.firstChild as HTMLElement
    expect(span.className).toContain('custom-class')
  })

  it('renders number children', () => {
    render(<Badge>{42}</Badge>)
    expect(screen.getByText('42')).toBeInTheDocument()
  })
})
