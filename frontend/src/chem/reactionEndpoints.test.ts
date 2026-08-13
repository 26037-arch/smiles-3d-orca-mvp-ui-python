import { describe, expect, it } from 'vitest'
import { newProject } from '../store/projectStore'
import { overlayEndpointProject, productProjectFromXyz, validateReactionEndpoints } from './reactionEndpoints'
import type { MoleculeProject } from '../types'

const endpoints = (): [MoleculeProject, MoleculeProject] => {
  const reactant = newProject()
  reactant.name = 'reactant'
  reactant.atoms = [
    { id: 'o', element: 'O', position: [0, 0, 0] },
    { id: 'h1', element: 'H', position: [.96, 0, 0] },
    { id: 'h2', element: 'H', position: [-.24, .93, 0] },
  ]
  const product = structuredClone(reactant)
  product.name = 'product'
  product.atoms[2].position = [-.24, 1.2, 0]
  return [reactant, product]
}

describe('reaction endpoint input', () => {
  it('accepts matching atom order without mutating the reactant', () => {
    const [reactant, product] = endpoints()
    const snapshot = structuredClone(reactant)
    expect(validateReactionEndpoints(reactant, product)).toBeUndefined()
    const imported = productProjectFromXyz(
      reactant,
      '3\nproduct\nO 0 0 0\nH .96 0 0\nH -.24 1.2 0\n',
      'product',
    )
    expect(imported.atoms[2].position[1]).toBe(1.2)
    expect(reactant).toEqual(snapshot)
  })

  it('reports count, ordered-element, charge, and identical-coordinate mismatches', () => {
    const [reactant, product] = endpoints()
    expect(validateReactionEndpoints(reactant, { ...product, atoms: product.atoms.slice(1) })).toContain('원자')
    const wrongOrder = structuredClone(product)
    wrongOrder.atoms[0].element = 'H'; wrongOrder.atoms[1].element = 'O'
    expect(validateReactionEndpoints(reactant, wrongOrder)).toContain('순서')
    expect(validateReactionEndpoints(reactant, { ...product, totalCharge: 1 })).toContain('전하')
    expect(validateReactionEndpoints(reactant, structuredClone(reactant))).toContain('동일')
  })

  it('builds a read-only overlay without changing either endpoint', () => {
    const [reactant, product] = endpoints()
    const overlay = overlayEndpointProject(reactant, product)
    expect(overlay.atoms).toHaveLength(6)
    expect(overlay.atoms.slice(3).every(atom => atom.id.startsWith('product-preview-'))).toBe(true)
    expect(reactant.atoms).toHaveLength(3)
    expect(product.atoms).toHaveLength(3)
  })

  it('rejects multi-frame XYZ product input', () => {
    const [reactant] = endpoints()
    const text = '1\na\nH 0 0 0\n1\nb\nH 1 0 0\n'
    expect(() => productProjectFromXyz(reactant, text, 'multi')).toThrow(/단일 구조/)
  })
})
