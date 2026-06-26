import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Button } from '@/components/ui/Button'

describe('Button', () => {
  // ── Rendering ──────────────────────────────────────────────────────────────

  it('renders with text content', () => {
    render(<Button>Click Me</Button>)
    expect(screen.getByText('Click Me')).toBeInTheDocument()
  })

  it('renders a <button> element', () => {
    render(<Button>Test</Button>)
    expect(screen.getByRole('button')).toBeInTheDocument()
  })

  it('applies primary variant classes by default', () => {
    render(<Button>Primary</Button>)
    const btn = screen.getByRole('button')
    expect(btn.className).toContain('bg-[var(--accent-blue)]')
  })

  it('applies secondary variant classes', () => {
    render(<Button variant="secondary">Secondary</Button>)
    const btn = screen.getByRole('button')
    expect(btn.className).toContain('bg-[var(--bg-accent)]')
  })

  it('applies danger variant classes', () => {
    render(<Button variant="danger">Danger</Button>)
    const btn = screen.getByRole('button')
    expect(btn.className).toContain('bg-[var(--accent-red)]')
  })

  it('applies ghost variant classes', () => {
    render(<Button variant="ghost">Ghost</Button>)
    const btn = screen.getByRole('button')
    expect(btn.className).toContain('bg-transparent')
  })

  // ── Sizes ──────────────────────────────────────────────────────────────────

  it('applies sm size class', () => {
    render(<Button size="sm">Small</Button>)
    expect(screen.getByRole('button').className).toContain('h-7')
  })

  it('applies md size class by default', () => {
    render(<Button>Default</Button>)
    expect(screen.getByRole('button').className).toContain('h-9')
  })

  it('applies lg size class', () => {
    render(<Button size="lg">Large</Button>)
    expect(screen.getByRole('button').className).toContain('h-11')
  })

  // ── Click behavior ─────────────────────────────────────────────────────────

  it('calls onClick when clicked', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Click</Button>)
    await user.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('does not call onClick when disabled', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<Button disabled onClick={onClick}>Disabled</Button>)
    await user.click(screen.getByRole('button'))
    expect(onClick).not.toHaveBeenCalled()
  })

  // ── Loading state ──────────────────────────────────────────────────────────

  it('shows spinner when loading=true', () => {
    render(<Button loading>Submit</Button>)
    // Spinner has role="status"
    expect(screen.getByRole('status')).toBeInTheDocument()
  })

  it('is disabled when loading=true', () => {
    render(<Button loading>Submit</Button>)
    expect(screen.getByRole('button')).toBeDisabled()
  })

  it('sets aria-busy when loading', () => {
    render(<Button loading>Submit</Button>)
    expect(screen.getByRole('button')).toHaveAttribute('aria-busy', 'true')
  })

  it('does not show spinner when loading=false', () => {
    render(<Button loading={false}>Submit</Button>)
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
  })

  it('does not call onClick when loading', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<Button loading onClick={onClick}>Submit</Button>)
    await user.click(screen.getByRole('button'))
    expect(onClick).not.toHaveBeenCalled()
  })

  // ── Icons ──────────────────────────────────────────────────────────────────

  it('renders leftIcon when not loading', () => {
    render(<Button leftIcon={<span data-testid="left-icon" />}>With Icon</Button>)
    expect(screen.getByTestId('left-icon')).toBeInTheDocument()
  })

  it('does not render leftIcon when loading (spinner replaces it)', () => {
    render(<Button loading leftIcon={<span data-testid="left-icon" />}>Loading</Button>)
    expect(screen.queryByTestId('left-icon')).not.toBeInTheDocument()
  })

  it('renders rightIcon when not loading', () => {
    render(<Button rightIcon={<span data-testid="right-icon" />}>With Icon</Button>)
    expect(screen.getByTestId('right-icon')).toBeInTheDocument()
  })

  it('hides rightIcon when loading', () => {
    render(<Button loading rightIcon={<span data-testid="right-icon" />}>Loading</Button>)
    expect(screen.queryByTestId('right-icon')).not.toBeInTheDocument()
  })

  // ── Custom className ───────────────────────────────────────────────────────

  it('applies custom className', () => {
    render(<Button className="my-custom-class">Test</Button>)
    expect(screen.getByRole('button').className).toContain('my-custom-class')
  })

  // ── Disabled prop ──────────────────────────────────────────────────────────

  it('is disabled when disabled prop is true', () => {
    render(<Button disabled>Disabled</Button>)
    expect(screen.getByRole('button')).toBeDisabled()
  })

  it('is not disabled by default', () => {
    render(<Button>Normal</Button>)
    expect(screen.getByRole('button')).not.toBeDisabled()
  })

  // ── Ref forwarding ─────────────────────────────────────────────────────────

  it('forwards ref to the button element', () => {
    const ref = { current: null as HTMLButtonElement | null }
    render(<Button ref={ref}>Ref Test</Button>)
    expect(ref.current).not.toBeNull()
    expect(ref.current?.tagName).toBe('BUTTON')
  })
})
