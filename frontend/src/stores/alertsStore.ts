import { create } from 'zustand'
import type { Alert, AlertStatus } from '@/types/api'

interface AlertsState {
  pending: Alert[]
  history: Alert[]
  badge: number
  addAlert: (alert: Alert) => void
  resolveAlert: (id: string, status: AlertStatus) => void
  expireAlert: (id: string) => void
  loadPending: (alerts: Alert[]) => void
  clearBadge: () => void
}

export const useAlertsStore = create<AlertsState>((set) => ({
  pending: [],
  history: [],
  badge: 0,

  addAlert: (alert) =>
    set((state) => ({
      pending:
        alert.status === 'PENDING' ? [...state.pending, alert] : state.pending,
      history:
        alert.status !== 'PENDING' ? [alert, ...state.history] : state.history,
      badge: alert.status === 'PENDING' ? state.badge + 1 : state.badge,
    })),

  resolveAlert: (id, status) =>
    set((state) => {
      const alert = state.pending.find((a) => a.id === id)
      if (!alert) return {}
      const resolved: Alert = { ...alert, status }
      return {
        pending: state.pending.filter((a) => a.id !== id),
        history: [resolved, ...state.history],
      }
    }),

  expireAlert: (id) =>
    set((state) => {
      const alert = state.pending.find((a) => a.id === id)
      if (!alert) return {}
      const expired: Alert = { ...alert, status: 'EXPIRED' }
      return {
        pending: state.pending.filter((a) => a.id !== id),
        history: [expired, ...state.history],
      }
    }),

  loadPending: (alerts) => {
    const safe = Array.isArray(alerts) ? alerts : []
    set({
      pending: safe.filter((a) => a.status === 'PENDING'),
      badge: safe.filter((a) => a.status === 'PENDING').length,
    })
  },

  clearBadge: () => set({ badge: 0 }),
}))
