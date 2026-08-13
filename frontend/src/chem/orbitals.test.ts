import { describe, expect, it } from 'vitest'
import type { Orbital, OrbitalSpin, SurfaceLayer } from '../types'
import {
  createSurfaceLayer,
  displayNumberToOrcaIndex,
  frontierOrbitals,
  orbitalOptionLabel,
  orbitalSurfaceKey,
  orcaIndexToDisplayNumber,
  surfaceRequestForLayer,
  toggleSurfaceLayer,
} from './orbitals'

const orbital = (
  index: number,
  spin: OrbitalSpin = 'restricted',
  label?: string,
): Orbital => ({
  internal_id: `${spin}:${index}`,
  orca_index: index,
  display_number: index + 1,
  energy_hartree: -0.5 + index * 0.02,
  occupancy: index <= 4 ? 2 : 0,
  spin,
  label,
})

describe('orbital numbering', () => {
  it('keeps internal ORCA zero-based index distinct from user display number', () => {
    expect(orcaIndexToDisplayNumber(0)).toBe(1)
    expect(displayNumberToOrcaIndex(6)).toBe(5)
  })
  it('rejects invalid values', () => {
    expect(() => orcaIndexToDisplayNumber(-1)).toThrow()
    expect(() => displayNumberToOrcaIndex(0)).toThrow()
  })
})

describe('orbital surface selection', () => {
  it('keeps the five frontier orbitals around HOMO by default', () => {
    const orbitals = Array.from({ length: 10 }, (_, index) => (
      orbital(index, 'restricted', index === 4 ? 'HOMO' : index === 5 ? 'LUMO' : undefined)
    ))

    expect(frontierOrbitals(orbitals, 'restricted:4').map(item => item.orca_index)).toEqual([
      2, 3, 4, 5, 6,
    ])
  })

  it('formats any calculated orbital for the compact full-MO selector', () => {
    const selected = orbital(16, 'alpha', 'HOMO')

    expect(orbitalOptionLabel(selected)).toContain('α MO 17 · HOMO')
    expect(orbitalOptionLabel(selected)).toContain('occ 0.0')
  })

  it.each<OrbitalSpin>(['restricted', 'alpha', 'beta'])(
    'preserves the %s spin and ORCA index in a surface layer and request',
    spin => {
      const selected = orbital(17, spin)
      const layer = createSurfaceLayer(selected)
      const request = surfaceRequestForLayer(layer)

      expect(layer.orbitalIndex).toBe(17)
      expect(layer.spin).toBe(spin)
      expect(request.spin).toBe(spin)
      expect(request.orbital_index).toBe(17)
    },
  )

  it('uses distinct keys for alpha and beta orbitals with the same index', () => {
    expect(orbitalSurfaceKey(orbital(17, 'alpha'))).toBe('mo:alpha:17')
    expect(orbitalSurfaceKey(orbital(17, 'beta'))).toBe('mo:beta:17')
  })

  it('toggles an existing MO instead of creating a duplicate layer', () => {
    const selected = orbital(3)
    const existing = createSurfaceLayer(selected)
    const update = toggleSurfaceLayer([existing], selected)

    expect(update.layer?.key).toBe(existing.key)
    expect(update.layer?.visible).toBe(false)
  })

  it('retains the six-visible-surface limit for an additional MO', () => {
    const visibleLayers = Array.from({ length: 6 }, (_, index) => ({
      ...createSurfaceLayer(orbital(index)),
      key: `existing:${index}`,
    })) satisfies SurfaceLayer[]

    expect(toggleSurfaceLayer(visibleLayers, orbital(20)).error).toContain('최대 6개')
  })
})
