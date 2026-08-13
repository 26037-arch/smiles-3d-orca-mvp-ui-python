import { beforeEach, describe, expect, it } from 'vitest'
import { useAnalysisStore } from './analysisStore'

beforeEach(() => useAnalysisStore.getState().reset())

describe('wavefunction plot selection', () => {
  it('switches MO and total density as separate graph modes', () => {
    useAnalysisStore.getState().setFieldMode('total_density')
    expect(useAnalysisStore.getState().fieldMode).toBe('total_density')
    useAnalysisStore.getState().setFieldMode('mo')
    expect(useAnalysisStore.getState().fieldMode).toBe('mo')
  })

  it('limits MO graphs to five and toggles existing selections', () => {
    for (let index = 0; index < 5; index += 1) {
      expect(useAnalysisStore.getState().toggleMo(`restricted:${index}`)).toBe(true)
    }
    expect(useAnalysisStore.getState().toggleMo('restricted:5')).toBe(false)
    expect(useAnalysisStore.getState().toggleMo('restricted:2')).toBe(true)
    expect(useAnalysisStore.getState().selectedMoIds).not.toContain('restricted:2')
  })

  it('adds an energy-diagram MO without removing an existing graph', () => {
    expect(useAnalysisStore.getState().addMo('restricted:2')).toBe(true)
    expect(useAnalysisStore.getState().addMo('restricted:2')).toBe(true)
    expect(useAnalysisStore.getState().selectedMoIds).toEqual(['restricted:2'])
  })

  it('toggles the combined MO plane view', () => {
    useAnalysisStore.getState().setPlaneOverlay(true)
    expect(useAnalysisStore.getState().planeOverlay).toBe(true)
  })
})
