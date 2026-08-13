import { describe, expect, it } from 'vitest'
import type { Orbital } from '../types'
import {
  DEFAULT_ENERGY_BREAK_THRESHOLD_EV,
  energyBreakKey,
  energyAtPosition,
  layoutEnergyLevels,
  positionForEnergy,
} from './energyDiagramLayout'

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
  it('turns similar-energy horizontal lanes into vertical levels when zoomed', () => {
    const orbitals = [
      orbital(0, -0.50),
      orbital(1, -0.49),
      orbital(2, -0.20),
    ]
    const compact = layoutEnergyLevels(orbitals, 1)
    const zoomed = layoutEnergyLevels(orbitals, 8)
    const compactPair = compact.levels.filter(level => level.orbital.orca_index < 2)
    const zoomedPair = zoomed.levels.filter(level => level.orbital.orca_index < 2)

    expect(compactPair.every(level => level.laneCount === 2)).toBe(true)
    expect(zoomedPair.every(level => level.laneCount === 1)).toBe(true)
  })

  it('compresses a large empty energy interval into a wave break', () => {
    const gapEv = DEFAULT_ENERGY_BREAK_THRESHOLD_EV + 10
    const layout = layoutEnergyLevels([
      orbital(0, 0),
      orbital(1, -gapEv / 27.211386245988),
    ])

    expect(layout.breaks).toHaveLength(1)
    expect(layout.breaks[0].gapEv).toBeCloseTo(gapEv)
    expect(layout.levels[1].top - layout.levels[0].top).toBe(24)
  })

  it('uses the user-selected energy threshold for wave breaks', () => {
    const fiveEvInHartree = 5 / 27.211386245988
    const orbitals = [orbital(0, 0), orbital(1, -fiveEvInHartree)]

    expect(layoutEnergyLevels(orbitals, 1, { breakThresholdEv: 6 }).breaks).toHaveLength(0)
    expect(layoutEnergyLevels(orbitals, 1, { breakThresholdEv: 4 }).breaks).toHaveLength(1)
  })

  it('expands a clicked wave and returns a bracket range that can restore it', () => {
    const high = 0
    const low = -10 / 27.211386245988
    const key = energyBreakKey(high, low)
    const layout = layoutEnergyLevels(
      [orbital(0, high), orbital(1, low)],
      1,
      { expandedBreakKeys: new Set([key]) },
    )

    expect(layout.breaks).toHaveLength(0)
    expect(layout.expandedRanges).toHaveLength(1)
    expect(layout.expandedRanges[0].key).toBe(key)
    expect(layout.expandedRanges[0].bottom - layout.expandedRanges[0].top).toBeCloseTo(120)
  })

  it('adds finer map-like scale ticks as zoom increases', () => {
    const orbitals = [orbital(0, 0), orbital(1, -0.18)]

    expect(layoutEnergyLevels(orbitals, 4).ticks.length)
      .toBeGreaterThan(layoutEnergyLevels(orbitals, 1).ticks.length)
  })

  it('round-trips energy and position for cursor-centered zoom anchoring', () => {
    const layout = layoutEnergyLevels([
      orbital(0, 0.1),
      orbital(1, 0.02),
      orbital(2, -0.1),
    ], 3)
    const energy = 0.05

    expect(energyAtPosition(layout, positionForEnergy(layout, energy))).toBeCloseTo(energy)
  })

  it('grows the chart so every orbital can be reached by scrolling', () => {
    const orbitals = Array.from({ length: 20 }, (_, index) => orbital(index, -index * 0.02))

    expect(layoutEnergyLevels(orbitals).height).toBe(240)
  })
})
