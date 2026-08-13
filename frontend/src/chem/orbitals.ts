import type { Orbital, SurfaceLayer } from '../types'

export const MAX_VISIBLE_SURFACES = 6

export const orcaIndexToDisplayNumber = (orcaIndex: number) => {
  if (!Number.isInteger(orcaIndex) || orcaIndex < 0) throw new Error('ORCA orbital index는 0 이상의 정수여야 합니다')
  return orcaIndex + 1
}

export const displayNumberToOrcaIndex = (displayNumber: number) => {
  if (!Number.isInteger(displayNumber) || displayNumber < 1) throw new Error('표시 번호는 1 이상의 정수여야 합니다')
  return displayNumber - 1
}

export const frontierOrbitals = (orbitals: Orbital[], homoInternalId?: string) => {
  const homoIndex = orbitals.find(orbital => orbital.internal_id === homoInternalId)?.orca_index ?? 0
  return orbitals.filter(
    orbital => orbital.label || Math.abs(orbital.orca_index - homoIndex) <= 2,
  )
}

const spinPrefix = (orbital: Orbital) => {
  if (orbital.spin === 'alpha') return 'α '
  if (orbital.spin === 'beta') return 'β '
  return ''
}

export const orbitalOptionLabel = (orbital: Orbital) => [
  `${spinPrefix(orbital)}MO ${orbital.display_number}`,
  orbital.label,
  `${(orbital.energy_hartree * 27.211386245988).toFixed(2)} eV`,
  `occ ${orbital.occupancy.toFixed(1)}`,
].filter(Boolean).join(' · ')

export const orbitalSurfaceKey = (orbital: Orbital) => (
  `mo:${orbital.spin}:${orbital.orca_index}`
)

export const createSurfaceLayer = (orbital?: Orbital): SurfaceLayer => orbital ? {
  key: orbitalSurfaceKey(orbital),
  name: `${spinPrefix(orbital)}${orbital.label ?? `MO ${orbital.display_number}`} · ORCA index ${orbital.orca_index}`,
  field: 'mo',
  orbitalIndex: orbital.orca_index,
  spin: orbital.spin,
  visible: true,
  opacity: 0.55,
  isovalue: 0.03,
  positiveColor: '#3d80ff',
  negativeColor: '#ff4f87',
  meshUrls: {},
} : {
  key: 'total_density',
  name: '전체 전자 밀도',
  field: 'total_density',
  spin: 'restricted',
  visible: true,
  opacity: 0.55,
  isovalue: 0.05,
  positiveColor: '#52c9a8',
  negativeColor: '#ff4f87',
  meshUrls: {},
}

export function toggleSurfaceLayer(layers: SurfaceLayer[], orbital?: Orbital) {
  const candidate = createSurfaceLayer(orbital)
  const existing = layers.find(layer => layer.key === candidate.key)
  if (existing?.visible) return { layer: { ...existing, visible: false } }
  if (layers.filter(layer => layer.visible).length >= MAX_VISIBLE_SURFACES) {
    return { error: `동시에 표시할 수 있는 표면은 최대 ${MAX_VISIBLE_SURFACES}개입니다` }
  }
  return { layer: existing ? { ...existing, visible: true } : candidate }
}

export const surfaceRequestForLayer = (layer: SurfaceLayer) => ({
  field: layer.field,
  orbital_index: layer.orbitalIndex,
  spin: layer.spin,
  isovalue: layer.isovalue,
  opacity: layer.opacity,
  display_mode: 'both' as const,
})
