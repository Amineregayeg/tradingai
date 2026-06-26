import { useEffect, useCallback } from 'react'
import { useSettingsStore } from '@/stores/settingsStore'
import { api } from '@/services/api'
import type { Theme } from '@/types/api'

interface UseThemeReturn {
  theme: Theme
  setTheme: (theme: Theme) => void
}

/**
 * Reads and writes the current theme.
 * Applies data-theme attribute to document.documentElement.
 * Falls back to 'dark' if settings not yet loaded.
 */
export function useTheme(): UseThemeReturn {
  const settings = useSettingsStore((s) => s.settings)
  const updateSettings = useSettingsStore((s) => s.updateSettings)

  const theme: Theme = settings?.theme ?? 'dark'

  // Sync to DOM whenever theme changes
  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
  }, [theme])

  const setTheme = useCallback(
    (newTheme: Theme) => {
      // Optimistic update
      updateSettings({ theme: newTheme })
      document.documentElement.setAttribute('data-theme', newTheme)

      // Persist to server
      api.settings.update({ theme: newTheme }).catch(() => {
        // Rollback on failure
        updateSettings({ theme })
        document.documentElement.setAttribute('data-theme', theme)
      })
    },
    [updateSettings, theme]
  )

  return { theme, setTheme }
}
