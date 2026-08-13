import { describe, expect, it } from 'vitest'
import type { Orbital } from '../types'
import { layoutEnergyLevels } from './energyDiagramLayout'

function orbital(index: number, energy: number): Orbital {
  return {
    internal_id: `restricted:${index}`,
    orca_index: index,
    display_number: index + 1,
    energy_hartree: energy,
    occupancy: index < 2 ? 2 : 0,
    spin: 'restricted',
  }
}

describe('layoutEnergyLevels', () => {
  it('places levels with nearly identical energies in horizontal lanes', () => {
    const layout = layoutEnergyLevels([
      orbital(0, -0.5000),
      orbital(1, -0.4999),
      orbital(2, 0.2),
    ])
    const first = layout.levels.find(level => level.orbital.orca_index === 0)
    const second = layout.levels.find(level => level.orbital.orca_index === 1)

    expect(first?.laneCount).toBe(2)
    expect(second?.laneCount).toBe(2)
    expect(first?.lane).not.toBe(second?.lane)
  })

  it('keeps sufficiently separated levels in the full-width lane', () => {
    const layout = layoutEnergyLevels([
      orbital(0, -1),
      orbital(1, 0),
      orbital(2, 1),
    ])

    expect(layout.levels.every(level => level.lane === 0 && level.laneCount === 1)).toBe(true)
  })

  it('grows the chart so every orbital can be reached by scrolling', () => {
    const orbitals = Array.from({ length: 20 }, (_, index) => orbital(index, index / 10))

    expect(layoutEnergyLevels(orbitals).height).toBe(560)
  })
})
