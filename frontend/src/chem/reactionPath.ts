import { BOND_INFERENCE } from './bonds'
import { ELEMENTS } from './elements'
import { distance } from './geometry'
import type { Atom, Bond, DisplayFrame, MoleculeProject, ReactionPathPlayback, ReactionPathResult } from '../types'

export const REACTION_PLAYBACK_FRAME_MS = 80
export const BOND_FORM_TOLERANCE = BOND_INFERENCE.tolerance
export const BOND_BREAK_TOLERANCE = 1.34

export function advancePlaybackFrame(index: number, frameCount: number): { index: number; playing: boolean } {
  if (frameCount <= 0 || index >= frameCount - 1) return { index: Math.max(0, frameCount - 1), playing: false }
  return { index: index + 1, playing: true }
}

export function playbackStartFrame(index: number, frameCount: number): number {
  return frameCount > 0 && index >= frameCount - 1 ? 0 : index
}

export function advanceOptimizationPlayback(
  playback: ReactionPathPlayback,
  frameIndex: number,
  scfIterationIndex: number,
): { frameIndex: number; scfIterationIndex: number; playing: boolean } {
  const frame = playback.displayFrames[frameIndex]
  const iterations = frame?.isCalculated
    ? playback.path.images[frame.leftImageIndex]?.scfIterations?.length ?? 0
    : 0
  if (scfIterationIndex < iterations) {
    return { frameIndex, scfIterationIndex: scfIterationIndex + 1, playing: true }
  }
  const next = advancePlaybackFrame(frameIndex, playback.displayFrames.length)
  return { frameIndex: next.index, scfIterationIndex: 0, playing: next.playing }
}

const pairKey = (a: string, b: string) => [a, b].sort().join(':')

export function reactionFrameAtoms(path: ReactionPathResult, frame: DisplayFrame, ids?: string[]): Atom[] {
  return frame.coordinates.map((position, index) => ({
    id: ids?.[index] ?? `reaction-atom-${index}`,
    element: path.elements[index],
    position: [...position],
  }))
}

export function inferReactionBonds(atoms: Atom[], previous: Bond[] = []): Bond[] {
  const prior = new Map(previous.map(bond => [pairKey(bond.atomId1, bond.atomId2), bond]))
  const bonds: Bond[] = []
  for (let left = 0; left < atoms.length; left++) for (let right = left + 1; right < atoms.length; right++) {
    const a = atoms[left]; const b = atoms[right]
    const key = pairKey(a.id, b.id)
    const existing = prior.get(key)
    const threshold = (ELEMENTS[a.element].radius + ELEMENTS[b.element].radius) * (existing ? BOND_BREAK_TOLERANCE : BOND_FORM_TOLERANCE)
    const separation = distance(a.position, b.position)
    if (separation >= BOND_INFERENCE.minimumDistance && separation <= threshold) {
      bonds.push(existing ?? { id: `reaction-bond-${left}-${right}`, atomId1: a.id, atomId2: b.id, order: 1, source: 'inferred' })
    }
  }
  return bonds
}

export function projectForReactionFrame(
  base: MoleculeProject,
  path: ReactionPathResult,
  frame: DisplayFrame,
  previousBonds: Bond[] = [],
): MoleculeProject {
  const compatibleIds = base.atoms.length === path.atomCount && base.atoms.every((atom, index) => atom.element === path.elements[index])
    ? base.atoms.map(atom => atom.id)
    : undefined
  const atoms = reactionFrameAtoms(path, frame, compatibleIds)
  return {
    ...base,
    atoms,
    bonds: inferReactionBonds(atoms, previousBonds),
    sketchPlanes: [],
    manualBondExclusions: [],
  }
}
