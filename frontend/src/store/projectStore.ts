import { create } from 'zustand'
import { inferBonds } from '../chem/bonds'
import { changeAngle, changeDistance, threeAtomPlane } from '../chem/geometry'
import type { Atom, Bond, CalculationResult, MoleculeProject, SketchPlane, SurfaceLayer, Tool, Vec3 } from '../types'

const plane = (kind: 'XY' | 'YZ' | 'ZX', origin: Vec3, normal: Vec3, basisU: Vec3, basisV: Vec3): SketchPlane => ({
  id: crypto.randomUUID(), kind, atomIds: [], origin, normal, basisU, basisV, visible: kind === 'XY', active: kind === 'XY', valid: true,
})

export const newProject = (): MoleculeProject => ({
  schemaVersion: 1,
  name: '새 분자',
  atoms: [], bonds: [],
  sketchPlanes: [
    plane('XY', [0, 0, 0], [0, 0, 1], [1, 0, 0], [0, 1, 0]),
    plane('YZ', [0, 0, 0], [1, 0, 0], [0, 1, 0], [0, 0, 1]),
    plane('ZX', [0, 0, 0], [0, 1, 0], [0, 0, 1], [1, 0, 0]),
  ],
  manualBondExclusions: [], totalCharge: 0, multiplicity: 1, calculationPreset: 'preview',
  displaySettings: { perspective: true, showGrid: true, showAxes: true, atomScale: 1, bondScale: 1 },
})

interface History { past: MoleculeProject[]; future: MoleculeProject[] }
export interface ProjectStore {
  project: MoleculeProject
  optimizedProject?: MoleculeProject
  viewStructure: 'initial' | 'optimized'
  selection: string[]
  tool: Tool
  addElement: string
  toolAtoms: string[]
  history: History
  notice?: string
  error?: string
  result?: CalculationResult
  surfaces: SurfaceLayer[]
  selectedOrbital?: string
  orbitEnabled: boolean
  setTool(tool: Tool): void
  setAddElement(element: string): void
  selectAtom(id: string, additive?: boolean): void
  clearSelection(): void
  addAtom(element: string, position: Vec3): void
  deleteSelected(): void
  moveAtoms(ids: string[], delta: Vec3): void
  updateAtom(id: string, patch: Partial<Pick<Atom, 'element' | 'position' | 'label'>>): void
  updateVisibleAtom(id: string, patch: Partial<Pick<Atom, 'element' | 'position' | 'label'>>): void
  addBond(a: string, b: string, order?: 1 | 2 | 3): void
  deleteBond(id: string): void
  updateBondOrder(id: string, order: 1 | 2 | 3): void
  reinferBonds(): void
  createThreeAtomPlane(atomIds: string[]): void
  setActivePlane(id: string): void
  togglePlane(id: string): void
  applyDistance(ids: [string, string], target: number): void
  applyAngle(ids: [string, string, string], target: number, camera?: Vec3): void
  setProject(project: MoleculeProject): void
  updateProject(patch: Partial<MoleculeProject>): void
  undo(): void
  redo(): void
  applyResult(result: CalculationResult): void
  setViewStructure(value: 'initial' | 'optimized'): void
  setResult(result?: CalculationResult): void
  upsertSurface(layer: SurfaceLayer): void
  removeSurface(key: string): void
  setSelectedOrbital(id?: string): void
  setNotice(value?: string): void
  setError(value?: string): void
  setOrbitEnabled(value: boolean): void
}

function refreshPlanes(project: MoleculeProject): MoleculeProject {
  return {
    ...project,
    sketchPlanes: project.sketchPlanes.map(p => {
      if (p.kind !== 'THREE_ATOMS') return p
      const atoms = p.atomIds.map(id => project.atoms.find(a => a.id === id))
      if (atoms.some(a => !a)) return { ...p, valid: false, active: false }
      try { return { ...p, ...threeAtomPlane(atoms[0]!.position, atoms[1]!.position, atoms[2]!.position), valid: true } }
      catch { return { ...p, valid: false, active: false } }
    }),
  }
}

const withCommand = (state: ProjectStore, project: MoleculeProject) => ({
  project: refreshPlanes(project), history: { past: [...state.history.past, state.project].slice(-100), future: [] }, error: undefined,
})

export const useProjectStore = create<ProjectStore>((set, get) => ({
  project: newProject(), viewStructure: 'initial', selection: [], tool: 'select', addElement: 'C', toolAtoms: [],
  history: { past: [], future: [] }, surfaces: [], orbitEnabled: true,
  setTool: tool => set({ tool, toolAtoms: [], error: undefined }),
  setAddElement: addElement => set({ addElement }),
  selectAtom: (id, additive = false) => {
    const state = get(); const selected = additive ? (state.selection.includes(id) ? state.selection.filter(x => x !== id) : [...state.selection, id]) : [id]
    const needed = state.tool === 'distance' ? 2 : state.tool === 'angle' || state.tool === 'plane' ? 3 : state.tool.startsWith('bond') ? 2 : 0
    const toolAtoms = needed ? [...state.toolAtoms.filter(x => x !== id), id].slice(-needed) : state.toolAtoms
    set({ selection: selected, toolAtoms })
    if (state.tool === 'bond-add' && toolAtoms.length === 2) { get().addBond(toolAtoms[0], toolAtoms[1]); set({ toolAtoms: [] }) }
    if (state.tool === 'bond-delete' && toolAtoms.length === 2) {
      const bond = get().project.bonds.find(b => new Set([b.atomId1, b.atomId2]).size === new Set(toolAtoms).size && toolAtoms.includes(b.atomId1) && toolAtoms.includes(b.atomId2))
      if (bond) get().deleteBond(bond.id); else set({ error: '선택한 원자 사이에 결합이 없습니다' }); set({ toolAtoms: [] })
    }
  },
  clearSelection: () => set({ selection: [], toolAtoms: [] }),
  addAtom: (element, position) => {
    if (position.some(x => !Number.isFinite(x))) return set({ error: '좌표는 유한한 숫자여야 합니다' })
    if (get().project.atoms.some(a => Math.hypot(...a.position.map((x, i) => x - position[i])) < .1)) return set({ error: '기존 원자와 0.1 Å 미만으로 겹칩니다' })
    const atom: Atom = { id: crypto.randomUUID(), element, position }
    const project = get().project; const atoms = [...project.atoms, atom]
    set(state => ({ ...withCommand(state, { ...project, atoms, bonds: inferBonds(atoms, project.bonds, project.manualBondExclusions) }), selection: [atom.id] }))
  },
  deleteSelected: () => {
    const state = get(); const deleting = new Set(state.selection)
    const project = { ...state.project, atoms: state.project.atoms.filter(a => !deleting.has(a.id)), bonds: state.project.bonds.filter(b => !deleting.has(b.atomId1) && !deleting.has(b.atomId2)), sketchPlanes: state.project.sketchPlanes.filter(p => !p.atomIds.some(id => deleting.has(id))) }
    set({ ...withCommand(state, project), selection: [] })
  },
  moveAtoms: (ids, delta) => {
    const state = get(); const moving = new Set(ids)
    set(withCommand(state, { ...state.project, atoms: state.project.atoms.map(a => moving.has(a.id) ? { ...a, position: a.position.map((x, i) => x + delta[i]) as Vec3 } : a) }))
  },
  updateAtom: (id, patch) => {
    const state = get(); set(withCommand(state, { ...state.project, atoms: state.project.atoms.map(a => a.id === id ? { ...a, ...patch } : a) }))
  },
  updateVisibleAtom: (id, patch) => {
    const state = get()
    if (state.viewStructure === 'optimized' && state.optimizedProject) {
      set({ optimizedProject: refreshPlanes({
        ...state.optimizedProject,
        // Exact coordinate editing intentionally changes only the selected atom.
        atoms: state.optimizedProject.atoms.map(atom => atom.id === id ? { ...atom, ...patch } : atom),
      }) })
      return
    }
    set(withCommand(state, {
      ...state.project,
      // Do not propagate coordinate-panel edits across bonds or rerun inference.
      atoms: state.project.atoms.map(atom => atom.id === id ? { ...atom, ...patch } : atom),
    }))
  },
  addBond: (a, b, order = 1) => {
    const state = get(); if (a === b) return set({ error: '서로 다른 두 원자가 필요합니다' })
    if (state.project.bonds.some(x => new Set([x.atomId1, x.atomId2]).has(a) && new Set([x.atomId1, x.atomId2]).has(b))) return set({ error: '이미 결합이 있습니다' })
    const bond: Bond = { id: crypto.randomUUID(), atomId1: a, atomId2: b, order, source: 'manual' }
    const exclusions = state.project.manualBondExclusions.filter(([x, y]) => !(new Set([x, y]).has(a) && new Set([x, y]).has(b)))
    set(withCommand(state, { ...state.project, bonds: [...state.project.bonds, bond], manualBondExclusions: exclusions }))
  },
  deleteBond: id => {
    const state = get(); const removed = state.project.bonds.find(b => b.id === id); if (!removed) return
    set(withCommand(state, { ...state.project, bonds: state.project.bonds.filter(b => b.id !== id), manualBondExclusions: [...state.project.manualBondExclusions, [removed.atomId1, removed.atomId2]] }))
  },
  updateBondOrder: (id, order) => { const state = get(); set(withCommand(state, { ...state.project, bonds: state.project.bonds.map(b => b.id === id ? { ...b, order, source: 'manual' } : b) })) },
  reinferBonds: () => { const state = get(); set(withCommand(state, { ...state.project, bonds: inferBonds(state.project.atoms, state.project.bonds, state.project.manualBondExclusions) })) },
  createThreeAtomPlane: atomIds => {
    const state = get(); if (new Set(atomIds).size !== 3) return set({ error: '서로 다른 원자 세 개를 순서대로 선택하세요' })
    const atoms = atomIds.map(id => state.project.atoms.find(a => a.id === id)); if (atoms.some(a => !a)) return set({ error: '원자를 찾을 수 없습니다' })
    try {
      const geometry = threeAtomPlane(atoms[0]!.position, atoms[1]!.position, atoms[2]!.position)
      const p: SketchPlane = { id: crypto.randomUUID(), kind: 'THREE_ATOMS', atomIds, ...geometry, visible: true, active: true, valid: true }
      set(withCommand(state, { ...state.project, sketchPlanes: [...state.project.sketchPlanes.map(x => ({ ...x, active: false })), p] }))
    } catch (error) { set({ error: (error as Error).message }) }
  },
  setActivePlane: id => { const state = get(); set(withCommand(state, { ...state.project, sketchPlanes: state.project.sketchPlanes.map(p => ({ ...p, active: p.id === id && p.valid })) })) },
  togglePlane: id => { const state = get(); set(withCommand(state, { ...state.project, sketchPlanes: state.project.sketchPlanes.map(p => p.id === id ? { ...p, visible: !p.visible } : p) })) },
  applyDistance: (ids, target) => { const state = get(); try { set(withCommand(state, { ...state.project, atoms: changeDistance(state.project.atoms, state.project.bonds, ...ids, target) })) } catch (e) { set({ error: (e as Error).message }) } },
  applyAngle: (ids, target, camera) => { const state = get(); try { set(withCommand(state, { ...state.project, atoms: changeAngle(state.project.atoms, state.project.bonds, ...ids, target, camera) })) } catch (e) { set({ error: (e as Error).message }) } },
  setProject: project => set({ project: refreshPlanes(project), optimizedProject: undefined, viewStructure: 'initial', selection: [], history: { past: [], future: [] }, result: undefined, surfaces: [], error: undefined }),
  updateProject: patch => { const state = get(); set(withCommand(state, { ...state.project, ...patch })) },
  undo: () => { const state = get(); const previous = state.history.past.at(-1); if (previous) set({ project: previous, history: { past: state.history.past.slice(0, -1), future: [state.project, ...state.history.future] }, selection: [] }) },
  redo: () => { const state = get(); const next = state.history.future[0]; if (next) set({ project: next, history: { past: [...state.history.past, state.project], future: state.history.future.slice(1) }, selection: [] }) },
  applyResult: result => { const state = get(); set({ result, optimizedProject: { ...state.project, atoms: result.optimized_atoms, lastCalculationId: result.job_id }, viewStructure: 'optimized', surfaces: [] }) },
  setViewStructure: viewStructure => set({ viewStructure }), setResult: result => set({ result }),
  upsertSurface: layer => set(state => ({ surfaces: [...state.surfaces.filter(x => x.key !== layer.key), layer] })),
  removeSurface: key => set(state => ({ surfaces: state.surfaces.filter(x => x.key !== key) })),
  setSelectedOrbital: selectedOrbital => set({ selectedOrbital }), setNotice: notice => set({ notice }), setError: error => set({ error }), setOrbitEnabled: orbitEnabled => set({ orbitEnabled }),
}))

export const visibleProject = (state: ProjectStore) => state.viewStructure === 'optimized' && state.optimizedProject ? state.optimizedProject : state.project
