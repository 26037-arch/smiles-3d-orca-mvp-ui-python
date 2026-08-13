import { describe, expect, it } from 'vitest'
import type { BasisContribution, Orbital } from '../types'
import {
  appendCompositionItems,
  basisSurfaceKey,
  createBasisSurfaceLayer,
  deselectIncomingBasis,
  initialBasisSelection,
  isCurrentAORequest,
} from './aoComposition'

const orbital: Orbital = {
  internal_id: 'alpha:4',
  orca_index: 4,
  display_number: 5,
  energy_hartree: -0.4,
  occupancy: 1,
  spin: 'alpha',
}

const contribution = (basisIndex: number): BasisContribution => ({
  basis_index: basisIndex,
  atom_index: 0,
  atom_label: 'N1',
  element: 'N',
  ao_label: 'p_z similar',
  shell_label: `p_z shell-${basisIndex + 1}`,
  coefficient: 0.5,
  loewdin_weight: 0.25,
  percentage: 25,
  phase: '+',
})

describe('AO composition presentation helpers', () => {
  it('keeps spin, MO index, and basis index in a stable surface key', () => {
    expect(basisSurfaceKey(orbital, 7)).toBe('ao:alpha:4:7')
    const layer = createBasisSurfaceLayer(orbital, contribution(7))
    expect(layer.field).toBe('ao_component')
    expect(layer.orbitalInternalId).toBe('alpha:4')
    expect(layer.basisIndex).toBe(7)
  })

  it('appends a page without checking or duplicating its rows', () => {
    const initial = Array.from({ length: 5 }, (_, index) => contribution(index))
    const next = [contribution(4), ...Array.from({ length: 5 }, (_, index) => contribution(index + 5))]

    expect(appendCompositionItems(initial, next).map(item => item.basis_index)).toEqual([
      0, 1, 2, 3, 4, 5, 6, 7, 8, 9,
    ])
    expect([...initialBasisSelection(initial)]).toEqual([0, 1, 2, 3, 4])
    expect([...deselectIncomingBasis(new Set([0, 1, 5, 6]), next)]).toEqual([0, 1])
  })

  it('rejects late or aborted request generations', () => {
    expect(isCurrentAORequest(4, 4, false)).toBe(true)
    expect(isCurrentAORequest(5, 4, false)).toBe(false)
    expect(isCurrentAORequest(4, 4, true)).toBe(false)
  })
})
