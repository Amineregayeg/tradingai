import { describe, it, expect, beforeEach } from 'vitest'
import { useSettingsStore } from '@/stores/settingsStore'
import type { Settings } from '@/types/api'

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

// ─── Reset store before each test ────────────────────────────────────────────

beforeEach(() => {
  useSettingsStore.setState({ settings: null, isLoading: false })
})

// ─── Initial state ────────────────────────────────────────────────────────────

describe('settingsStore — initial state', () => {
  it('starts with null settings', () => {
    expect(useSettingsStore.getState().settings).toBeNull()
  })

  it('starts with isLoading = false', () => {
    expect(useSettingsStore.getState().isLoading).toBe(false)
  })
})

// ─── setSettings ──────────────────────────────────────────────────────────────

describe('setSettings', () => {
  it('stores a full settings object', () => {
    const settings = makeSettings()
    useSettingsStore.getState().setSettings(settings)
    expect(useSettingsStore.getState().settings).toEqual(settings)
  })

  it('replaces existing settings with new ones', () => {
    useSettingsStore.getState().setSettings(makeSettings({ theme: 'dark' }))
    useSettingsStore.getState().setSettings(makeSettings({ theme: 'light' }))
    expect(useSettingsStore.getState().settings?.theme).toBe('light')
  })
})

// ─── updateSettings ───────────────────────────────────────────────────────────

describe('updateSettings', () => {
  it('merges partial settings into existing settings', () => {
    const original = makeSettings({ theme: 'dark', max_risk_pct: 1.0 })
    useSettingsStore.getState().setSettings(original)
    useSettingsStore.getState().updateSettings({ theme: 'light' })
    const updated = useSettingsStore.getState().settings
    expect(updated?.theme).toBe('light')
    // Other fields remain unchanged
    expect(updated?.max_risk_pct).toBe(1.0)
  })

  it('preserves all non-updated fields', () => {
    const original = makeSettings()
    useSettingsStore.getState().setSettings(original)
    useSettingsStore.getState().updateSettings({ max_concurrent_positions: 5 })
    const updated = useSettingsStore.getState().settings
    expect(updated?.ai_primary_model).toBe('claude-sonnet-4-6')
    expect(updated?.timezone).toBe('UTC')
    expect(updated?.max_concurrent_positions).toBe(5)
  })

  it('does nothing when settings is null', () => {
    // settings starts null — updateSettings should not throw and settings stays null
    useSettingsStore.getState().updateSettings({ theme: 'light' })
    expect(useSettingsStore.getState().settings).toBeNull()
  })

  it('can update multiple fields at once', () => {
    useSettingsStore.getState().setSettings(makeSettings())
    useSettingsStore.getState().updateSettings({
      theme: 'light',
      max_risk_pct: 2.0,
      max_concurrent_positions: 10,
    })
    const s = useSettingsStore.getState().settings
    expect(s?.theme).toBe('light')
    expect(s?.max_risk_pct).toBe(2.0)
    expect(s?.max_concurrent_positions).toBe(10)
  })
})

// ─── setLoading ───────────────────────────────────────────────────────────────

describe('setLoading', () => {
  it('sets isLoading to true', () => {
    useSettingsStore.getState().setLoading(true)
    expect(useSettingsStore.getState().isLoading).toBe(true)
  })

  it('sets isLoading back to false', () => {
    useSettingsStore.getState().setLoading(true)
    useSettingsStore.getState().setLoading(false)
    expect(useSettingsStore.getState().isLoading).toBe(false)
  })
})
