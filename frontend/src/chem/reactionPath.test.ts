import { describe, expect, it } from 'vitest'
import { advanceOptimizationPlayback, advancePlaybackFrame, inferReactionBonds, playbackStartFrame, projectForReactionFrame } from './reactionPath'
import type { DisplayFrame, MoleculeProject, ReactionPathPlayback, ReactionPathResult } from '../types'

const base: MoleculeProject = {
  schemaVersion: 1, name: 'H2', atoms: [
    { id: 'a', element: 'H', position: [0, 0, 0] },
    { id: 'b', element: 'H', position: [0.7, 0, 0] },
  ], bonds: [], sketchPlanes: [], manualBondExclusions: [], totalCharge: 0,
  multiplicity: 1, calculationPreset: 'preview',
  displaySettings: { perspective: true, showGrid: true, showAxes: true, atomScale: 1, bondScale: 1 },
}
const path: ReactionPathResult = {
  schemaVersion: 1, sourceType: 'imported', atomCount: 2, elements: ['H', 'H'],
  charge: 0, multiplicity: 1, hasPhysicalTime: false, images: [],
}
const frame = (distance: number, calculated = false): DisplayFrame => ({
  index: 0, leftImageIndex: 0, rightImageIndex: 1, interpolationValue: .5,
  coordinates: [[0, 0, 0], [distance, 0, 0]], reactionCoordinate: .5,
  relativeEnergyKjMol: 2, isCalculated: calculated,
})

describe('reaction path playback helpers', () => {
  it('stops at the last frame and restarts there from zero', () => {
    expect(advancePlaybackFrame(2, 3)).toEqual({ index: 2, playing: false })
    expect(playbackStartFrame(2, 3)).toBe(0)
    expect(advancePlaybackFrame(0, 3)).toEqual({ index: 1, playing: true })
  })

  it('replays SCF iterations before advancing an actual geometry', () => {
    const playback = {
      path: {
        ...path,
        images: [{
          id: 'g0', index: 0, atoms: [], energyHartree: -1, relativeEnergyKjMol: 0,
          reactionCoordinate: 0, orbitalRefs: {}, convergence: 'converged',
          scfIterations: [
            { iteration: 1, energyHartree: -0.9, deltaEnergyHartree: null, rmsDensity: null, maxDensity: null, diisError: null, maxGradient: null },
            { iteration: 2, energyHartree: -1, deltaEnergyHartree: -.1, rmsDensity: null, maxDensity: null, diisError: null, maxGradient: null },
          ],
        }],
      },
      displayFrames: [frame(.7, true), { ...frame(.8), index: 1 }],
    } as ReactionPathPlayback
    expect(advanceOptimizationPlayback(playback, 0, 0)).toEqual({ frameIndex: 0, scfIterationIndex: 1, playing: true })
    expect(advanceOptimizationPlayback(playback, 0, 2)).toEqual({ frameIndex: 1, scfIterationIndex: 0, playing: true })
  })

  it('keeps atom ids while synchronizing display coordinates', () => {
    const displayed = projectForReactionFrame(base, path, frame(1.2))
    expect(displayed.atoms.map(atom => atom.id)).toEqual(['a', 'b'])
    expect(displayed.atoms[1].position).toEqual([1.2, 0, 0])
  })

  it('uses bond hysteresis around the inference threshold', () => {
    const bonded = projectForReactionFrame(base, path, frame(.75))
    expect(bonded.bonds).toHaveLength(1)
    const retained = inferReactionBonds(projectForReactionFrame(base, path, frame(.8)).atoms, bonded.bonds)
    expect(retained).toHaveLength(1)
    const broken = inferReactionBonds(projectForReactionFrame(base, path, frame(1.2)).atoms, retained)
    expect(broken).toHaveLength(0)
  })
})
