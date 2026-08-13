import { Html, Line, OrbitControls, PerspectiveCamera, OrthographicCamera, TransformControls } from '@react-three/drei'
import { Canvas, type ThreeEvent, useThree } from '@react-three/fiber'
import { useEffect, useMemo, useRef, useState } from 'react'
import * as THREE from 'three'
import { Pause, Play } from 'lucide-react'
import { PLYLoader } from 'three/examples/jsm/loaders/PLYLoader.js'
import { angleDegrees, distance, normalize, stableAngleAxis, sub } from '../chem/geometry'
import { advancePlaybackFrame, playbackStartFrame, REACTION_PLAYBACK_FRAME_MS } from '../chem/reactionPath'
import { ELEMENTS } from '../chem/elements'
import { useProjectStore, visibleProject } from '../store/projectStore'
import type { Atom, Bond, SketchPlane, SurfaceLayer, Vec3 } from '../types'
import { WeightedBlendedOIT } from './WeightedBlendedOIT'
import { createOitSurfaceMaterial, OIT_LAYER, OIT_SURFACE_FLAG } from './weightedBlendedOitMaterial'
import { api } from '../api/client'

function BondMesh({ bond, atoms }: { bond: Bond; atoms: Atom[] }) {
  const a = atoms.find(x => x.id === bond.atomId1); const b = atoms.find(x => x.id === bond.atomId2)
  const data = useMemo(() => {
    if (!a || !b) return null; const start = new THREE.Vector3(...a.position); const end = new THREE.Vector3(...b.position)
    const midpoint = start.clone().add(end).multiplyScalar(.5); const length = start.distanceTo(end)
    const quaternion = new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 1, 0), end.clone().sub(start).normalize())
    return { midpoint, length, quaternion }
  }, [a, b])
  if (!data) return null
  return <group position={data.midpoint} quaternion={data.quaternion}>{Array.from({ length: bond.order }, (_, i) => <mesh key={i} position={[(i - (bond.order - 1) / 2) * .1, 0, 0]}><cylinderGeometry args={[.065, .065, data.length, 18]} /><meshStandardMaterial color={bond.source === 'manual' ? '#b9c8dc' : '#75869b'} /></mesh>)}</group>
}

function AtomMesh({ atom }: { atom: Atom }) {
  const selected = useProjectStore(s => s.selection.includes(atom.id)); const select = useProjectStore(s => s.selectAtom); const tool = useProjectStore(s => s.tool)
  const productPreview = atom.id.startsWith('product-preview-')
  return <mesh position={atom.position} onPointerDown={(e: ThreeEvent<PointerEvent>) => { e.stopPropagation(); select(atom.id, e.ctrlKey || e.shiftKey) }} castShadow>
    <sphereGeometry args={[Math.max(.24, ELEMENTS[atom.element].radius * .35), 32, 20]} />
    <meshStandardMaterial color={ELEMENTS[atom.element].color} transparent={productPreview} opacity={productPreview ? .48 : 1} emissive={selected || productPreview ? '#55d6ff' : '#000'} emissiveIntensity={selected ? .7 : productPreview ? .25 : 0} roughness={.3} metalness={.05} />
    {(selected || tool === 'distance' || tool === 'angle') && <Html center distanceFactor={8} position={[0, .42, 0]} className="atom-label"><span>{atom.element}</span><small>{atom.id.slice(0, 4)}</small></Html>}
  </mesh>
}

function PlaneMesh({ plane }: { plane: SketchPlane }) {
  const tool = useProjectStore(s => s.tool); const element = useProjectStore(s => s.addElement); const addAtom = useProjectStore(s => s.addAtom); const setError = useProjectStore(s => s.setError)
  const quaternion = useMemo(() => new THREE.Quaternion().setFromUnitVectors(new THREE.Vector3(0, 0, 1), new THREE.Vector3(...plane.normal).normalize()), [plane.normal])
  const lines = useMemo(() => Array.from({ length: 25 }, (_, i) => i - 12), [])
  if (!plane.visible || !plane.valid) return null
  return <group position={plane.origin} quaternion={quaternion}>
    <mesh onPointerDown={e => { if (tool !== 'add' || !plane.active) return; e.stopPropagation(); const p = e.point.toArray() as Vec3; try { addAtom(element, p) } catch (error) { setError((error as Error).message) } }}>
      <planeGeometry args={[12, 12]} /><meshBasicMaterial color={plane.active ? '#2f8cff' : '#54687f'} transparent opacity={plane.active ? .11 : .055} side={THREE.DoubleSide} depthWrite={false} />
    </mesh>
    {lines.map(i => <Line key={`x${i}`} points={[[-6, i / 2, .003], [6, i / 2, .003]]} color={i === 0 ? '#4ea3ff' : '#31455e'} transparent opacity={i === 0 ? .7 : .24} lineWidth={i === 0 ? 1.2 : .6} />)}
    {lines.map(i => <Line key={`y${i}`} points={[[i / 2, -6, .003], [i / 2, 6, .003]]} color={i === 0 ? '#4ea3ff' : '#31455e'} transparent opacity={i === 0 ? .7 : .24} lineWidth={i === 0 ? 1.2 : .6} />)}
    <Html position={[-5.6, 5.6, .01]} className="plane-label"><span>{plane.kind}</span>{plane.active && <b>ACTIVE</b>}</Html>
  </group>
}

function DistanceMeasure({ atoms, ids }: { atoms: Atom[]; ids: string[] }) {
  const apply = useProjectStore(s => s.applyDistance); const [editing, setEditing] = useState(false)
  if (ids.length !== 2) return null; const a = atoms.find(x => x.id === ids[0]); const b = atoms.find(x => x.id === ids[1]); if (!a || !b) return null
  const d = distance(a.position, b.position); const midpoint = a.position.map((x, i) => (x + b.position[i]) / 2) as Vec3
  return <><Line points={[a.position, b.position]} color="#50d5ff" dashed dashScale={15} />
    <Html position={midpoint} center className="measure-label">{editing ? <input autoFocus defaultValue={d.toFixed(4)} onBlur={e => { apply([a.id, b.id], Number(e.target.value)); setEditing(false) }} onKeyDown={e => e.key === 'Enter' && e.currentTarget.blur()} /> : <button onClick={() => setEditing(true)}>{d.toFixed(3)} Å</button>}</Html></>
}

function AngleMeasure({ atoms, ids }: { atoms: Atom[]; ids: string[] }) {
  const apply = useProjectStore(s => s.applyAngle); const [editing, setEditing] = useState(false)
  if (ids.length !== 3) return null; const [a, b, c] = ids.map(id => atoms.find(x => x.id === id)); if (!a || !b || !c) return null
  let angle: number; try { angle = angleDegrees(a.position, b.position, c.position) } catch { return null }
  const ba = normalize(sub(a.position, b.position)); const axis = stableAngleAxis(a.position, b.position, c.position)
  const radius = Math.min(1, distance(a.position, b.position) * .55, distance(c.position, b.position) * .55); const points: Vec3[] = []
  for (let i = 0; i <= 24; i++) { const q = new THREE.Vector3(...ba).applyAxisAngle(new THREE.Vector3(...axis), -angle * Math.PI / 180 * i / 24).multiplyScalar(radius); points.push([b.position[0] + q.x, b.position[1] + q.y, b.position[2] + q.z]) }
  const label = points[12]
  return <><Line points={points} color="#ffca62" lineWidth={2} /><Html position={label} center className="measure-label angle">{editing ? <input autoFocus defaultValue={angle.toFixed(3)} onBlur={e => { apply([a.id, b.id, c.id], Number(e.target.value)); setEditing(false) }} onKeyDown={e => e.key === 'Enter' && e.currentTarget.blur()} /> : <button onClick={() => setEditing(true)}>{angle.toFixed(2)}°</button>}</Html></>
}

function SurfaceMesh({ layer, phase, url }: { layer: SurfaceLayer; phase: string; url: string }) {
  const [geometry, setGeometry] = useState<THREE.BufferGeometry>()
  const geometryRef = useRef<THREE.BufferGeometry | undefined>(undefined)
  useEffect(() => {
    let active = true
    new PLYLoader().load(url, loaded => {
      loaded.computeVertexNormals()
      if (!active) { loaded.dispose(); return }
      geometryRef.current?.dispose()
      geometryRef.current = loaded
      setGeometry(loaded)
    })
    return () => {
      active = false
      geometryRef.current?.dispose()
      geometryRef.current = undefined
    }
  }, [url])
  const color = phase === 'positive' ? layer.positiveColor : layer.negativeColor
  const [material] = useState(() => createOitSurfaceMaterial(color, layer.opacity))
  useEffect(() => {
    material.uniforms.uColor.value.set(color)
    material.uniforms.uOpacity.value = layer.opacity
  }, [color, layer.opacity, material])
  useEffect(() => () => material.dispose(), [material])
  if (!geometry) return null
  return <mesh
    geometry={geometry}
    material={material}
    ref={mesh => mesh?.layers.set(OIT_LAYER)}
    userData={{ [OIT_SURFACE_FLAG]: true }}
  />
}

function FitController({ atoms }: { atoms: Atom[] }) {
  const { camera, controls } = useThree()
  useEffect(() => {
    const fit = () => {
      if (!atoms.length) return; const box = new THREE.Box3().setFromPoints(atoms.map(a => new THREE.Vector3(...a.position))); const sphere = new THREE.Sphere(); box.getBoundingSphere(sphere)
      camera.position.copy(sphere.center.clone().add(new THREE.Vector3(1.5, 1.1, 1.7).normalize().multiplyScalar(Math.max(5, sphere.radius * 4)))); camera.lookAt(sphere.center); camera.updateProjectionMatrix()
      const c = controls as any; if (c?.target) { c.target.copy(sphere.center); c.update() }
    }
    window.addEventListener('fit-molecule', fit); return () => window.removeEventListener('fit-molecule', fit)
  }, [atoms, camera, controls]); return null
}

function TransformGizmo({ atoms }: { atoms: Atom[] }) {
  const selection = useProjectStore(s => s.selection); const move = useProjectStore(s => s.moveAtoms); const setOrbit = useProjectStore(s => s.setOrbitEnabled)
  const group = useRef<THREE.Group>(null); const start = useRef(new THREE.Vector3())
  const center = useMemo(() => { const chosen = atoms.filter(a => selection.includes(a.id)); if (!chosen.length) return new THREE.Vector3(); return chosen.reduce((v, a) => v.add(new THREE.Vector3(...a.position)), new THREE.Vector3()).multiplyScalar(1 / chosen.length) }, [atoms, selection])
  useEffect(() => { group.current?.position.copy(center) }, [center])
  if (!selection.length) return null
  return <TransformControls mode="translate" size={.72} onMouseDown={() => { if (group.current) start.current.copy(group.current.position); setOrbit(false) }} onMouseUp={() => { if (group.current) { const d = group.current.position.clone().sub(start.current); if (d.lengthSq() > 1e-12) move(selection, d.toArray() as Vec3); group.current.position.copy(center) } setOrbit(true) }}><group ref={group} /></TransformControls>
}

function Scene() {
  const project = useProjectStore(visibleProject); const clear = useProjectStore(s => s.clearSelection); const tool = useProjectStore(s => s.tool); const toolAtoms = useProjectStore(s => s.toolAtoms); const surfaces = useProjectStore(s => s.surfaces); const orbitEnabled = useProjectStore(s => s.orbitEnabled); const reactionStatus = useProjectStore(s => s.reactionStatus)
  return <>
    <color attach="background" args={['#07111f']} /><ambientLight intensity={1.25} /><directionalLight position={[5, 8, 6]} intensity={2.2} castShadow /><directionalLight position={[-5, -3, -2]} intensity={.5} color="#4c8cff" />
    {project.displaySettings.perspective ? <PerspectiveCamera makeDefault position={[5, 4, 7]} fov={43} /> : <OrthographicCamera makeDefault position={[5, 4, 7]} zoom={75} />}
    <OrbitControls makeDefault enabled={orbitEnabled} enableDamping dampingFactor={.08} screenSpacePanning />
    <group onPointerMissed={() => clear()}>{project.sketchPlanes.map(p => <PlaneMesh key={p.id} plane={p} />)}{project.bonds.map(b => <BondMesh key={b.id} bond={b} atoms={project.atoms} />)}{project.atoms.map(a => <AtomMesh key={a.id} atom={a} />)}</group>
    {tool === 'move' && reactionStatus !== 'playing' && <TransformGizmo atoms={project.atoms} />}
    {tool === 'distance' && <DistanceMeasure atoms={project.atoms} ids={toolAtoms} />}{tool === 'angle' && <AngleMeasure atoms={project.atoms} ids={toolAtoms} />}
    {surfaces.filter(s => s.visible && !s.loading).flatMap(layer => Object.entries(layer.meshUrls).map(([phase, url]) => <SurfaceMesh key={`${layer.key}-${phase}-${url}`} layer={layer} phase={phase} url={url} />))}
    <axesHelper args={[2]} visible={project.displaySettings.showAxes} /><FitController atoms={project.atoms} /><WeightedBlendedOIT />
  </>
}

export function ReactionPathControls() {
  const calculationKind = useProjectStore(s => s.calculationKind)
  const status = useProjectStore(s => s.reactionStatus)
  const playback = useProjectStore(s => s.reactionPath)
  const frameIndex = useProjectStore(s => s.reactionFrameIndex)
  const setFrame = useProjectStore(s => s.setReactionFrame)
  const setPlaying = useProjectStore(s => s.setReactionPlaying)
  const error = useProjectStore(s => s.reactionError)
  const reactionProduct = useProjectStore(s => s.reactionProduct)
  const selectedOrbital = useProjectStore(s => s.selectedOrbital)
  const result = useProjectStore(s => s.result)
  const [orbitalTrack, setOrbitalTrack] = useState<{ active: boolean; loading: boolean; error?: string; frameSurfaces?: Record<string, Record<string, string>> }>({ active: true, loading: false })
  const orbitalRequest = useRef<AbortController | undefined>(undefined)
  const upsertSurface = useProjectStore(s => s.upsertSurface)
  const removeSurface = useProjectStore(s => s.removeSurface)
  const reactionIsovalue = useProjectStore(s => s.surfaces.find(layer => layer.key === 'reaction-path-mo')?.isovalue ?? 0.03)
  const requestRef = useRef<number | undefined>(undefined)
  const previousTime = useRef(0)

  useEffect(() => {
    if (status !== 'playing' || !playback) return
    const tick = (time: number) => {
      if (!previousTime.current) previousTime.current = time
      if (time - previousTime.current >= REACTION_PLAYBACK_FRAME_MS) {
        previousTime.current = time
        const state = useProjectStore.getState()
        const next = advancePlaybackFrame(state.reactionFrameIndex, playback.displayFrames.length)
        state.setReactionFrame(next.index)
        if (!next.playing) state.setReactionPlaying(false)
      }
      if (useProjectStore.getState().reactionStatus === 'playing') requestRef.current = requestAnimationFrame(tick)
    }
    requestRef.current = requestAnimationFrame(tick)
    return () => {
      if (requestRef.current !== undefined) cancelAnimationFrame(requestRef.current)
      requestRef.current = undefined
      previousTime.current = 0
    }
  }, [status, playback])

  useEffect(() => {
    orbitalRequest.current?.abort()
    if (!selectedOrbital || !result || !playback) {
      setOrbitalTrack({ active: true, loading: false })
      return
    }
    const controller = new AbortController(); orbitalRequest.current = controller
    setOrbitalTrack({ active: true, loading: true })
    api.reactionOrbitalTrack(result.job_id, selectedOrbital, reactionIsovalue, controller.signal).then(track => {
      if (!controller.signal.aborted) setOrbitalTrack({ active: track.active, loading: false, frameSurfaces: track.frameSurfaces })
    }).catch(error => {
      if (!controller.signal.aborted) setOrbitalTrack({ active: false, loading: false, error: (error as Error).message })
    })
    return () => controller.abort()
  }, [selectedOrbital, result, playback, reactionIsovalue, removeSurface])

  useEffect(() => {
    if (calculationKind !== 'reaction-path') removeSurface('reaction-path-mo')
    return () => removeSurface('reaction-path-mo')
  }, [calculationKind, removeSurface])

  useEffect(() => {
    if (!selectedOrbital || !playback || orbitalTrack.loading) return
    const meshUrls = orbitalTrack.frameSurfaces?.[String(frameIndex)]
    if (!meshUrls) {
      removeSurface('reaction-path-mo')
      return
    }
    const calculated = playback.displayFrames[frameIndex].isCalculated
    upsertSurface({
      key: 'reaction-path-mo', name: calculated ? '계산된 MO' : '보간된 MO', field: 'mo',
      orbitalInternalId: selectedOrbital, spin: selectedOrbital.startsWith('alpha:') ? 'alpha' : selectedOrbital.startsWith('beta:') ? 'beta' : 'restricted',
      visible: true, opacity: .55, isovalue: reactionIsovalue, positiveColor: '#45b8ff', negativeColor: '#ff6a8a', meshUrls, reactionFrame: true,
    })
  }, [selectedOrbital, playback, frameIndex, orbitalTrack, reactionIsovalue, upsertSurface, removeSurface])

  if (calculationKind !== 'reaction-path') return null
  if (!playback) {
    const notFound = !error || error.startsWith('REACTION_PATH_NOT_FOUND')
    return <div className="reaction-empty" role="status">
      <strong>{reactionProduct && !error ? '반응물과 생성물 endpoint를 준비했습니다.' : notFound ? '지원되는 반응 경로 결과가 없습니다.' : '반응 경로 결과는 있지만 형식 검증에 실패했습니다.'}</strong>
      <span>{status === 'loading-path' ? 'endpoint 최적화와 ORCA NEB 계산을 준비하거나 기존 결과를 찾는 중입니다…' : reactionProduct && !error ? '검증이 완료되면 ORCA 계산을 실행하세요.' : notFound ? '필요한 파일: *_MEP_trj.xyz 또는 *_IRC_Full_trj.xyz' : 'trajectory의 원자 수, 원소 순서와 좌표를 확인하세요.'}</span>
      {error && !notFound && <em>세부 정보: {error}</em>}
    </div>
  }
  const frame = playback.displayFrames[frameIndex]
  const atEnd = frameIndex === playback.displayFrames.length - 1
  const toggle = () => {
    if (status === 'playing') return setPlaying(false)
    if (atEnd) setFrame(playbackStartFrame(frameIndex, playback.displayFrames.length))
    setPlaying(true)
  }
  const pointText = frame.isCalculated
    ? `계산 지점 ${frame.leftImageIndex + 1}/${playback.path.images.length}`
    : `보간됨 · 지점 ${frame.leftImageIndex + 1}→${frame.rightImageIndex + 1}`
  const hasWavefunctions = playback.path.images.every(image => Object.keys(image.orbitalRefs).length > 0)
  return <div className="reaction-controls" aria-label="반응 경로 재생">
    <button className="reaction-play" onClick={toggle} aria-label={status === 'playing' ? '일시정지' : '재생'}>{status === 'playing' ? <Pause /> : <Play />}</button>
    <input aria-label="반응 경로 프레임" type="range" min="0" max={playback.displayFrames.length - 1} step="1" value={frameIndex} onChange={event => { setPlaying(false); setFrame(Number(event.target.value)) }} />
    <div className="reaction-frame-info"><strong>{pointText}</strong><span>경로 위치 {(frame.reactionCoordinate * 100).toFixed(1)}%</span></div>
    <div className="reaction-energy">{frame.relativeEnergyKjMol == null ? '에너지 없음' : `${frame.relativeEnergyKjMol.toFixed(2)} kJ/mol${frame.isCalculated ? '' : ' · 보간값'}`}</div>
    {!hasWavefunctions && <div className="reaction-mo-warning">이 반응 경로에는 이미지별 파동함수 결과가 없습니다. 분자 구조 경로만 재생할 수 있습니다.</div>}
    {selectedOrbital && orbitalTrack.loading && <div className="reaction-mo-warning">선택한 MO의 cube와 중첩을 준비하는 중…</div>}
    {selectedOrbital && !orbitalTrack.loading && !orbitalTrack.active && <div className="reaction-mo-warning">{orbitalTrack.error ?? '대응 오비탈 없음 — 추적 종료'} · 원자 경로는 계속 재생됩니다.</div>}
    <p>계산 경로의 시각적 보간이며 프레임 간격은 실제 시간이 아닙니다.</p>
  </div>
}

export function Viewport() {
  const perspective = useProjectStore(s => s.project.displaySettings.perspective); const update = useProjectStore(s => s.updateProject); const project = useProjectStore(s => s.project)
  return <><Canvas key={perspective ? 'p' : 'o'} dpr={[1, 2]} gl={{ antialias: true, alpha: false }}><Scene /></Canvas><div className="viewport-badge"><button onClick={() => update({ displaySettings: { ...project.displaySettings, perspective: !perspective } })}>{perspective ? 'Perspective' : 'Orthographic'}</button><span>Å</span></div><ReactionPathControls /></>
}
