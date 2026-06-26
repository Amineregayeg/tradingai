import { create } from 'zustand'
import type { TickData } from '@/types/ws'

interface PricesState {
  ticks: Record<string, TickData>
  watchedPairs: string[]
  updateTick: (tick: TickData) => void
  addWatchedPair: (pair: string) => void
  removeWatchedPair: (pair: string) => void
}

export const usePricesStore = create<PricesState>((set) => ({
  ticks: {},
  watchedPairs: [],

  updateTick: (tick) =>
    set((state) => ({
      ticks: { ...state.ticks, [tick.pair]: tick },
    })),

  addWatchedPair: (pair) =>
    set((state) =>
      state.watchedPairs.includes(pair)
        ? {}
        : { watchedPairs: [...state.watchedPairs, pair] }
    ),

  removeWatchedPair: (pair) =>
    set((state) => ({
      watchedPairs: state.watchedPairs.filter((p) => p !== pair),
    })),
}))
