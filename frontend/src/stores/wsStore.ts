import { create } from 'zustand'

type WSConnectionStatus = 'connecting' | 'connected' | 'disconnected'

interface WSState {
  status: WSConnectionStatus
  reconnectAttempts: number
  setStatus: (status: WSConnectionStatus) => void
  incrementReconnects: () => void
  resetReconnects: () => void
}

export const useWSStore = create<WSState>((set) => ({
  status: 'disconnected',
  reconnectAttempts: 0,

  setStatus: (status) => set({ status }),

  incrementReconnects: () =>
    set((state) => ({ reconnectAttempts: state.reconnectAttempts + 1 })),

  resetReconnects: () => set({ reconnectAttempts: 0 }),
}))
