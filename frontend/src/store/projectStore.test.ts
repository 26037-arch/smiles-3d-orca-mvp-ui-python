import { beforeEach, describe, expect, it } from 'vitest'
import { newProject, useProjectStore } from './projectStore'
import { angleDegrees, distance } from '../chem/geometry'
import type { MoleculeProject } from '../types'

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
