import { beforeEach, describe, expect, it } from 'vitest'
import { newProject, useProjectStore } from './projectStore'
import { angleDegrees, distance } from '../chem/geometry'
import type { MoleculeProject } from '../types'

const reactionPlayback = () => ({
  path: {
    schemaVersion: 1 as const, sourceType: 'imported' as const, atomCount: 2, elements: ['H', 'H'], charge: 0,
    multiplicity: 1, hasPhysicalTime: false as const, images: [0, 1].map(index => ({
      id: `p${index}`, index, atoms: [], energyHartree: null, relativeEnergyKjMol: null,
      reactionCoordinate: index, orbitalRefs: {}, convergence: 'converged' as const,
    })),
  },
  displayFrames: [0, 1, 2].map((index) => ({
    index, leftImageIndex: index === 2 ? 1 : 0, rightImageIndex: 1,
    interpolationValue: index / 2, coordinates: [[0, 0, 0], [0.7 + index * .1, 0, 0]] as [[number, number, number], [number, number, number]],
    reactionCoordinate: index / 2, relativeEnergyKjMol: index, isCalculated: index !== 1,
  })),
})

beforeEach(() => useProjectStore.getState().setProject(newProject()))

describe('selection and command history', () => {
  it('shows a clicked atom and exact coordinate edits move only that atom', () => {
    const store = useProjectStore.getState(); store.addAtom('C', [0, 0, 0]); store.addAtom('H', [1, 0, 0])
    const [carbon, hydrogen] = useProjectStore.getState().project.atoms
    useProjectStore.getState().selectAtom(hydrogen.id)
    expect(useProjectStore.getState().selection).toEqual([hydrogen.id])
    useProjectStore.getState().updateVisibleAtom(hydrogen.id, { position: [1.5, .25, 0] })
    const after = useProjectStore.getState().project.atoms
    expect(after.find(a => a.id === hydrogen.id)!.position).toEqual([1.5, .25, 0])
    expect(after.find(a => a.id === carbon.id)!.position).toEqual([0, 0, 0])
  })

  it('runs the distance selection state machine and undo/redo', () => {
    const store = useProjectStore.getState(); store.addAtom('H', [0, 0, 0]); store.addAtom('H', [1, 0, 0])
    const ids = useProjectStore.getState().project.atoms.map(a => a.id)
    useProjectStore.getState().setTool('distance'); useProjectStore.getState().selectAtom(ids[0]); useProjectStore.getState().selectAtom(ids[1])
    expect(useProjectStore.getState().toolAtoms).toEqual(ids)
    useProjectStore.getState().applyDistance(ids as [string, string], 1.5)
    expect(distance(...useProjectStore.getState().project.atoms.map(a => a.position) as [[number, number, number], [number, number, number]])).toBeCloseTo(1.5)
    useProjectStore.getState().undo(); expect(distance(useProjectStore.getState().project.atoms[0].position, useProjectStore.getState().project.atoms[1].position)).toBeCloseTo(1)
    useProjectStore.getState().redo(); expect(distance(useProjectStore.getState().project.atoms[0].position, useProjectStore.getState().project.atoms[1].position)).toBeCloseTo(1.5)
  })

  it('preserves manual deletion exclusion during reinference', () => {
    const s = useProjectStore.getState(); s.addAtom('H', [0, 0, 0]); s.addAtom('H', [.7, 0, 0])
    const inferred = useProjectStore.getState().project.bonds[0]; expect(inferred).toBeTruthy()
    useProjectStore.getState().deleteBond(inferred.id); useProjectStore.getState().reinferBonds()
    expect(useProjectStore.getState().project.bonds).toHaveLength(0)
  })
})

describe('core smoke flow', () => {
  it('loads water, edits distance/angle, applies mock result and surface state', () => {
    const p = newProject(); const ids = ['o', 'h1', 'h2']; const water: MoleculeProject = { ...p, name: 'Water', atoms: [
      { id: ids[0], element: 'O', position: [0, 0, 0] }, { id: ids[1], element: 'H', position: [.96, 0, 0] }, { id: ids[2], element: 'H', position: [-.24, .93, 0] },
    ], bonds: [
      { id: 'b1', atomId1: 'o', atomId2: 'h1', order: 1, source: 'manual' }, { id: 'b2', atomId1: 'o', atomId2: 'h2', order: 1, source: 'manual' },
    ] }
    useProjectStore.getState().setProject(water); useProjectStore.getState().applyDistance(['o', 'h1'], 1); useProjectStore.getState().applyAngle(['h1', 'o', 'h2'], 104.5)
    const edited = useProjectStore.getState().project.atoms
    expect(angleDegrees(
      edited.find(a => a.id === 'h1')!.position,
      edited.find(a => a.id === 'o')!.position,
      edited.find(a => a.id === 'h2')!.position,
    )).toBeCloseTo(104.5)
    const result = { job_id: 'job', optimized_atoms: useProjectStore.getState().project.atoms, total_energy_hartree: -76, normal_termination: true, scf_converged: true, geometry_converged: true, local_minimum_notice: '입력 구조에서 찾은 국소 최적화 구조', orbitals: [], demo: true }
    useProjectStore.getState().applyResult(result); expect(useProjectStore.getState().viewStructure).toBe('optimized')
    useProjectStore.getState().upsertSurface({ key: 'density', name: '전체 전자 밀도', field: 'total_density', spin: 'restricted', visible: true, opacity: .5, isovalue: .05, positiveColor: '#fff', negativeColor: '#000', meshUrls: {} })
    expect(useProjectStore.getState().surfaces[0].visible).toBe(true)
  })
})

describe('AO mode surface lifecycle', () => {
  it('keeps only the selected MO as a translucent reference and restores exact state', () => {
    const first = { key: 'mo:restricted:1', name: 'MO 2', field: 'mo' as const, orbitalIndex: 1, orbitalInternalId: 'restricted:1', spin: 'restricted' as const, visible: false, opacity: .37, isovalue: .03, positiveColor: '#00f', negativeColor: '#f00', meshUrls: { positive: '/one' } }
    const selected = { key: 'mo:restricted:2', name: 'MO 3', field: 'mo' as const, orbitalIndex: 2, orbitalInternalId: 'restricted:2', spin: 'restricted' as const, visible: true, opacity: .81, isovalue: .03, positiveColor: '#00f', negativeColor: '#f00', meshUrls: { positive: '/two' } }
    const density = { key: 'total_density', name: 'density', field: 'total_density' as const, spin: 'restricted' as const, visible: false, opacity: .44, isovalue: .05, positiveColor: '#0f0', negativeColor: '#f00', meshUrls: {} }
    useProjectStore.setState({ surfaces: [first, selected, density] })

    useProjectStore.getState().enterAOMode(selected)
    const during = useProjectStore.getState().surfaces
    expect(during.find(layer => layer.key === first.key)?.visible).toBe(false)
    expect(during.find(layer => layer.key === selected.key)).toMatchObject({ visible: true, opacity: .22 })
    expect(during.find(layer => layer.key === density.key)).toMatchObject({ visible: false, opacity: .44 })
    useProjectStore.getState().upsertSurface({ ...selected, key: 'ao:restricted:2:0', field: 'ao_component', basisIndex: 0 })

    useProjectStore.getState().exitAOMode()
    expect(useProjectStore.getState().surfaces).toEqual([first, selected, density])
  })
})

describe('reaction path state', () => {
  it('keeps calculation kind independent from the calculation preset', () => {
    useProjectStore.getState().updateProject({ calculationPreset: 'standard' })
    useProjectStore.getState().setCalculationKind('reaction-path')
    expect(useProjectStore.getState().project.calculationPreset).toBe('standard')
    expect(useProjectStore.getState().calculationKind).toBe('reaction-path')
  })

  it('keeps the product endpoint separate and previews it without overwriting the reactant', () => {
    const reactant = newProject(); reactant.atoms = [
      { id: 'a', element: 'H', position: [0, 0, 0] },
      { id: 'b', element: 'H', position: [.7, 0, 0] },
    ]
    const product = structuredClone(reactant); product.atoms[1].position = [1.1, 0, 0]
    useProjectStore.getState().setProject(reactant)
    useProjectStore.getState().setCalculationKind('reaction-path')
    useProjectStore.getState().setReactionProduct(product)
    expect(useProjectStore.getState().project.atoms[1].position[0]).toBe(.7)
    expect(useProjectStore.getState().reactionProduct?.atoms[1].position[0]).toBe(1.1)
    expect(useProjectStore.getState().reactionEndpointView).toBe('product')
  })

  it('synchronizes slider frames and distinguishes calculated frames', () => {
    const project = newProject(); project.atoms = [
      { id: 'a', element: 'H', position: [0, 0, 0] }, { id: 'b', element: 'H', position: [.7, 0, 0] },
    ]
    useProjectStore.getState().setProject(project)
    useProjectStore.getState().applyReactionPath(reactionPlayback())
    useProjectStore.getState().setReactionFrame(1)
    const state = useProjectStore.getState()
    expect(state.reactionProject?.atoms[1].position[0]).toBeCloseTo(.8)
    expect(state.reactionPath?.displayFrames[1].isCalculated).toBe(false)
  })

  it('blocks path coordinate edits and can copy the current frame to a single structure', () => {
    const project = newProject(); project.name = 'Path'; project.atoms = [
      { id: 'a', element: 'H', position: [0, 0, 0] }, { id: 'b', element: 'H', position: [.7, 0, 0] },
    ]
    useProjectStore.getState().setProject(project)
    useProjectStore.getState().applyReactionPath(reactionPlayback())
    useProjectStore.getState().setReactionFrame(2)
    useProjectStore.getState().updateVisibleAtom('b', { position: [9, 0, 0] })
    expect(useProjectStore.getState().reactionCopyPrompt).toBe(true)
    expect(useProjectStore.getState().reactionProject?.atoms[1].position[0]).toBeCloseTo(.9)
    useProjectStore.getState().copyReactionFrameToSingle()
    expect(useProjectStore.getState().calculationKind).toBe('single')
    expect(useProjectStore.getState().project.atoms[1].position[0]).toBeCloseTo(.9)
  })
})
