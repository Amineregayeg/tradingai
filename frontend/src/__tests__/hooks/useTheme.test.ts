import { describe, it, expect, beforeEach, vi } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useSettingsStore } from '@/stores/settingsStore'
import type { Settings } from '@/types/api'

// ─── Mock api service ─────────────────────────────────────────────────────────

vi.mock('@/services/api', () => ({
  api: {
    settings: {
      update: vi.fn().mockResolvedValue({}),
    },
  },
}))

// ─── Helpers ─────────────────────────────────────────────────────────────────

function makeSettings(overrides: Partial<Settings> = {}): Settings {
  return {
    user_id: 'system',
    ai_enabled: true,
    ai_primary_model: 'claude-sonnet-4-6',
    ai_screening_model: 'claude-haiku-4-5',
    ai_monthly_budget_usd: 50,
    ai_used_current_month_usd: 0,
    alert_sound: true,
    desktop_notifications: true,
    auto_screenshot_on_open: true,
    auto_screenshot_interval: 15,
    max_risk_pct: 1.0,
    max_daily_loss_pct: 5.0,
    max_concurrent_positions: 3,
    require_checklist: false,
    timezone: 'UTC',
    theme: 'dark',
    updated_at: '2024-05-16T00:00:00.000Z',
    ...overrides,
  }
}

// ─── Reset store & DOM before each test ──────────────────────────────────────

beforeEach(() => {
  useSettingsStore.setState({ settings: null, isLoading: false })
  document.documentElement.removeAttribute('data-theme')
  vi.clearAllMocks()
})

// ─── Tests ────────────────────────────────────────────────────────────────────

describe('useTheme', () => {
  it('returns dark as default theme when settings are null', async () => {
    const { useTheme } = await import('@/hooks/useTheme')
    const { result } = renderHook(() => useTheme())
    expect(result.current.theme).toBe('dark')
  })

  it('returns the theme from settings when settings are loaded', async () => {
    useSettingsStore.getState().setSettings(makeSettings({ theme: 'light' }))
    const { useTheme } = await import('@/hooks/useTheme')
    const { result } = renderHook(() => useTheme())
    expect(result.current.theme).toBe('light')
  })

  it('applies data-theme attribute to document.documentElement on mount', async () => {
    useSettingsStore.getState().setSettings(makeSettings({ theme: 'dark' }))
    const { useTheme } = await import('@/hooks/useTheme')
    renderHook(() => useTheme())
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })

  it('setTheme updates the DOM data-theme attribute immediately', async () => {
    useSettingsStore.getState().setSettings(makeSettings({ theme: 'dark' }))
    const { useTheme } = await import('@/hooks/useTheme')
    const { result } = renderHook(() => useTheme())

    act(() => {
      result.current.setTheme('light')
    })

    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })

  it('setTheme optimistically updates the store theme', async () => {
    useSettingsStore.getState().setSettings(makeSettings({ theme: 'dark' }))
    const { useTheme } = await import('@/hooks/useTheme')
    const { result } = renderHook(() => useTheme())

    act(() => {
      result.current.setTheme('light')
    })

    expect(result.current.theme).toBe('light')
  })

  it('setTheme calls api.settings.update with the new theme', async () => {
    const { api } = await import('@/services/api')
    useSettingsStore.getState().setSettings(makeSettings({ theme: 'dark' }))
    const { useTheme } = await import('@/hooks/useTheme')
    const { result } = renderHook(() => useTheme())

    act(() => {
      result.current.setTheme('light')
    })

    expect(api.settings.update).toHaveBeenCalledWith({ theme: 'light' })
  })

  it('rolls back to original theme on API failure', async () => {
    const { api } = await import('@/services/api')
    // Make the API call fail
    vi.mocked(api.settings.update).mockRejectedValueOnce(new Error('Network error'))

    useSettingsStore.getState().setSettings(makeSettings({ theme: 'dark' }))
    const { useTheme } = await import('@/hooks/useTheme')
    const { result } = renderHook(() => useTheme())

    act(() => {
      result.current.setTheme('light')
    })

    // Wait for the rejected promise to trigger rollback
    await act(async () => {
      await Promise.resolve()
    })

    expect(result.current.theme).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
  })
})
