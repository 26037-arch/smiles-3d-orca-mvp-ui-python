import { describe, expect, it } from 'vitest'
import { displayNumberToOrcaIndex, orcaIndexToDisplayNumber } from './orbitals'

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

