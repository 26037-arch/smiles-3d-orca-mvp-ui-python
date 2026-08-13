import { inferBonds } from './bonds'
import { ELEMENTS } from './elements'
import { xyzToAtoms } from './serialization'
import type { MoleculeProject } from '../types'

export function validateReactionEndpoints(
  reactant: MoleculeProject,
  product?: MoleculeProject,
): string | undefined {
  if (!product) return '생성물 endpoint를 불러오세요.'
  if (reactant.atoms.length !== product.atoms.length) {
    return `반응물은 ${reactant.atoms.length}개, 생성물은 ${product.atoms.length}개 원자입니다.`
  }
  for (let index = 0; index < reactant.atoms.length; index++) {
    const left = reactant.atoms[index]
    const right = product.atoms[index]
    if (left.position.some(value => !Number.isFinite(value)) || right.position.some(value => !Number.isFinite(value))) {
      return `${index + 1}번 원자의 좌표는 유한한 숫자여야 합니다.`
    }
    if (left.element !== right.element) {
      return `생성물 ${index + 1}번 원자는 ${right.element}이지만 반응물 ${index + 1}번 원자는 ${left.element}입니다. 반응물과 생성물의 원자 순서를 동일하게 맞춰 주세요.`
    }
  }
  if (reactant.totalCharge !== product.totalCharge) return '반응물과 생성물의 전체 전하가 다릅니다.'
  if (reactant.multiplicity !== product.multiplicity) return '반응물과 생성물의 다중도가 다릅니다.'
  const electrons = reactant.atoms.reduce(
    (sum, atom) => sum + ELEMENTS[atom.element].atomicNumber,
    -reactant.totalCharge,
  )
  if (electrons % 2 !== (reactant.multiplicity - 1) % 2) {
    return `전자 수 ${electrons}과 다중도 ${reactant.multiplicity}의 parity가 일치하지 않습니다.`
  }
  const identical = reactant.atoms.every((atom, index) => atom.position.every(
    (value, axis) => Math.abs(value - product.atoms[index].position[axis]) <= 1e-12,
  ))
  if (identical) return '반응물과 생성물 좌표가 동일합니다.'
  return undefined
}

export function productProjectFromXyz(
  reactant: MoleculeProject,
  text: string,
  name: string,
): MoleculeProject {
  const atoms = xyzToAtoms(text)
  return {
    ...reactant,
    name,
    atoms,
    bonds: inferBonds(atoms),
    sketchPlanes: [],
    manualBondExclusions: [],
    lastCalculationId: undefined,
  }
}

export function overlayEndpointProject(
  reactant: MoleculeProject,
  product: MoleculeProject,
): MoleculeProject {
  const productAtoms = product.atoms.map((atom, index) => ({
    ...atom,
    id: `product-preview-${index}`,
    label: `${atom.element} · 생성물`,
  }))
  return {
    ...reactant,
    name: `${reactant.name} · endpoint 겹쳐 보기`,
    atoms: [...reactant.atoms, ...productAtoms],
    bonds: [...reactant.bonds],
    sketchPlanes: [],
  }
}
