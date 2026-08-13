import { useFrame, useThree } from '@react-three/fiber'
import { useEffect, useMemo } from 'react'
import * as THREE from 'three'
import { configureOitMaterial, OIT_LAYER, OIT_SURFACE_FLAG, type OitPass } from './weightedBlendedOitMaterial'

const compositeVertexShader = /* glsl */ `
  varying vec2 vUv;

  void main() {
    vUv = uv;
    gl_Position = vec4(position.xy, 0.0, 1.0);
  }
`

const compositeFragmentShader = /* glsl */ `
  uniform sampler2D uOpaque;
  uniform sampler2D uAccumulation;
  uniform sampler2D uRevealage;

  varying vec2 vUv;

  void main() {
    vec3 opaque = texture2D(uOpaque, vUv).rgb;
    vec4 accumulation = texture2D(uAccumulation, vUv);
    float revealage = clamp(texture2D(uRevealage, vUv).r, 0.0, 1.0);
    vec3 transparentColor = accumulation.rgb / max(accumulation.a, 1.0e-5);
    gl_FragColor = vec4(
      transparentColor * (1.0 - revealage) + opaque * revealage,
      1.0
    );
    #include <colorspace_fragment>
  }
`

function configureSurfacePass(scene: THREE.Scene, pass: OitPass) {
  scene.traverse(object => {
    if (!object.userData[OIT_SURFACE_FLAG]) return
    const mesh = object as THREE.Mesh
    const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material]
    materials.forEach(material => {
      if (material instanceof THREE.ShaderMaterial) configureOitMaterial(material, pass)
    })
  })
}

function makeRenderTargets() {
  const depthTexture = new THREE.DepthTexture(1, 1, THREE.UnsignedIntType)
  depthTexture.format = THREE.DepthFormat

  const opaque = new THREE.WebGLRenderTarget(1, 1, {
    minFilter: THREE.LinearFilter,
    magFilter: THREE.LinearFilter,
    depthBuffer: true,
    stencilBuffer: false,
    depthTexture,
  })
  opaque.texture.name = 'WBOIT opaque color'

  const accumulation = new THREE.WebGLRenderTarget(1, 1, {
    minFilter: THREE.NearestFilter,
    magFilter: THREE.NearestFilter,
    type: THREE.HalfFloatType,
    format: THREE.RGBAFormat,
    depthBuffer: true,
    stencilBuffer: false,
    depthTexture,
  })
  accumulation.texture.name = 'WBOIT weighted accumulation'

  const revealage = new THREE.WebGLRenderTarget(1, 1, {
    minFilter: THREE.NearestFilter,
    magFilter: THREE.NearestFilter,
    type: THREE.UnsignedByteType,
    format: THREE.RGBAFormat,
    depthBuffer: true,
    stencilBuffer: false,
    depthTexture,
  })
  revealage.texture.name = 'WBOIT revealage'

  return { opaque, accumulation, revealage }
}

export function WeightedBlendedOIT() {
  const { gl, scene, camera } = useThree()
  const targets = useMemo(makeRenderTargets, [])
  const drawingBufferSize = useMemo(() => new THREE.Vector2(), [])
  const previousClearColor = useMemo(() => new THREE.Color(), [])

  const composite = useMemo(() => {
    const material = new THREE.ShaderMaterial({
      uniforms: {
        uOpaque: { value: targets.opaque.texture },
        uAccumulation: { value: targets.accumulation.texture },
        uRevealage: { value: targets.revealage.texture },
      },
      vertexShader: compositeVertexShader,
      fragmentShader: compositeFragmentShader,
      depthTest: false,
      depthWrite: false,
      toneMapped: false,
    })
    const geometry = new THREE.PlaneGeometry(2, 2)
    const quad = new THREE.Mesh(geometry, material)
    quad.frustumCulled = false
    const compositeScene = new THREE.Scene()
    compositeScene.add(quad)
    const compositeCamera = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1)
    return { material, geometry, scene: compositeScene, camera: compositeCamera }
  }, [targets])

  useEffect(() => () => {
    // The three render targets share one depth texture. Detach it from the two
    // secondary framebuffers so the texture is disposed exactly once.
    targets.accumulation.depthTexture = null
    targets.revealage.depthTexture = null
    targets.accumulation.dispose()
    targets.revealage.dispose()
    targets.opaque.dispose()
    composite.geometry.dispose()
    composite.material.dispose()
  }, [composite, targets])

  useFrame(() => {
    gl.getDrawingBufferSize(drawingBufferSize)
    const width = Math.max(1, drawingBufferSize.x)
    const height = Math.max(1, drawingBufferSize.y)
    if (targets.opaque.width !== width || targets.opaque.height !== height) {
      targets.opaque.setSize(width, height)
      targets.accumulation.setSize(width, height)
      targets.revealage.setSize(width, height)
    }

    const previousTarget = gl.getRenderTarget()
    const previousAutoClear = gl.autoClear
    const previousClearAlpha = gl.getClearAlpha()
    const previousBackground = scene.background
    const previousCameraMask = camera.layers.mask
    gl.getClearColor(previousClearColor)

    try {
      gl.autoClear = true
      camera.layers.set(0)
      gl.setRenderTarget(targets.opaque)
      gl.render(scene, camera)

      // Both transparent passes retain the opaque target's shared depth buffer.
      // Only color is cleared, so surfaces remain correctly occluded by atoms.
      scene.background = null
      camera.layers.set(OIT_LAYER)

      configureSurfacePass(scene, 'accumulation')
      gl.setRenderTarget(targets.accumulation)
      gl.setClearColor(0x000000, 0)
      gl.clear(true, false, false)
      gl.render(scene, camera)

      configureSurfacePass(scene, 'revealage')
      gl.setRenderTarget(targets.revealage)
      gl.setClearColor(0xffffff, 1)
      gl.clear(true, false, false)
      gl.render(scene, camera)

      gl.setRenderTarget(null)
      gl.setClearColor(0x000000, 1)
      gl.clear(true, true, true)
      gl.render(composite.scene, composite.camera)
    } finally {
      camera.layers.mask = previousCameraMask
      scene.background = previousBackground
      gl.autoClear = previousAutoClear
      gl.setClearColor(previousClearColor, previousClearAlpha)
      gl.setRenderTarget(previousTarget)
    }
  }, 1)

  return null
}
