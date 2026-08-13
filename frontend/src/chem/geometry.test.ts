import { describe, expect, it } from 'vitest'
import { angleDegrees, changeAngle, changeDistance, distance, stableAngleAxis, threeAtomPlane } from './geometry'
import type { Atom, Bond } from '../types'

const atom = (id: string, position: [number, number, number]): Atom => ({ id, element: 'C', position })
const bond = (id: string, a: string, b: string): Bond => ({ id, atomId1: a, atomId2: b, order: 1, source: 'manual' })

describe('distance editing graph rules', () => {
  it('moves the entire later-side component across a bridge', () => {
    const atoms = [atom('a', [0, 0, 0]), atom('b', [1, 0, 0]), atom('c', [2, 0, 0])]
    const changed = changeDistance(atoms, [bond('ab', 'a', 'b'), bond('bc', 'b', 'c')], 'a', 'b', 2)
    expect(changed.find(a => a.id === 'a')!.position).toEqual([0, 0, 0])
    expect(changed.find(a => a.id === 'b')!.position).toEqual([2, 0, 0])
    expect(changed.find(a => a.id === 'c')!.position).toEqual([3, 0, 0])
  })

  it('moves only the later selected atom when the edge belongs to a ring', () => {
    const atoms = [atom('a', [0, 0, 0]), atom('b', [1, 0, 0]), atom('c', [.5, 1, 0])]
    const bonds = [bond('ab', 'a', 'b'), bond('bc', 'b', 'c'), bond('ca', 'c', 'a')]
    const changed = changeDistance(atoms, bonds, 'a', 'b', 2)
    expect(changed.find(a => a.id === 'b')!.position).toEqual([2, 0, 0])
    expect(changed.find(a => a.id === 'c')!.position).toEqual([.5, 1, 0])
  })

  it('rejects a zero direction and nonpositive target', () => {
    expect(() => changeDistance([atom('a', [0, 0, 0]), atom('b', [0, 0, 0])], [], 'a', 'b', 1)).toThrow('방향')
    expect(() => changeDistance([atom('a', [0, 0, 0]), atom('b', [1, 0, 0])], [], 'a', 'b', 0)).toThrow('0보다 큰')
  })
})

describe('angle editing', () => {
  it('calculates and changes an angle while preserving B-C length', () => {
    const atoms = [atom('a', [1, 0, 0]), atom('b', [0, 0, 0]), atom('c', [0, 1, 0]), atom('d', [0, 2, 0])]
    const bonds = [bond('ab', 'a', 'b'), bond('bc', 'b', 'c'), bond('cd', 'c', 'd')]
    const changed = changeAngle(atoms, bonds, 'a', 'b', 'c', 120)
    expect(angleDegrees(changed[0].position, changed[1].position, changed[2].position)).toBeCloseTo(120, 8)
    expect(distance(changed[1].position, changed[2].position)).toBeCloseTo(1, 8)
    expect(distance(changed[2].position, changed[3].position)).toBeCloseTo(1, 8)
  })

  it('uses a deterministic perpendicular fallback for collinear atoms', () => {
    const axis = stableAngleAxis([1, 0, 0], [0, 0, 0], [-1, 0, 0], [0, 0, -1])
    expect(axis).toEqual([0, 0, -1])
    const changed = changeAngle([atom('a', [1, 0, 0]), atom('b', [0, 0, 0]), atom('c', [-1, 0, 0])], [], 'a', 'b', 'c', 90)
    expect(angleDegrees(changed[0].position, changed[1].position, changed[2].position)).toBeCloseTo(90, 8)
  })

  it('rejects a degenerate three-atom plane', () => {
    expect(() => threeAtomPlane([0, 0, 0], [1, 0, 0], [2, 0, 0])).toThrow('일직선')
  })
})

