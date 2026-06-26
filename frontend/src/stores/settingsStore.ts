import { create } from 'zustand'
import type { Settings } from '@/types/api'

interface SettingsState {
  settings: Settings | null
  isLoading: boolean
  setSettings: (settings: Settings) => void
  updateSettings: (partial: Partial<Settings>) => void
  setLoading: (isLoading: boolean) => void
}

export const useSettingsStore = create<SettingsState>((set) => ({
  settings: null,
  isLoading: false,

  setSettings: (settings) => set({ settings }),

  updateSettings: (partial) =>
    set((state) => ({
      settings: state.settings ? { ...state.settings, ...partial } : null,
    })),

  setLoading: (isLoading) => set({ isLoading }),
}))
