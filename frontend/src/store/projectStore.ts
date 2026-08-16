import { create } from 'zustand'
import { inferBonds } from '../chem/bonds'
import { changeAngle, changeDistance, threeAtomPlane } from '../chem/geometry'
import { AO_REFERENCE_OPACITY } from '../chem/aoComposition'
import { projectForReactionFrame } from '../chem/reactionPath'
import type { Atom, Bond, CalculationKind, CalculationResult, MoleculeProject, OrbitalTrackingResult, ReactionPathPlayback, ReactionPathStatus, SketchPlane, SurfaceLayer, Tool, Vec3 } from '../types'

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
  aoMode: boolean
  aoOrbitalId?: string
  aoSurfaceSnapshot?: SurfaceLayer[]
  calculationKind: CalculationKind
  reactionStatus: ReactionPathStatus
  reactionPath?: ReactionPathPlayback
  reactionProject?: MoleculeProject
  reactionFrameIndex: number
  selectedGeometryIndex: number
  reactionScfIterationIndex: number
  reactionError?: string
  reactionCopyPrompt: boolean
  trackingEnabled: boolean
  trackingSourceOrbitalId?: string
  trackingSourceGeometryIndex?: number
  trackingId?: string
  trackingActive?: boolean
  trackingLoading: boolean
  trackingError?: string
  trackingSurfaceError?: string
  trackingResult?: OrbitalTrackingResult
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
  enterAOMode(reference: SurfaceLayer): void
  exitAOMode(): void
  setCalculationKind(kind: CalculationKind): void
  setLastCalculationId(id: string): void
  beginReactionPathLoad(): void
  applyReactionPath(playback: ReactionPathPlayback): void
  failReactionPath(message: string): void
  setReactionFrame(index: number): void
  setReactionScfIteration(index: number): void
  setReactionPlaying(playing: boolean): void
  beginMoTracking(): void
  completeMoTracking(result: OrbitalTrackingResult): void
  failMoTrackingSetup(message: string): void
  failMoTrackingSurface(message: string): void
  failMoTracking(message: string): void
  stopMoTracking(): void
  copyReactionFrameToSingle(): void
  dismissReactionCopyPrompt(): void
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

const structureTools = new Set<Tool>(['add', 'move', 'plane', 'bond-add', 'bond-delete'])

function blockReactionEdit(state: ProjectStore, set: (patch: Partial<ProjectStore>) => void): boolean {
  if (state.calculationKind !== 'reaction-path') return false
  if (state.reactionPath) {
    set({ reactionStatus: 'paused', reactionCopyPrompt: true })
    return true
  }
  return false
}

export const useProjectStore = create<ProjectStore>((set, get) => ({
  project: newProject(), viewStructure: 'initial', selection: [], tool: 'select', addElement: 'C', toolAtoms: [],
  history: { past: [], future: [] }, surfaces: [], orbitEnabled: true, aoMode: false,
  calculationKind: 'single', reactionStatus: 'idle', reactionFrameIndex: 0,
  selectedGeometryIndex: 0, reactionScfIterationIndex: 0, reactionCopyPrompt: false,
  trackingEnabled: false, trackingLoading: false, trackingSurfaceError: undefined, trackingResult: undefined,
  setTool: tool => {
    const state = get()
    if (state.reactionStatus === 'playing' && structureTools.has(tool)) {
      set({ notice: '재생 중에는 구조 편집이 잠깁니다. 일시정지한 뒤 편집하세요.' })
      return
    }
    set({ tool, toolAtoms: [], error: undefined })
  },
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
    if (blockReactionEdit(get(), set)) return
    if (position.some(x => !Number.isFinite(x))) return set({ error: '좌표는 유한한 숫자여야 합니다' })
    if (get().project.atoms.some(a => Math.hypot(...a.position.map((x, i) => x - position[i])) < .1)) return set({ error: '기존 원자와 0.1 Å 미만으로 겹칩니다' })
    const atom: Atom = { id: crypto.randomUUID(), element, position }
    const project = get().project; const atoms = [...project.atoms, atom]
    set(state => ({ ...withCommand(state, { ...project, atoms, bonds: inferBonds(atoms, project.bonds, project.manualBondExclusions) }), selection: [atom.id] }))
  },
  deleteSelected: () => {
    const state = get(); const deleting = new Set(state.selection)
    if (blockReactionEdit(state, set)) return
    const project = { ...state.project, atoms: state.project.atoms.filter(a => !deleting.has(a.id)), bonds: state.project.bonds.filter(b => !deleting.has(b.atomId1) && !deleting.has(b.atomId2)), sketchPlanes: state.project.sketchPlanes.filter(p => !p.atomIds.some(id => deleting.has(id))) }
    set({ ...withCommand(state, project), selection: [] })
  },
  moveAtoms: (ids, delta) => {
    const state = get(); const moving = new Set(ids)
    if (blockReactionEdit(state, set)) return
    set(withCommand(state, { ...state.project, atoms: state.project.atoms.map(a => moving.has(a.id) ? { ...a, position: a.position.map((x, i) => x + delta[i]) as Vec3 } : a) }))
  },
  updateAtom: (id, patch) => {
    const state = get(); if (blockReactionEdit(state, set)) return
    set(withCommand(state, { ...state.project, atoms: state.project.atoms.map(a => a.id === id ? { ...a, ...patch } : a) }))
  },
  updateVisibleAtom: (id, patch) => {
    const state = get()
    if (blockReactionEdit(state, set)) return
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
    const state = get(); if (blockReactionEdit(state, set)) return; if (a === b) return set({ error: '서로 다른 두 원자가 필요합니다' })
    if (state.project.bonds.some(x => new Set([x.atomId1, x.atomId2]).has(a) && new Set([x.atomId1, x.atomId2]).has(b))) return set({ error: '이미 결합이 있습니다' })
    const bond: Bond = { id: crypto.randomUUID(), atomId1: a, atomId2: b, order, source: 'manual' }
    const exclusions = state.project.manualBondExclusions.filter(([x, y]) => !(new Set([x, y]).has(a) && new Set([x, y]).has(b)))
    set(withCommand(state, { ...state.project, bonds: [...state.project.bonds, bond], manualBondExclusions: exclusions }))
  },
  deleteBond: id => {
    const state = get(); const removed = state.project.bonds.find(b => b.id === id); if (!removed) return
    if (blockReactionEdit(state, set)) return
    set(withCommand(state, { ...state.project, bonds: state.project.bonds.filter(b => b.id !== id), manualBondExclusions: [...state.project.manualBondExclusions, [removed.atomId1, removed.atomId2]] }))
  },
  updateBondOrder: (id, order) => { const state = get(); if (blockReactionEdit(state, set)) return; set(withCommand(state, { ...state.project, bonds: state.project.bonds.map(b => b.id === id ? { ...b, order, source: 'manual' } : b) })) },
  reinferBonds: () => { const state = get(); if (blockReactionEdit(state, set)) return; set(withCommand(state, { ...state.project, bonds: inferBonds(state.project.atoms, state.project.bonds, state.project.manualBondExclusions) })) },
  createThreeAtomPlane: atomIds => {
    const state = get(); if (new Set(atomIds).size !== 3) return set({ error: '서로 다른 원자 세 개를 순서대로 선택하세요' })
    if (blockReactionEdit(state, set)) return
    const atoms = atomIds.map(id => state.project.atoms.find(a => a.id === id)); if (atoms.some(a => !a)) return set({ error: '원자를 찾을 수 없습니다' })
    try {
      const geometry = threeAtomPlane(atoms[0]!.position, atoms[1]!.position, atoms[2]!.position)
      const p: SketchPlane = { id: crypto.randomUUID(), kind: 'THREE_ATOMS', atomIds, ...geometry, visible: true, active: true, valid: true }
      set(withCommand(state, { ...state.project, sketchPlanes: [...state.project.sketchPlanes.map(x => ({ ...x, active: false })), p] }))
    } catch (error) { set({ error: (error as Error).message }) }
  },
  setActivePlane: id => { const state = get(); if (blockReactionEdit(state, set)) return; set(withCommand(state, { ...state.project, sketchPlanes: state.project.sketchPlanes.map(p => ({ ...p, active: p.id === id && p.valid })) })) },
  togglePlane: id => { const state = get(); if (blockReactionEdit(state, set)) return; set(withCommand(state, { ...state.project, sketchPlanes: state.project.sketchPlanes.map(p => p.id === id ? { ...p, visible: !p.visible } : p) })) },
  applyDistance: (ids, target) => { const state = get(); if (blockReactionEdit(state, set)) return; try { set(withCommand(state, { ...state.project, atoms: changeDistance(state.project.atoms, state.project.bonds, ...ids, target) })) } catch (e) { set({ error: (e as Error).message }) } },
  applyAngle: (ids, target, camera) => { const state = get(); if (blockReactionEdit(state, set)) return; try { set(withCommand(state, { ...state.project, atoms: changeAngle(state.project.atoms, state.project.bonds, ...ids, target, camera) })) } catch (e) { set({ error: (e as Error).message }) } },
  setProject: project => set({ project: refreshPlanes(project), optimizedProject: undefined, viewStructure: 'initial', selection: [], history: { past: [], future: [] }, result: undefined, surfaces: [], aoMode: false, aoOrbitalId: undefined, aoSurfaceSnapshot: undefined, error: undefined, calculationKind: 'single', reactionStatus: 'idle', reactionPath: undefined, reactionProject: undefined, reactionFrameIndex: 0, selectedGeometryIndex: 0, reactionScfIterationIndex: 0, reactionError: undefined, reactionCopyPrompt: false, trackingEnabled: false, trackingSourceOrbitalId: undefined, trackingSourceGeometryIndex: undefined, trackingId: undefined, trackingActive: undefined, trackingLoading: false, trackingError: undefined, trackingSurfaceError: undefined, trackingResult: undefined }),
  updateProject: patch => { const state = get(); set(withCommand(state, { ...state.project, ...patch })) },
  undo: () => { const state = get(); const previous = state.history.past.at(-1); if (previous) set({ project: previous, history: { past: state.history.past.slice(0, -1), future: [state.project, ...state.history.future] }, selection: [] }) },
  redo: () => { const state = get(); const next = state.history.future[0]; if (next) set({ project: next, history: { past: [...state.history.past, state.project], future: state.history.future.slice(1) }, selection: [] }) },
  applyResult: result => { const state = get(); set({ result, optimizedProject: { ...state.project, atoms: result.optimized_atoms, lastCalculationId: result.job_id }, viewStructure: 'optimized', surfaces: [], aoMode: false, aoOrbitalId: undefined, aoSurfaceSnapshot: undefined }) },
  setViewStructure: viewStructure => set({ viewStructure }), setResult: result => set({ result }),
  upsertSurface: layer => set(state => ({ surfaces: [...state.surfaces.filter(x => x.key !== layer.key), layer] })),
  removeSurface: key => set(state => ({ surfaces: state.surfaces.filter(x => x.key !== key) })),
  setSelectedOrbital: selectedOrbital => set({ selectedOrbital }), setNotice: notice => set({ notice }), setError: error => set({ error }), setOrbitEnabled: orbitEnabled => set({ orbitEnabled }),
  enterAOMode: reference => set(state => {
    const snapshot = state.aoSurfaceSnapshot ?? state.surfaces.map(layer => ({ ...layer, meshUrls: { ...layer.meshUrls } }))
    const base = snapshot.map(layer => ({ ...layer, meshUrls: { ...layer.meshUrls } }))
    const referenceIndex = base.findIndex(layer => layer.key === reference.key)
    if (referenceIndex < 0) base.push(reference)
    const surfaces = base.map(layer => {
      if (layer.field !== 'mo') return layer
      return layer.key === reference.key
        ? { ...layer, visible: true, opacity: AO_REFERENCE_OPACITY }
        : { ...layer, visible: false }
    })
    return { aoMode: true, aoOrbitalId: reference.orbitalInternalId, aoSurfaceSnapshot: snapshot, surfaces }
  }),
  exitAOMode: () => set(state => ({
    surfaces: (state.aoSurfaceSnapshot ?? state.surfaces.filter(layer => layer.field !== 'ao_component')).map(layer => ({ ...layer, meshUrls: { ...layer.meshUrls } })),
    aoMode: false,
    aoOrbitalId: undefined,
    aoSurfaceSnapshot: undefined,
  })),
  setCalculationKind: calculationKind => set(state => ({
    calculationKind,
    reactionStatus: calculationKind === 'reaction-path'
      ? (state.reactionPath ? 'paused' : 'idle')
      : 'idle',
    tool: calculationKind === 'single' ? state.tool : 'select',
    toolAtoms: [],
    selection: [],
    ...(calculationKind === 'single' ? {
      trackingEnabled: false, trackingSourceOrbitalId: undefined,
      trackingSourceGeometryIndex: undefined, trackingId: undefined,
      trackingActive: undefined, trackingLoading: false, trackingError: undefined,
      trackingSurfaceError: undefined, trackingResult: undefined,
    } : {}),
  })),
  setLastCalculationId: lastCalculationId => set(state => ({
    project: { ...state.project, lastCalculationId },
  })),
  beginReactionPathLoad: () => set({ reactionStatus: 'loading-path', reactionError: undefined }),
  applyReactionPath: reactionPath => set(state => {
    const frame = reactionPath.displayFrames[0]
    return {
      calculationKind: 'reaction-path', reactionPath, reactionFrameIndex: 0,
      selectedGeometryIndex: frame.leftImageIndex,
      reactionScfIterationIndex: 0,
      reactionProject: projectForReactionFrame(state.project, reactionPath.path, frame),
      reactionStatus: 'paused', reactionError: undefined,
      surfaces: [], selection: [], toolAtoms: [],
      trackingEnabled: false, trackingSourceOrbitalId: undefined,
      trackingSourceGeometryIndex: undefined, trackingId: undefined,
      trackingActive: undefined, trackingLoading: false, trackingError: undefined,
      trackingSurfaceError: undefined, trackingResult: undefined,
    }
  }),
  failReactionPath: reactionError => set({ reactionStatus: 'error', reactionError }),
  setReactionFrame: reactionFrameIndex => set(state => {
    if (!state.reactionPath) return {}
    const bounded = Math.max(0, Math.min(reactionFrameIndex, state.reactionPath.displayFrames.length - 1))
    const frame = state.reactionPath.displayFrames[bounded]
    return {
      reactionFrameIndex: bounded,
      selectedGeometryIndex: frame.leftImageIndex,
      reactionScfIterationIndex: state.reactionPath.path.images[frame.leftImageIndex]?.scfIterations?.length ?? 0,
      reactionProject: projectForReactionFrame(state.project, state.reactionPath.path, frame, state.reactionProject?.bonds),
    }
  }),
  setReactionScfIteration: reactionScfIterationIndex => set(state => {
    if (!state.reactionPath) return {}
    const frame = state.reactionPath.displayFrames[state.reactionFrameIndex]
    const maximum = state.reactionPath.path.images[frame.leftImageIndex]?.scfIterations?.length ?? 0
    return { reactionScfIterationIndex: Math.max(0, Math.min(maximum, reactionScfIterationIndex)) }
  }),
  setReactionPlaying: playing => set(state => ({
    reactionStatus: playing ? 'playing' : state.reactionPath ? 'paused' : 'idle',
    tool: playing && structureTools.has(state.tool) ? 'select' : state.tool,
    toolAtoms: playing ? [] : state.toolAtoms,
  })),
  beginMoTracking: () => set(state => {
    if (!state.selectedOrbital || !state.reactionPath) return {}
    const frame = state.reactionPath.displayFrames[state.reactionFrameIndex]
    if (!frame?.isCalculated) return { trackingError: '실제 ORCA geometry에서만 MO Tracking을 시작할 수 있습니다.' }
    return {
      trackingEnabled: true,
      trackingSourceOrbitalId: state.selectedOrbital,
      trackingSourceGeometryIndex: frame.leftImageIndex,
      trackingId: undefined,
      trackingActive: undefined,
      trackingLoading: true,
      trackingError: undefined,
      trackingSurfaceError: undefined,
      trackingResult: undefined,
    }
  }),
  completeMoTracking: (resultOrId: OrbitalTrackingResult | string, maybeActive?: boolean) => set(state => {
    const result = typeof resultOrId === 'string'
      ? {
          trackingId: resultOrId,
          sourceOrbital: state.trackingSourceOrbitalId ?? '',
          sourceGeometryIndex: state.trackingSourceGeometryIndex ?? 0,
          threshold: 0.6,
          active: maybeActive ?? false,
          steps: [],
          transitions: [],
          cacheHit: false,
        }
      : resultOrId
    return {
      trackingId: result.trackingId,
      trackingActive: result.active,
      trackingLoading: false,
      trackingError: undefined,
      trackingSurfaceError: undefined,
      trackingResult: result,
    }
  }),
  failMoTrackingSetup: trackingError => set({
    trackingEnabled: false,
    trackingLoading: false,
    trackingActive: false,
    trackingError,
    trackingSurfaceError: undefined,
    trackingResult: undefined,
  }),
  failMoTrackingSurface: trackingSurfaceError => set(state => ({
    trackingLoading: false,
    trackingActive: state.trackingActive ?? true,
    trackingSurfaceError,
  })),
  failMoTracking: trackingError => set({
    trackingEnabled: false,
    trackingLoading: false,
    trackingActive: false,
    trackingError,
    trackingSurfaceError: undefined,
    trackingResult: undefined,
  }),
  stopMoTracking: () => set(state => ({
    trackingEnabled: false, trackingSourceOrbitalId: undefined,
    trackingSourceGeometryIndex: undefined, trackingId: undefined,
    trackingActive: undefined, trackingLoading: false, trackingError: undefined,
    trackingSurfaceError: undefined, trackingResult: undefined,
    surfaces: state.surfaces.filter(layer => layer.key !== 'reaction-path-mo'),
  })),
  copyReactionFrameToSingle: () => set(state => {
    if (!state.reactionProject) return { reactionCopyPrompt: false }
    const project = refreshPlanes({ ...state.reactionProject, name: `${state.project.name} · 경로 프레임 복사` })
    return {
      project, optimizedProject: undefined, viewStructure: 'initial', calculationKind: 'single',
      reactionStatus: 'idle', reactionPath: undefined, reactionProject: undefined,
      reactionFrameIndex: 0, selectedGeometryIndex: 0, reactionScfIterationIndex: 0,
      reactionCopyPrompt: false, reactionError: undefined,
      selection: [], toolAtoms: [], history: { past: [], future: [] }, surfaces: [], result: undefined,
      trackingEnabled: false, trackingSourceOrbitalId: undefined,
      trackingSourceGeometryIndex: undefined, trackingId: undefined,
      trackingActive: undefined, trackingLoading: false, trackingError: undefined,
      trackingSurfaceError: undefined, trackingResult: undefined,
      notice: '현재 경로 프레임을 새 단일 구조로 복사했습니다.',
    }
  }),
  dismissReactionCopyPrompt: () => set({ reactionCopyPrompt: false }),
}))

export const visibleProject = (state: ProjectStore) => state.calculationKind === 'reaction-path' && state.reactionProject
  ? state.reactionProject
  : state.viewStructure === 'optimized' && state.optimizedProject ? state.optimizedProject : state.project
