import { create } from 'zustand'
import type { Position } from '@/types/api'

interface PositionsState {
  positions: Position[]
  isLoading: boolean
  setPositions: (positions: Position[]) => void
  updatePosition: (position: Position) => void
  removePosition: (id: string) => void
  setLoading: (isLoading: boolean) => void
}

export const usePositionsStore = create<PositionsState>((set) => ({
  positions: [],
  isLoading: false,

  setPositions: (positions) => set({ positions }),

  updatePosition: (position) =>
    set((state) => {
      const idx = state.positions.findIndex((p) => p.id === position.id)
      if (idx === -1) {
        return { positions: [...state.positions, position] }
      }
      const next = [...state.positions]
      next[idx] = position
      return { positions: next }
    }),

  removePosition: (id) =>
    set((state) => ({
      positions: state.positions.filter((p) => p.id !== id),
    })),

  setLoading: (isLoading) => set({ isLoading }),
}))
