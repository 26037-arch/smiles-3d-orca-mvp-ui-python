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

export interface Orbital {
  internal_id: string
  orca_index: number
  display_number: number
  energy_hartree: number
  occupancy: number
  spin: 'restricted' | 'alpha' | 'beta'
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
  field: 'total_density' | 'mo'
  orbitalIndex?: number
  visible: boolean
  opacity: number
  isovalue: number
  positiveColor: string
  negativeColor: string
  meshUrls: Record<string, string>
  loading?: boolean
  cacheHit?: boolean
  error?: string
}

export interface Capabilities {
  calculation: { available: boolean; reasons: string[] }
  demo: { available: boolean; label: string }
  opi: { available: boolean; version?: string }
  orca: { available: boolean; path?: string; version?: string; compatible: boolean }
  orcaPlot: { available: boolean; path?: string }
  jobs: { writable: boolean; path: string }
}

