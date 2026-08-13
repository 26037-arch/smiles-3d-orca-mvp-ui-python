import type { Atom, Bond, Vec3 } from '../types'

const EPS = 1e-10
export const add = (a: Vec3, b: Vec3): Vec3 => [a[0] + b[0], a[1] + b[1], a[2] + b[2]]
export const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]]
export const scale = (a: Vec3, s: number): Vec3 => [a[0] * s, a[1] * s, a[2] * s]
export const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
export const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
export const norm = (a: Vec3) => Math.sqrt(dot(a, a))
export const normalize = (a: Vec3): Vec3 => { const n = norm(a); if (n < EPS) throw new Error('0 길이 벡터의 방향은 정의되지 않습니다'); return scale(a, 1 / n) }
export const distance = (a: Vec3, b: Vec3) => norm(sub(a, b))
export const clamp = (x: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, x))

export function angleDegrees(a: Vec3, b: Vec3, c: Vec3): number {
  const ba = normalize(sub(a, b)); const bc = normalize(sub(c, b))
  return Math.acos(clamp(dot(ba, bc), -1, 1)) * 180 / Math.PI
}

export function connectedComponent(atomIds: string[], bonds: Bond[], start: string, removedPair?: [string, string]): Set<string> {
  const adjacency = new Map(atomIds.map(id => [id, [] as string[]]))
  const removed = removedPair && new Set(removedPair)
  for (const bond of bonds) {
    if (removed?.has(bond.atomId1) && removed?.has(bond.atomId2)) continue
    adjacency.get(bond.atomId1)?.push(bond.atomId2)
    adjacency.get(bond.atomId2)?.push(bond.atomId1)
  }
  const seen = new Set<string>(); const queue = [start]
  while (queue.length) { const id = queue.shift()!; if (seen.has(id)) continue; seen.add(id); queue.push(...(adjacency.get(id) ?? [])) }
  return seen
}

export function isDirectBond(bonds: Bond[], a: string, b: string) {
  return bonds.some(bond => (bond.atomId1 === a && bond.atomId2 === b) || (bond.atomId1 === b && bond.atomId2 === a))
}

export function changeDistance(atoms: Atom[], bonds: Bond[], aId: string, bId: string, target: number): Atom[] {
  if (!(target > 0) || !Number.isFinite(target)) throw new Error('길이는 0보다 큰 유한한 값이어야 합니다')
  const a = atoms.find(x => x.id === aId); const b = atoms.find(x => x.id === bId)
  if (!a || !b || a.id === b.id) throw new Error('서로 다른 원자 두 개가 필요합니다')
  const delta = sub(b.position, a.position); const current = norm(delta)
  if (current < EPS) throw new Error('두 원자의 좌표가 같아 방향을 정할 수 없습니다')
  const movement = scale(delta, (target - current) / current)
  let moving = new Set([bId])
  if (isDirectBond(bonds, aId, bId)) {
    const component = connectedComponent(atoms.map(x => x.id), bonds, bId, [aId, bId])
    if (!component.has(aId)) moving = component // bridge; ring keeps only B
  }
  return atoms.map(atom => moving.has(atom.id) ? { ...atom, position: add(atom.position, movement) } : atom)
}

export function stableAngleAxis(a: Vec3, b: Vec3, c: Vec3, cameraDirection: Vec3 = [0, 0, -1]): Vec3 {
  const ba = normalize(sub(a, b)); const bc = normalize(sub(c, b))
  const normal = cross(ba, bc)
  if (norm(normal) > 1e-7) return normalize(normal)
  const candidates: Vec3[] = [[1, 0, 0], [0, 1, 0], [0, 0, 1], cameraDirection]
  const reference = candidates.sort((x, y) => Math.abs(dot(x, bc)) - Math.abs(dot(y, bc)))[0]
  return normalize(cross(bc, reference))
}

export function rotateAroundAxis(point: Vec3, origin: Vec3, axis: Vec3, radians: number): Vec3 {
  const v = sub(point, origin); const u = normalize(axis); const cos = Math.cos(radians); const sin = Math.sin(radians)
  return add(origin, add(add(scale(v, cos), scale(cross(u, v), sin)), scale(u, dot(u, v) * (1 - cos))))
}

export function changeAngle(atoms: Atom[], bonds: Bond[], aId: string, bId: string, cId: string, target: number, cameraDirection: Vec3 = [0, 0, -1]): Atom[] {
  if (!Number.isFinite(target) || target < 0 || target > 180) throw new Error('각도는 0°에서 180° 사이여야 합니다')
  const a = atoms.find(x => x.id === aId); const b = atoms.find(x => x.id === bId); const c = atoms.find(x => x.id === cId)
  if (!a || !b || !c || new Set([aId, bId, cId]).size !== 3) throw new Error('서로 다른 원자 세 개가 필요합니다')
  const current = angleDegrees(a.position, b.position, c.position)
  const axis = stableAngleAxis(a.position, b.position, c.position, cameraDirection)
  // Around BA×BC, positive Rodrigues rotation increases the directed BA→BC angle.
  const radians = (target - current) * Math.PI / 180
  let moving = new Set([cId])
  if (isDirectBond(bonds, bId, cId)) {
    const component = connectedComponent(atoms.map(x => x.id), bonds, cId, [bId, cId])
    if (!component.has(bId)) moving = component
  }
  return atoms.map(atom => moving.has(atom.id) ? { ...atom, position: rotateAroundAxis(atom.position, b.position, axis, radians) } : atom)
}

export function threeAtomPlane(a: Vec3, b: Vec3, c: Vec3) {
  const u = normalize(sub(b, a)); const rawNormal = cross(sub(b, a), sub(c, a))
  if (norm(rawNormal) < 1e-7) throw new Error('세 원자가 일직선이거나 거의 일직선입니다')
  const normal = normalize(rawNormal); const v = normalize(cross(normal, u))
  return { origin: a, normal, basisU: u, basisV: v }
}
