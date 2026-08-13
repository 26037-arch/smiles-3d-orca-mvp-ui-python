import { describe, expect, it } from 'vitest'
import { apiErrorMessage } from './client'

describe('API error formatting', () => {
  it('preserves the structured backend error code and detail', () => {
    expect(apiErrorMessage({
      detail: {
        code: 'AO_BASIS_MAPPING_FAILED',
        message: 'Expected one AO Cube; found 5.',
      },
    }, 422, 'Unprocessable Entity')).toBe(
      'AO_BASIS_MAPPING_FAILED: Expected one AO Cube; found 5.',
    )
  })
})
