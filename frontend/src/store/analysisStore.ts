import { create } from 'zustand'
import type { PlotFieldMode } from '../types'

interface AnalysisStore {
  mode: 'model' | 'plot'
  cutKind: 'line' | 'plane'
  fieldMode: PlotFieldMode
  selectedMoIds: string[]
  planeOverlay: boolean
  setMode(mode: 'model' | 'plot'): void
  setCutKind(kind: 'line' | 'plane'): void
  setFieldMode(mode: PlotFieldMode): void
  setPlaneOverlay(enabled: boolean): void
  addMo(id: string): boolean
  toggleMo(id: string): boolean
  reset(): void
}

const initial = {
  mode: 'model' as const,
  cutKind: 'line' as const,
  fieldMode: 'mo' as const,
  selectedMoIds: [] as string[],
  planeOverlay: false,
}

export const useAnalysisStore = create<AnalysisStore>((set, get) => ({
  ...initial,
  setMode: mode => set({ mode }),
  setCutKind: cutKind => set({ cutKind }),
  setFieldMode: fieldMode => set({ fieldMode }),
  setPlaneOverlay: planeOverlay => set({ planeOverlay }),
  addMo: id => {
    const current = get().selectedMoIds
    if (current.includes(id)) return true
    if (current.length >= 5) return false
    set({ selectedMoIds: [...current, id] })
    return true
  },
  toggleMo: id => {
    const current = get().selectedMoIds
    if (current.includes(id)) {
      set({ selectedMoIds: current.filter(item => item !== id) })
      return true
    }
    if (current.length >= 5) return false
    set({ selectedMoIds: [...current, id] })
    return true
  },
  reset: () => set(initial),
}))
