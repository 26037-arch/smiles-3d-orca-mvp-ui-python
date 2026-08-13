import type { BasisContribution, Orbital, SurfaceLayer } from '../types'

export const AO_REFERENCE_OPACITY = 0.22
export const AO_PAGE_SIZE = 5
export const AO_COMPONENT_ISOVALUE = 0.03

export const basisSurfaceKey = (orbital: Orbital, basisIndex: number) => (
  `ao:${orbital.spin}:${orbital.orca_index}:${basisIndex}`
)

export const createBasisSurfaceLayer = (
  orbital: Orbital,
  item: BasisContribution,
  visible = true,
): SurfaceLayer => ({
  key: basisSurfaceKey(orbital, item.basis_index),
  name: `${item.atom_label} ${item.shell_label} · Cμ φμ`,
  field: 'ao_component',
  orbitalIndex: orbital.orca_index,
  orbitalInternalId: orbital.internal_id,
  basisIndex: item.basis_index,
  spin: orbital.spin,
  visible,
  opacity: 0.68,
  isovalue: AO_COMPONENT_ISOVALUE,
  positiveColor: '#3d80ff',
  negativeColor: '#ff4f87',
  meshUrls: {},
})

export const appendCompositionItems = (
  current: BasisContribution[],
  incoming: BasisContribution[],
) => {
  const seen = new Set(current.map(item => item.basis_index))
  return [...current, ...incoming.filter(item => !seen.has(item.basis_index))]
}

export const initialBasisSelection = (items: BasisContribution[]) => new Set(
  items.slice(0, AO_PAGE_SIZE).map(item => item.basis_index),
)

export const isCurrentAORequest = (
  currentGeneration: number,
  requestGeneration: number,
  aborted: boolean,
) => currentGeneration === requestGeneration && !aborted
