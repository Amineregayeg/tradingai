import { create } from 'zustand'
import type { Trade } from '@/types/api'

interface TradesState {
  trades: Trade[]
  isLoading: boolean
  total: number
  page: number
  setTrades: (trades: Trade[], total: number, page: number) => void
  appendTrade: (trade: Trade) => void
  updateTrade: (id: string, changes: Partial<Trade>) => void
  setLoading: (isLoading: boolean) => void
}

export const useTradesStore = create<TradesState>((set) => ({
  trades: [],
  isLoading: false,
  total: 0,
  page: 1,

  setTrades: (trades, total, page) => set({ trades, total, page }),

  appendTrade: (trade) =>
    set((state) => ({
      trades: [trade, ...state.trades],
      total: state.total + 1,
    })),

  updateTrade: (id, changes) =>
    set((state) => ({
      trades: state.trades.map((t) => (t.id === id ? { ...t, ...changes } : t)),
    })),

  setLoading: (isLoading) => set({ isLoading }),
}))
