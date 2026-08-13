export type Vec3 = [number, number, number]
export type Tool = 'select' | 'add' | 'move' | 'plane' | 'bond-add' | 'bond-delete' | 'distance' | 'angle'

export interface Atom {
  id: string
  element: string
  position: Vec3
  label?: string
}

export interface Bond {
  id: string
  atomId1: string
  atomId2: string
  order: 1 | 2 | 3
  source: 'inferred' | 'manual'
}

export interface SketchPlane {
  id: string
  kind: 'XY' | 'YZ' | 'ZX' | 'THREE_ATOMS'
  atomIds: string[]
  origin: Vec3
  normal: Vec3
  basisU: Vec3
  basisV: Vec3
  visible: boolean
  active: boolean
  valid: boolean
}

export interface MoleculeProject {
  schemaVersion: 1
  name: string
  atoms: Atom[]
  bonds: Bond[]
  sketchPlanes: SketchPlane[]
  manualBondExclusions: [string, string][]
  totalCharge: number
  multiplicity: number
  calculationPreset: string
  displaySettings: {
    perspective: boolean
    showGrid: boolean
    showAxes: boolean
    atomScale: number
    bondScale: number
  }
  lastCalculationId?: string
}

export type OrbitalSpin = 'restricted' | 'alpha' | 'beta'
export type CalculationKind = 'single' | 'reaction-path'
export type ReactionPathStatus = 'idle' | 'loading-path' | 'ready' | 'loading-orbitals' | 'preparing-display-frames' | 'playing' | 'paused' | 'error'

export interface CalculatedImageAtom {
  element: string
  atomIndex: number
  x: number
  y: number
  z: number
}

export interface CalculatedImage {
  id: string
  index: number
  atoms: CalculatedImageAtom[]
  energyHartree: number | null
  relativeEnergyKjMol: number | null
  reactionCoordinate: number | null
  gradient?: number[][]
  wavefunctionRef?: string | null
  orbitalRefs: Record<string, string>
  convergence: 'converged' | 'unconverged' | 'unknown'
}

export interface ReactionPathResult {
  schemaVersion: 1
  sourceType: 'imported' | 'neb' | 'irc' | 'relaxed-scan'
  atomCount: number
  elements: string[]
  charge: number | null
  multiplicity: number | null
  images: CalculatedImage[]
  hasPhysicalTime: false
  sourceTrajectory?: string | null
  energyReference?: 'first-image'
  energyUnit?: 'hartree'
  relativeEnergyUnit?: 'kJ/mol'
  reactionCoordinateSource?: 'orca' | 'derived-aligned-cartesian' | 'unknown'
  sourceMetadata?: {
    path: string
    size: number
    mtimeNs: number
    sha256: string
  } | null
}

export interface DisplayFrame {
  index: number
  leftImageIndex: number
  rightImageIndex: number
  interpolationValue: number
  coordinates: Vec3[]
  reactionCoordinate: number
  relativeEnergyKjMol: number | null
  isCalculated: boolean
}

export interface ReactionPathPlayback {
  path: ReactionPathResult
  displayFrames: DisplayFrame[]
}

export interface OrbitalMatch {
  leftOrbitalId: string
  rightOrbitalId: string | null
  signedOverlap: number | null
  absoluteOverlap: number | null
  status: 'matched' | 'below-threshold' | 'ambiguous'
}

export interface Orbital {
  internal_id: string
  orca_index: number
  display_number: number
  energy_hartree: number
  occupancy: number
  spin: OrbitalSpin
  label?: string
}

export interface CalculationResult {
  job_id: string
  optimized_atoms: Atom[]
  total_energy_hartree: number
  normal_termination: boolean
  scf_converged: boolean
  geometry_converged: boolean
  local_minimum_notice: string
  orbitals: Orbital[]
  homo_internal_id?: string
  lumo_internal_id?: string
  demo: boolean
}

export interface SurfaceLayer {
  key: string
  name: string
  field: 'total_density' | 'mo' | 'ao_component'
  orbitalIndex?: number
  orbitalInternalId?: string
  basisIndex?: number
  spin: OrbitalSpin
  visible: boolean
  opacity: number
  isovalue: number
  positiveColor: string
  negativeColor: string
  meshUrls: Record<string, string>
  loading?: boolean
  cacheHit?: boolean
  error?: string
  reactionFrame?: boolean
}

export interface Capabilities {
  calculation: { available: boolean; reasons: string[] }
  demo: { available: boolean; label: string }
  opi: { available: boolean; version?: string }
  orca: { available: boolean; path?: string; version?: string; compatible: boolean }
  orcaPlot: { available: boolean; path?: string }
  orca2Json: { available: boolean; path?: string }
  aoComposition: { available: boolean; reasons: string[] }
  jobs: { writable: boolean; path: string }
}

export interface BasisContribution {
  basis_index: number
  atom_index: number
  atom_label: string
  element: string
  ao_label: string
  shell_label: string
  coefficient: number
  loewdin_weight: number
  percentage: number
  phase: '+' | '-'
}

export interface AOContributionGroup {
  key: string
  atom_index: number
  atom_label: string
  element: string
  ao_label: string
  basis_indices: number[]
  count: number
  percentage: number
  representative_phase: '+' | '-'
}

export interface OrbitalComposition {
  orbital_internal_id: string
  energy_hartree: number
  population_method: 'loewdin'
  interpretation: 'selected_mo_basis_component'
  items: BasisContribution[]
  groups: AOContributionGroup[]
  offset: number
  limit: number
  total: number
  has_more: boolean
  cache_hit: boolean
}

export type PlotFieldMode = 'mo' | 'total_density'
export type PlotCut =
  | { kind: 'axis_line'; axis: 'x' | 'y' | 'z'; offsets: [number, number] }
  | { kind: 'atom_line'; atom_ids: [string, string] }
  | { kind: 'axis_plane'; plane: 'xy' | 'yz' | 'zx'; offset: number }
  | { kind: 'atom_plane'; atom_ids: [string, string, string] }

export interface PlotSampleRequest {
  field: {
    field: PlotFieldMode
    orbital_internal_id?: string
    orbital_index?: number
    spin?: OrbitalSpin
  }
  cut: PlotCut
  bounds: { automatic: boolean; padding: number }
  line_samples?: number
  plane_samples_u?: number
  plane_samples_v?: number
  cube_resolution?: number
}

export interface LinePlotSample {
  kind: 'line'
  field: PlotSampleRequest['field']
  coordinate_label: string
  coordinates: number[]
  values: Array<number | null>
  valid: boolean[]
  origin: Vec3
  direction: Vec3
  bounds: { s: [number, number] }
  cache_hit: boolean
}

export interface PlanePlotSample {
  kind: 'plane'
  field: PlotSampleRequest['field']
  u_label: string
  v_label: string
  u: number[]
  v: number[]
  values: Array<Array<number | null>>
  valid: boolean[][]
  origin: Vec3
  basis_u: Vec3
  basis_v: Vec3
  bounds: { u: [number, number]; v: [number, number] }
  cache_hit: boolean
}

export type PlotSample = LinePlotSample | PlanePlotSample
