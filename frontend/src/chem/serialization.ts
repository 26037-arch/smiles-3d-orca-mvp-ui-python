import { inferBonds } from './bonds'
import { normalizeElement } from './elements'
import type { Atom, MoleculeProject } from '../types'

export function projectToJson(project: MoleculeProject) { return JSON.stringify(project, null, 2) }

export function parseProjectJson(text: string): MoleculeProject {
  const value = JSON.parse(text) as MoleculeProject
  if (value.schemaVersion !== 1 || !Array.isArray(value.atoms) || !Array.isArray(value.bonds)) throw new Error('지원하지 않거나 손상된 프로젝트 JSON입니다')
  const ids = new Set<string>()
  value.atoms.forEach(atom => {
    if (ids.has(atom.id)) throw new Error('중복된 원자 id가 있습니다')
    ids.add(atom.id)
    if (!normalizeElement(atom.element) || atom.position.length !== 3 || atom.position.some(x => !Number.isFinite(x))) throw new Error('잘못된 원자 데이터가 있습니다')
  })
  return value
}

export function projectToXyz(project: MoleculeProject): string {
  return `${project.atoms.length}\n${project.name}; charge=${project.totalCharge}; multiplicity=${project.multiplicity}\n${project.atoms.map(a => `${a.element.padEnd(3)} ${a.position.map(x => x.toFixed(10)).join(' ')}`).join('\n')}\n`
}

export function xyzToAtoms(text: string): Atom[] {
  const lines = text.trim().split(/\r?\n/); const count = Number(lines[0])
  if (!Number.isInteger(count) || count < 0 || lines.length < count + 2) throw new Error('손상된 XYZ 파일입니다')
  return lines.slice(2, count + 2).map((line, i) => {
    const [raw, ...coords] = line.trim().split(/\s+/); const element = normalizeElement(raw); const position = coords.slice(0, 3).map(Number)
    if (!element || position.length !== 3 || position.some(x => !Number.isFinite(x))) throw new Error(`XYZ ${i + 3}행이 잘못되었습니다`)
    return { id: crypto.randomUUID(), element, position: position as [number, number, number] }
  })
}

export function replaceFromXyz(project: MoleculeProject, text: string): MoleculeProject {
  const atoms = xyzToAtoms(text)
  return { ...project, atoms, bonds: inferBonds(atoms), sketchPlanes: project.sketchPlanes.filter(p => p.kind !== 'THREE_ATOMS'), manualBondExclusions: [] }
}

export function downloadText(filename: string, content: string, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([content], { type })); const anchor = document.createElement('a')
  anchor.href = url; anchor.download = filename; anchor.click(); URL.revokeObjectURL(url)
}

