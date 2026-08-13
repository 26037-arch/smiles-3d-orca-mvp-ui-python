import type { Orbital } from '../types'

const HARTREE_TO_EV = 27.211386245988
const MIN_CHART_HEIGHT = 180
const MIN_HEIGHT_PER_ORBITAL = 12
const CHART_PADDING = 14
const MIN_VERTICAL_GAP = 20
const PIXELS_PER_EV = 12
const BREAK_VISUAL_GAP = 24
export const DEFAULT_ENERGY_BREAK_THRESHOLD_EV = 6

export const energyBreakKey = (highEnergyHartree: number, lowEnergyHartree: number) => (
  `${highEnergyHartree}:${lowEnergyHartree}`
)

export interface PositionedOrbital {
  orbital: Orbital
  top: number
  lane: number
  laneCount: number
}

export interface EnergyAxisTick {
  energyHartree: number
  top: number
}

export interface EnergyAxisBreak {
  key: string
  top: number
  gapEv: number
  highEnergyHartree: number
  lowEnergyHartree: number
}

export interface ExpandedEnergyRange {
  key: string
  top: number
  bottom: number
  gapEv: number
}

interface EnergySegment {
  highEnergyHartree: number
  lowEnergyHartree: number
  top: number
  bottom: number
  broken: boolean
}

export interface EnergyDiagramLayout {
  height: number
  levels: PositionedOrbital[]
  ticks: EnergyAxisTick[]
  breaks: EnergyAxisBreak[]
  expandedRanges: ExpandedEnergyRange[]
  segments: EnergySegment[]
}

export interface EnergyDiagramOptions {
  breakThresholdEv?: number
  expandedBreakKeys?: ReadonlySet<string>
}

const niceStep = (rawStep: number) => {
  const magnitude = 10 ** Math.floor(Math.log10(rawStep))
  const normalized = rawStep / magnitude
  const multiplier = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10
  return multiplier * magnitude
}

const isInsideBreak = (energyHartree: number, breaks: EnergyAxisBreak[]) => breaks.some(
  gap => energyHartree < gap.highEnergyHartree && energyHartree > gap.lowEnergyHartree,
)

export function positionForEnergy(layout: EnergyDiagramLayout, energyHartree: number) {
  if (!layout.segments.length) return layout.height / 2
  const first = layout.segments[0]
  const last = layout.segments.at(-1)!
  if (energyHartree >= first.highEnergyHartree) return first.top
  if (energyHartree <= last.lowEnergyHartree) return last.bottom
  const segment = layout.segments.find(item => (
    energyHartree <= item.highEnergyHartree && energyHartree >= item.lowEnergyHartree
  )) ?? last
  const ratio = (segment.highEnergyHartree - energyHartree)
    / Math.max(Number.EPSILON, segment.highEnergyHartree - segment.lowEnergyHartree)
  return segment.top + ratio * (segment.bottom - segment.top)
}

export function energyAtPosition(layout: EnergyDiagramLayout, top: number) {
  if (!layout.segments.length) return layout.levels[0]?.orbital.energy_hartree ?? 0
  const first = layout.segments[0]
  const last = layout.segments.at(-1)!
  if (top <= first.top) return first.highEnergyHartree
  if (top >= last.bottom) return last.lowEnergyHartree
  const segment = layout.segments.find(item => top >= item.top && top <= item.bottom) ?? last
  const ratio = (top - segment.top) / Math.max(Number.EPSILON, segment.bottom - segment.top)
  return segment.highEnergyHartree
    - ratio * (segment.highEnergyHartree - segment.lowEnergyHartree)
}

export function layoutEnergyLevels(
  orbitals: Orbital[],
  zoom = 1,
  options: EnergyDiagramOptions = {},
): EnergyDiagramLayout {
  const safeZoom = Math.max(1, zoom)
  const breakThresholdEv = Math.max(
    0.1,
    options.breakThresholdEv ?? DEFAULT_ENERGY_BREAK_THRESHOLD_EV,
  )
  const expandedBreakKeys = options.expandedBreakKeys ?? new Set<string>()
  if (!orbitals.length) {
    return {
      height: MIN_CHART_HEIGHT,
      levels: [],
      ticks: [],
      breaks: [],
      expandedRanges: [],
      segments: [],
    }
  }

  const sorted = [...orbitals].sort((a, b) => b.energy_hartree - a.energy_hartree)
  const rawPoints = [{ orbital: sorted[0], top: CHART_PADDING }]
  const rawSegments: EnergySegment[] = []
  const rawBreaks: EnergyAxisBreak[] = []
  const rawExpandedRanges: ExpandedEnergyRange[] = []
  let cursor = CHART_PADDING

  for (let index = 1; index < sorted.length; index += 1) {
    const previous = sorted[index - 1]
    const orbital = sorted[index]
    const gapEv = (previous.energy_hartree - orbital.energy_hartree) * HARTREE_TO_EV
    const key = energyBreakKey(previous.energy_hartree, orbital.energy_hartree)
    const breakEligible = gapEv > breakThresholdEv
    const broken = breakEligible && !expandedBreakKeys.has(key)
    const visualGap = broken ? BREAK_VISUAL_GAP : gapEv * PIXELS_PER_EV * safeZoom
    const next = cursor + Math.max(0, visualGap)
    rawSegments.push({
      highEnergyHartree: previous.energy_hartree,
      lowEnergyHartree: orbital.energy_hartree,
      top: cursor,
      bottom: next,
      broken,
    })
    if (broken) {
      rawBreaks.push({
        key,
        top: cursor + visualGap / 2,
        gapEv,
        highEnergyHartree: previous.energy_hartree,
        lowEnergyHartree: orbital.energy_hartree,
      })
    } else if (breakEligible) {
      rawExpandedRanges.push({ key, top: cursor, bottom: next, gapEv })
    }
    cursor = next
    rawPoints.push({ orbital, top: cursor })
  }

  const naturalHeight = cursor + CHART_PADDING
  const height = Math.max(MIN_CHART_HEIGHT, sorted.length * MIN_HEIGHT_PER_ORBITAL, naturalHeight)
  const offset = (height - naturalHeight) / 2
  const points = rawPoints.map(point => ({ ...point, top: point.top + offset }))
  const segments = rawSegments.map(segment => ({
    ...segment,
    top: segment.top + offset,
    bottom: segment.bottom + offset,
  }))
  const breaks = rawBreaks.map(gap => ({ ...gap, top: gap.top + offset }))
  const expandedRanges = rawExpandedRanges.map(range => ({
    ...range,
    top: range.top + offset,
    bottom: range.bottom + offset,
  }))

  const highestEv = sorted[0].energy_hartree * HARTREE_TO_EV
  const lowestEv = sorted.at(-1)!.energy_hartree * HARTREE_TO_EV
  const tickStepEv = niceStep(44 / (PIXELS_PER_EV * safeZoom))
  const ticks: EnergyAxisTick[] = []
  for (
    let energyEv = Math.ceil(lowestEv / tickStepEv) * tickStepEv;
    energyEv <= highestEv + tickStepEv * 0.001;
    energyEv += tickStepEv
  ) {
    const energyHartree = energyEv / HARTREE_TO_EV
    if (!isInsideBreak(energyHartree, breaks)) {
      ticks.push({ energyHartree, top: positionForEnergy({
        height, levels: [], ticks: [], breaks, expandedRanges, segments,
      }, energyHartree) })
    }
  }

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
    ticks,
    breaks,
    expandedRanges,
    segments,
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
