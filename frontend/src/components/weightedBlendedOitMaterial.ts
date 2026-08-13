import * as THREE from 'three'

export const OIT_LAYER = 1
export const OIT_SURFACE_FLAG = 'weightedBlendedOIT'

export const surfaceVertexShader = /* glsl */ `
  varying vec3 vNormal;
  varying vec3 vViewPosition;

  void main() {
    vec4 viewPosition = modelViewMatrix * vec4(position, 1.0);
    vNormal = normalize(normalMatrix * normal);
    vViewPosition = -viewPosition.xyz;
    gl_Position = projectionMatrix * viewPosition;
  }
`

export const surfaceFragmentShader = /* glsl */ `
  uniform vec3 uColor;
  uniform float uOpacity;
  uniform bool uRevealPass;

  varying vec3 vNormal;
  varying vec3 vViewPosition;

  void main() {
    float alpha = clamp(uOpacity, 0.0, 1.0);
    if (alpha <= 0.0001) discard;

    vec3 normal = normalize(vNormal);
    if (!gl_FrontFacing) normal = -normal;

    vec3 keyLight = normalize(vec3(0.45, 0.75, 0.55));
    vec3 fillLight = normalize(vec3(-0.65, -0.25, 0.35));
    vec3 viewDirection = normalize(vViewPosition);
    float diffuse = 0.34
      + 0.54 * max(dot(normal, keyLight), 0.0)
      + 0.16 * max(dot(normal, fillLight), 0.0);
    float specular = 0.22 * pow(
      max(dot(reflect(-keyLight, normal), viewDirection), 0.0),
      32.0
    );
    vec3 shadedColor = uColor * diffuse + vec3(specular);

    if (uRevealPass) {
      // ZERO, ONE_MINUS_SRC_ALPHA blending multiplies revealage by (1-alpha).
      gl_FragColor = vec4(0.0, 0.0, 0.0, alpha);
      return;
    }

    // McGuire/Bavoil weighted blended OIT weighting. Dividing by the maximum
    // keeps the same relative weights while preserving headroom in RGBA16F.
    float weight = clamp(
      pow(min(1.0, alpha * 10.0) + 0.01, 3.0)
        * 1.0e8
        * pow(1.0 - gl_FragCoord.z * 0.9, 3.0),
      1.0e-2,
      3.0e3
    ) / 3.0e3;

    // ONE, ONE blending accumulates premultiplied weighted color and alpha.
    gl_FragColor = vec4(shadedColor * alpha * weight, alpha * weight);
  }
`

export type OitPass = 'accumulation' | 'revealage'

export function createOitSurfaceMaterial(color: THREE.ColorRepresentation, opacity: number) {
  return new THREE.ShaderMaterial({
    uniforms: {
      uColor: { value: new THREE.Color(color) },
      uOpacity: { value: opacity },
      uRevealPass: { value: false },
    },
    vertexShader: surfaceVertexShader,
    fragmentShader: surfaceFragmentShader,
    transparent: true,
    depthTest: true,
    depthWrite: false,
    side: THREE.DoubleSide,
    blending: THREE.CustomBlending,
    blendEquation: THREE.AddEquation,
    blendSrc: THREE.OneFactor,
    blendDst: THREE.OneFactor,
    toneMapped: false,
  })
}

export function configureOitMaterial(material: THREE.ShaderMaterial, pass: OitPass) {
  const revealage = pass === 'revealage'
  material.uniforms.uRevealPass.value = revealage
  material.blendSrc = revealage ? THREE.ZeroFactor : THREE.OneFactor
  material.blendDst = revealage ? THREE.OneMinusSrcAlphaFactor : THREE.OneFactor
  material.blendEquation = THREE.AddEquation
}
