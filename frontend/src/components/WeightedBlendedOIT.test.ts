import { describe, expect, it } from 'vitest'
import * as THREE from 'three'
import { configureOitMaterial, createOitSurfaceMaterial } from './weightedBlendedOitMaterial'

describe('weighted blended OIT material', () => {
  it('uses additive blending for weighted color accumulation', () => {
    const material = createOitSurfaceMaterial('#ff0000', 0.42)
    configureOitMaterial(material, 'accumulation')

    expect(material.transparent).toBe(true)
    expect(material.depthTest).toBe(true)
    expect(material.depthWrite).toBe(false)
    expect(material.blendSrc).toBe(THREE.OneFactor)
    expect(material.blendDst).toBe(THREE.OneFactor)
    expect(material.uniforms.uRevealPass.value).toBe(false)
    material.dispose()
  })

  it('multiplies revealage by one minus fragment alpha', () => {
    const material = createOitSurfaceMaterial('#00ff00', 0.63)
    configureOitMaterial(material, 'revealage')

    expect(material.blendSrc).toBe(THREE.ZeroFactor)
    expect(material.blendDst).toBe(THREE.OneMinusSrcAlphaFactor)
    expect(material.uniforms.uRevealPass.value).toBe(true)
    material.dispose()
  })
})
