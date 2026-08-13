import { ELEMENTS } from './elements'
import { distance } from './geometry'
import type { Atom, Bond } from '../types'

export const BOND_INFERENCE = { tolerance: 1.22, minimumDistance: 0.35 }
const pairKey = (a: string, b: string) => [a, b].sort().join(':')

export function inferBonds(atoms: Atom[], existing: Bond[] = [], exclusions: [string, string][] = []): Bond[] {
  const manual = existing.filter(b => b.source === 'manual')
  const occupied = new Set(manual.map(b => pairKey(b.atomId1, b.atomId2)))
  const excluded = new Set(exclusions.map(([a, b]) => pairKey(a, b)))
  const inferred: Bond[] = []
  for (let i = 0; i < atoms.length; i++) for (let j = i + 1; j < atoms.length; j++) {
    const a = atoms[i]; const b = atoms[j]; const key = pairKey(a.id, b.id)
    const d = distance(a.position, b.position)
    if (!occupied.has(key) && !excluded.has(key) && d >= BOND_INFERENCE.minimumDistance && d <= (ELEMENTS[a.element].radius + ELEMENTS[b.element].radius) * BOND_INFERENCE.tolerance) {
      inferred.push({ id: crypto.randomUUID(), atomId1: a.id, atomId2: b.id, order: 1, source: 'inferred' })
      occupied.add(key)
    }
  }
  return [...manual, ...inferred]
}

