import type { Orbital } from '../types'

const MIN_CHART_HEIGHT = 180
const ROW_PITCH = 28
const CHART_PADDING = 14
const MIN_VERTICAL_GAP = 20

export interface PositionedOrbital {
  orbital: Orbital
  top: number
  lane: number
  laneCount: number
}

export interface EnergyDiagramLayout {
  height: number
  levels: PositionedOrbital[]
}

export function layoutEnergyLevels(orbitals: Orbital[]): EnergyDiagramLayout {
  const height = Math.max(MIN_CHART_HEIGHT, orbitals.length * ROW_PITCH)
  if (!orbitals.length) return { height, levels: [] }

  const sorted = [...orbitals].sort((a, b) => b.energy_hartree - a.energy_hartree)
  const highest = sorted[0].energy_hartree
  const lowest = sorted.at(-1)?.energy_hartree ?? highest
  const energyRange = Math.max(0.0001, highest - lowest)
  const drawableHeight = height - CHART_PADDING * 2
  const points = sorted.map(orbital => ({
    orbital,
    top: CHART_PADDING + (highest - orbital.energy_hartree) / energyRange * drawableHeight,
  }))

  const groups: typeof points[] = []
  for (const point of points) {
    const group = groups.at(-1)
    const previous = group?.at(-1)
    if (!group || !previous || point.top - previous.top >= MIN_VERTICAL_GAP) {
      groups.push([point])
    } else {
      group.push(point)
    }
  }

  return {
    height,
    levels: groups.flatMap(group => {
      const lastTopByLane: number[] = []
      const assigned = group.map(point => {
        let lane = lastTopByLane.findIndex(top => point.top - top >= MIN_VERTICAL_GAP)
        if (lane === -1) lane = lastTopByLane.length
        lastTopByLane[lane] = point.top
        return { ...point, lane }
      })
      const laneCount = lastTopByLane.length
      return assigned.map(point => ({ ...point, laneCount }))
    }),
  }
}
